#!/usr/bin/env python3
"""skill_eval.py — eval-flow 行為評測的 runner（Spec: spec/2026-10-03-skill-evals.md §2.1）。

對 evals/ 下每個情境做三步：建暫存 fixture → 在 fixture 內跑所選 harness CLI → 執行該情境的
check.py 對產物做純檔案斷言。評測對象是「模型拿到需求後照不照 skill 走」，所以 fixture 的規則檔
透過共用安裝器自 repo 現檔產生，不內嵌任何副本（內嵌副本會與本體漂移，量到的就不是現況）。

用法：
  python3 .agent-flow/scripts/skill_eval.py [--dry-run] [--case NAME] [--runs N] [--max-cost-usd X]
                                      [--timeout SEC] [--keep-fixture]

exit：0＝全部斷言符合；1＝任一斷言不符合／使用錯誤／環境錯誤（有 FAIL 時優先於 2）；2＝無 FAIL 但累計成本觸及上限、後續情境未跑（部分結果）。

**不進 pytest 預設套件**：每次執行是付費且非確定性的真實 agent run。首跑分數是量測、不是回歸基線。
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import harness_adapter

HOOKS_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HOOKS_DIR))
EVALS_DIR = os.path.join(ROOT, "evals")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")

# 預算預設值（使用者裁示，Spec §4）：單輪快速取訊號；上限是「跑爆就停」的硬防線，不是目標。
DEFAULT_RUNS = 1
DEFAULT_MAX_COST_USD = 3.0
DEFAULT_TIMEOUT_SEC = 900
# 單一情境的最低可用預算：剩餘預算低於此值就不開 session（實測：剩 0.39 美元開 session 只跑到 1 輪就被
# --max-budget-usd 切斷，結果 JSON 無 result、量到的是預算不足而不是行為）。實測單情境成本 1.6–2.6 美元，
# 門檻取 2.0；仍被切斷者由 is_error／subtype 判成 budget_exhausted、不記 FAIL（見 run_claude）。
MIN_CASE_BUDGET_USD = 2.0

# fixture 要從 repo 複製的規則檔／目錄（評測載入的是這些的現況）。
# .gitignore 與 retro/ 是 Game day 首跑補的：缺 .gitignore 時 prepare gate 把 untracked run/ 算進程式樹快照、
# 恢復者得自己改 .git/info/exclude 才能 commit；缺 retro/RETRO.md 時知識前置落空。兩者都是真實部署會有的檔。
FIXTURE_SOURCES = (".gitignore", "retro")  # adapters and skills come from install_harness.py
# 複製 .claude 時排除：worktree 與 cache 不屬規則
COPY_IGNORE = shutil.ignore_patterns("worktrees", "__pycache__", "*.pyc")


def fail(msg, code=1):
    print(f"[skill-eval] {msg}", file=sys.stderr)
    sys.exit(code)


class _ArgParser(argparse.ArgumentParser):
    """參數錯誤走 exit 1：exit 2 在本 script 專指「成本上限、部分結果」，不可撞碼。"""

    def error(self, message):
        fail(f"參數錯誤：{message}", 1)


def discover_cases(case_filter=None):
    """evals/ 下含 prompt.md 的子目錄即情境；results/ 不是情境。"""
    if not os.path.isdir(EVALS_DIR):
        fail(f"找不到情境目錄 {EVALS_DIR}")
    cases = []
    for name in sorted(os.listdir(EVALS_DIR)):
        d = os.path.join(EVALS_DIR, name)
        if not os.path.isdir(d) or name == "results" or name.startswith("."):
            continue
        if not os.path.isfile(os.path.join(d, "prompt.md")):
            continue
        if case_filter and name != case_filter:
            continue
        cases.append(d)
    if case_filter and not cases:
        fail(f"找不到情境 {case_filter}")
    return cases


def read_prompt(case_dir):
    with open(os.path.join(case_dir, "prompt.md"), encoding="utf-8") as f:
        return f.read().strip()


def claude_argv(prompt, budget_usd, permissions='inherit'):
    return harness_adapter.build_argv('claude', budget_usd=budget_usd, permissions=permissions)


def assert_not_repo(path):
    """拒絕以 repo 本身當 fixture。realpath 不是 abspath：symlink／別名目錄會讓字串比對失效（R-020）。"""
    if os.path.realpath(path) == os.path.realpath(ROOT):
        fail("拒絕以 repo 本身為 fixture：fixture 必須是暫存目錄")


def build_fixture(case_dir, workdir, harness="claude"):
    """workdir/fixture：git init＋以 cp 複製 repo 現檔；有 setup.py 則在 fixture 內執行它。"""
    fixture = os.path.join(workdir, "fixture")
    os.makedirs(fixture)
    assert_not_repo(fixture)
    for src in FIXTURE_SOURCES:
        s = os.path.join(ROOT, src)
        if not os.path.exists(s):
            continue
        d = os.path.join(fixture, src)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=COPY_IGNORE, symlinks=True)
        else:
            shutil.copy2(s, d)
    subprocess.run([sys.executable, os.path.join(ROOT, "install_harness.py"),
                    "--target", fixture, "--harness", harness], check=True, capture_output=True, text=True)
    # Build the synthetic commit history before installing the commit gate.
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "skill-eval@local"],
                ["git", "config", "user.name", "skill-eval"],
                ["git", "add", "-A"],
                ["git", "commit", "-q", "-m", "fixture baseline"]):
        subprocess.run(cmd, cwd=fixture, check=True, capture_output=True)
    setup = os.path.join(case_dir, "setup.py")
    if os.path.isfile(setup):
        r = subprocess.run([sys.executable, setup, fixture], cwd=fixture, capture_output=True, text=True,
                           env={**os.environ, "AGENT_FLOW_HARNESS": harness})
        if r.returncode != 0:
            raise RuntimeError(f"setup.py 失敗（exit {r.returncode}）：{r.stderr.strip()[-400:]}")
    subprocess.run([sys.executable, os.path.join(ROOT, "install_harness.py"),
                    "--target", fixture, "--git-hook-only"], check=True, capture_output=True)
    return fixture


def run_harness(harness, fixture, prompt, budget_usd, timeout, permissions='inherit', model=None):
    argv = harness_adapter.build_argv(harness, budget_usd=budget_usd if harness == 'claude' else None,
                                     permissions=permissions, model=model)
    try:
        proc = subprocess.run(argv, input=prompt, cwd=fixture, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"超時（{timeout} 秒）"
    except OSError as e:
        return None, "", f"無法啟動 {harness}：{e}"
    data = harness_adapter.parse_result(harness, proc.stdout, proc.returncode)
    if data['budget_exhausted']:
        return data, proc.stdout, 'budget_exhausted'
    if data['is_error']:
        return None, proc.stdout, f"輸出不可解析／工具失敗：{data['error']}；{proc.stderr.strip()[-200:]}"
    return data, proc.stdout, ''


def run_claude(fixture, prompt, budget_usd, timeout):
    """Compatibility helper; live execution uses the selected harness."""
    return run_harness('claude', fixture, prompt, budget_usd, timeout)


# verdict → 人讀標籤（DoD 措辭）：pass／fail／checker_error（check.py 本身出錯，不當通過、繼續下一情境）
VERDICT_LABEL = {"pass": "PASS", "fail": "FAIL", "checker_error": "檢查器錯誤", "budget_exhausted": "預算切斷（不計行為）"}


def run_check(case_dir, fixture, result_path):
    """執行情境 check.py；回傳 (verdict, output)。verdict ∈ pass／fail／checker_error。"""
    check = os.path.join(case_dir, "check.py")
    if not os.path.isfile(check):
        return "checker_error", "缺 check.py"
    try:
        r = subprocess.run([sys.executable, check, fixture, result_path],
                           cwd=case_dir, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "checker_error", "check.py 超時"
    out = (r.stdout or "") + (("\n[stderr] " + r.stderr.strip()) if r.stderr.strip() else "")
    # 例外也是 exit 1：未捕捉的例外與 FAIL 同碼（實測），得看 stderr 才分得出「斷言不符」與「檢查器壞了」
    if "Traceback (most recent call last)" in (r.stderr or ""):
        return "checker_error", f"check.py 拋例外\n{out}"
    if r.returncode == 0:
        return "pass", out
    if r.returncode == 1:
        return "fail", out
    return "checker_error", f"check.py exit {r.returncode}\n{out}"


def selected_model(harness):
    with open(os.path.join(ROOT, '.agent-flow/harnesses/models.json'), encoding='utf-8') as stream:
        profile = json.load(stream)[harness]['code-writer']
    if harness == 'codex':
        return profile['model']
    return next((line.split(':', 1)[1].strip() for line in profile['frontmatter'].splitlines()
                 if line.startswith('model:')), None)


def print_plan(cases, args):
    print(f"[skill-eval] dry-run：{len(cases)} 個情境；runs={args.runs} max_cost_usd={args.max_cost_usd} "
          f"timeout={args.timeout}s harness={args.harness}（不呼叫 {args.harness}）")
    for c in cases:
        prompt = read_prompt(c)
        head = prompt.splitlines()[0] if prompt else ""
        has_setup = os.path.isfile(os.path.join(c, "setup.py"))
        print(f"\n## {os.path.basename(c)}")
        print(f"  fixture: <tmp>/skill-eval-<id>/fixture（共用安裝器產生 {args.harness} 設定；"
              f"{'有' if has_setup else '無'} setup.py）")
        print(f"  argv: {' '.join(harness_adapter.build_argv(args.harness, model=args.model, permissions=args.permissions, budget_usd=args.max_cost_usd if args.harness == 'claude' else None)[:-1])} \"{head[:60]}…\"")
        print(f"  check: python3 check.py <fixture> <result.json>")


def main():
    ap = _ArgParser(description="eval-flow 行為評測 runner（不進 pytest 預設套件）")
    ap.add_argument("--dry-run", action="store_true", help="只印執行計畫，不呼叫 CLI、不建 fixture")
    ap.add_argument("--case", help="只跑指定情境（evals/ 下的目錄名）")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS, help=f"每情境執行次數（預設 {DEFAULT_RUNS}）")
    ap.add_argument("--max-cost-usd", type=float, default=DEFAULT_MAX_COST_USD,
                    help=f"累計成本上限，觸及即停（預設 {DEFAULT_MAX_COST_USD}）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC, help="單次 claude 執行秒數上限")
    ap.add_argument("--keep-fixture", action="store_true", help="保留 fixture 目錄供人工檢視")
    ap.add_argument('--harness', choices=harness_adapter.HARNESSES, default='claude')
    ap.add_argument('--permissions', choices=harness_adapter.PERMISSIONS, default='inherit')
    ap.add_argument('--model', help='Explicit model; omitted uses the project profile')
    args = ap.parse_args()
    args.model = args.model or selected_model(args.harness)
    if args.runs < 1:
        fail("--runs 須 ≥1")
    if not __import__("math").isfinite(args.max_cost_usd) or args.max_cost_usd <= 0:
        fail("--max-cost-usd 須 >0")

    cases = discover_cases(args.case)
    if args.dry_run:
        print_plan(cases, args)
        return 0

    if args.timeout <= 0:
        fail('--timeout 須 >0')
    if shutil.which(args.harness) is None:
        fail(f"找不到 {args.harness} CLI（不在 PATH）")
    if args.harness == 'codex':
        print('[skill-eval] Codex CLI 不提供美元預算限制；成本記 unknown，以 runs/timeout 限制執行。', file=sys.stderr)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    results_path = os.path.join(RESULTS_DIR, f"{stamp}.json")
    records = []
    total_cost = 0.0
    any_fail = False
    ceiling_hit = False

    for case_dir in cases:
        name = os.path.basename(case_dir)
        prompt = read_prompt(case_dir)
        for i in range(1, args.runs + 1):
            remaining = args.max_cost_usd - total_cost
            if args.harness == 'claude' and remaining < MIN_CASE_BUDGET_USD:
                ceiling_hit = True
                break
            workdir = tempfile.mkdtemp(prefix="skill-eval-")
            rec = {"case": name, "run": i, "verdict": None, "cost_usd": None, "turns": None,
                   "session_id": None, "harness": args.harness, "model": args.model, "permissions": args.permissions, "note": "", "fixture": workdir if args.keep_fixture else None}
            try:
                fixture = build_fixture(case_dir, workdir, args.harness)
            except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
                rec["verdict"] = "checker_error"
                rec["note"] = f"fixture 建立失敗：{e}"
                records.append(rec)
                any_fail = True
                print(f"[skill-eval] {name} run {i}: fixture 建立失敗 — {e}")
                if not args.keep_fixture:
                    shutil.rmtree(workdir, ignore_errors=True)
                continue
            data, raw, note = run_harness(args.harness, fixture, prompt, remaining, args.timeout, args.permissions, args.model)
            result_path = os.path.join(workdir, "result.json")
            with open(result_path, "w", encoding="utf-8") as f:
                f.write(raw if data is None else json.dumps(data, ensure_ascii=False, indent=2))
            # 成本記帳：拿不到 total_cost_usd（超時／不可解析／缺鍵）時保守記該 session 的預算上限，
            # 否則失敗路徑記 $0、下一情境又拿到完整 remaining，累計上限形同虛設
            cost = data.get("total_cost_usd") if isinstance(data, dict) else None
            if args.harness == 'codex':
                rec['cost_usd'] = None
                rec['cost_unknown'] = True
            elif isinstance(cost, (int, float)):
                rec["cost_usd"] = cost
            else:
                rec["cost_usd"] = remaining
                rec["cost_unknown"] = True
            total_cost += rec["cost_usd"] or 0
            cost_label = "unknown" if rec["cost_usd"] is None else f"${rec['cost_usd']:.2f}"
            if data is None:
                rec["verdict"] = "fail"
                rec["note"] = note
                any_fail = True
                print(f"[skill-eval] {name} run {i}: FAIL — {note}（成本狀態：{cost_label}）")
            elif note == "budget_exhausted":
                rec["verdict"] = "budget_exhausted"
                rec["turns"] = data.get("num_turns")
                rec["session_id"] = data.get("session_id")
                rec["note"] = f"session 被 --max-budget-usd {remaining:.2f} 切斷（subtype={data.get('subtype')}），不計行為"
                ceiling_hit = True
                print(f"\n## {name} run {i}: {VERDICT_LABEL['budget_exhausted']}  cost={cost_label}  累計=${total_cost:.2f}")
            else:
                rec["turns"] = data.get("num_turns")
                rec["session_id"] = data.get("session_id")
                verdict, out = run_check(case_dir, fixture, result_path)
                rec["verdict"] = verdict
                rec["check_output"] = out
                if verdict != "pass":
                    any_fail = True
                print(f"\n## {name} run {i}: {VERDICT_LABEL[verdict]}  cost={cost_label}  "
                      f"turns={rec['turns']}  成本狀態={'unknown' if rec.get('cost_unknown') else 'known'}")
                print(out.rstrip())
            records.append(rec)
            if not args.keep_fixture:
                shutil.rmtree(workdir, ignore_errors=True)
            if args.harness == 'claude' and total_cost >= args.max_cost_usd:
                ceiling_hit = True
                break
        if ceiling_hit:
            break

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"stamp": stamp, "runs": args.runs, "max_cost_usd": args.max_cost_usd,
                   "harness": args.harness, "model": args.model, "permissions": args.permissions,
                   "total_cost_usd": round(total_cost, 4) if args.harness == "claude" else None, "ceiling_hit": ceiling_hit,
                   "records": records}, f, ensure_ascii=False, indent=2)
    done = len(records)
    total_label = f"${total_cost:.2f}（上限 ${args.max_cost_usd:.2f}）" if args.harness == "claude" else "unknown（Codex CLI 不提供美元成本）"
    print(f"\n[skill-eval] 完成 {done} 次執行，累計 {total_label}"
          f"→ {os.path.relpath(results_path, ROOT)}")
    if ceiling_hit:
        skipped = [os.path.basename(c) for c in cases if not any(r["case"] == os.path.basename(c) for r in records)]
        print(f"[skill-eval] 成本上限觸及（剩餘不足單情境最低 ${MIN_CASE_BUDGET_USD:.2f}）：未跑情境 {skipped or '無'}；"
              f"本輪為部分結果", file=sys.stderr)
    # exit 優先序：有 FAIL → 1（部分結果不可蓋掉失敗）；只觸上限 → 2；全過 → 0
    if any_fail:
        return 1
    return 2 if ceiling_hit else 0


if __name__ == "__main__":
    sys.exit(main())
