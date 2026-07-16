#!/usr/bin/env python3
"""test-strategy skill 的執行端：測試 baseline 建立與「新增失敗」判定。

用法：
  python3 .claude/hooks/test_baseline.py baseline [--cmd "pytest -q"] [--runs 2] [--run-id ID] [--fresh]
  python3 .claude/hooks/test_baseline.py check    [--cmd "pytest -q"] [--strike-key sub_task_1] [--run-id ID]
  python3 .claude/hooks/test_baseline.py related  --files src/a.py src/b.py

--cmd 省略時讀 run/<run_id>.json（manifest）的 test_command 欄位——全套指令的
single source of truth，保證 baseline 與 check 的範圍一致。

baseline：跑 --runs 次（預設 2），每次都失敗的測試記為 stable（既有壞測試，
          之後不擋），只失敗部分次數的記為 flaky。寫入 run/<run_id>.test_baseline.json。
          既有 baseline 檔中存在「head_sha == 目前 HEAD 且 cmd 相同」者 → 直接沿用
          其 stable/flaky 名單（baseline 記的是進場 HEAD 的既有失敗快照，同進場 HEAD
          即可沿用，免重跑全套；本 run 工作樹的新變更由 check 把關），--fresh 強制重建。
check：   跑一次，扣掉 baseline 的 stable / flaky 後若有新失敗，重跑一次過濾 flaky：
          重跑仍失敗 → 真的新增失敗，exit 2；重跑通過 → 併入 flaky 名單，放行。
          --strike-key 提供時累計該 key 的連續真失敗次數（通過即歸零），
          達 2 次時提示停止自行修復、回報使用者。
related： 由變更檔案清單找出相關測試檔（測試檔命名慣例 + grep 引用），輸出路徑清單。

run_id 未指定時讀 eval_state.json 的 run_id。
exit 0 = gate 通過；exit 2 = 有新增穩定失敗（stderr 列清單）；exit 1 = 使用錯誤。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

# 常見測試框架的失敗行樣式；比對不到且 exit != 0 時，整個 suite 當一個單位
FAIL_PATTERNS = [
    re.compile(r"^FAILED (\S+)", re.M),        # pytest
    re.compile(r"^ERROR (\S+)", re.M),         # pytest（collection error）
    re.compile(r"^--- FAIL: (\S+)", re.M),     # go test
    re.compile(r"^FAIL (\S+)", re.M),          # jest / vitest（檔案層級）
    re.compile(r"^\s*[✕×✗] (.+?)(?: \(\d+ ?m?s\))?$", re.M),  # jest / vitest / mocha
]

TEST_FILE_RE = re.compile(
    r"(^test_.*|.*_test\.\w+$|.*\.test\.\w+$|.*\.spec\.\w+$|.*Tests?\.\w+$)"
)
TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}


def fail(msg, code=1):
    print(f"[test-gate] {msg}", file=sys.stderr)
    sys.exit(code)


def run_tests(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    fails = set()
    for pat in FAIL_PATTERNS:
        fails.update(m.strip() for m in pat.findall(out))
    if p.returncode != 0 and not fails:
        fails.add("__suite__")
    return fails, p.returncode


def resolve_run_id(args):
    if args.run_id:
        return args.run_id
    try:
        with open("eval_state.json", encoding="utf-8") as f:
            run_id = json.load(f).get("run_id")
    except (OSError, json.JSONDecodeError):
        run_id = None
    if not run_id:
        fail("無法定位 run_id：eval_state.json 不存在或缺 run_id，請用 --run-id 指定")
    return run_id


def baseline_path(run_id):
    return f"run/{run_id}.test_baseline.json"


def resolve_cmd(args, run_id):
    if args.cmd:
        return args.cmd
    manifest = f"run/{run_id}.json"
    try:
        with open(manifest, encoding="utf-8") as f:
            cmd = json.load(f).get("test_command")
    except (OSError, json.JSONDecodeError):
        cmd = None
    if not cmd:
        fail(f"未指定 --cmd 且 {manifest} 無 test_command：請先把全套測試指令寫入 manifest，或用 --cmd 指定")
    return cmd


def git_head():
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return p.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None  # 非 git repo：不重用，照常全新建立


def find_reusable_baseline(run_id, cmd, head):
    """掃既有 baseline 檔，找「head_sha == 目前 HEAD 且 cmd 相同」者供沿用。
    多個符合時取排序最後者——契約：run_id 以可字典序排序的日期開頭
    （YYYY-MM-DD-slug），字典序即時序；命名慣例若變，此處要換排序鍵。
    找不到回 None。"""
    if not head:
        return None
    own = baseline_path(run_id)
    candidate = None
    for path in sorted(glob.glob("run/*.test_baseline.json")):
        if path == own:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("head_sha") == head and data.get("cmd") == cmd:
            candidate = data
    return candidate


def cmd_baseline(args):
    run_id = resolve_run_id(args)
    cmd = resolve_cmd(args, run_id)
    head = git_head()
    if not args.fresh:
        prev = find_reusable_baseline(run_id, cmd, head)
        if prev:
            os.makedirs("run", exist_ok=True)
            _save(baseline_path(run_id), {
                "run_id": run_id,
                "cmd": cmd,
                "head_sha": head,
                "reused_from": prev.get("run_id"),
                "stable_failures": prev.get("stable_failures", []),
                "flaky": prev.get("flaky", []),
                "strikes": {},
            })
            print(
                f"[test-gate] 沿用 {prev.get('run_id')} 的 baseline"
                f"（HEAD 未變、cmd 相同），免重跑全套建基準；要強制重建用 --fresh"
            )
            return
    results = []
    for i in range(args.runs):
        fails, _ = run_tests(cmd)
        results.append(fails)
        print(f"[test-gate] baseline 第 {i + 1}/{args.runs} 次：{len(fails)} 個失敗")
    stable = set.intersection(*results) if results else set()
    flaky = set.union(*results) - stable if results else set()
    os.makedirs("run", exist_ok=True)
    data = {
        "run_id": run_id,
        "cmd": cmd,
        "head_sha": head,
        "stable_failures": sorted(stable),
        "flaky": sorted(flaky),
        "strikes": {},
    }
    with open(baseline_path(run_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(
        f"[test-gate] baseline 已寫入 {baseline_path(run_id)}："
        f"stable(既有壞測試，不擋) {len(stable)} 個、flaky {len(flaky)} 個"
    )
    if stable:
        print("[test-gate] 既有壞測試（欠帳，僅記錄）：" + ", ".join(sorted(stable)))


def cmd_check(args):
    run_id = resolve_run_id(args)
    path = baseline_path(run_id)
    if not os.path.exists(path):
        fail(f"{path} 不存在：先跑 baseline 子命令建立基準，再跑 check")
    with open(path, encoding="utf-8") as f:
        base = json.load(f)
    known = set(base.get("stable_failures", [])) | set(base.get("flaky", []))
    cmd = resolve_cmd(args, run_id)

    fails, _ = run_tests(cmd)
    new = fails - known
    strikes = base.setdefault("strikes", {})
    key = args.strike_key or "_default"

    if new:
        print(f"[test-gate] 出現 {len(new)} 個非 baseline 的失敗，重跑一次過濾 flaky…")
        fails2, _ = run_tests(cmd)
        real = sorted(new & fails2)
        newly_flaky = sorted(new - fails2)
        if newly_flaky:
            base["flaky"] = sorted(set(base.get("flaky", [])) | set(newly_flaky))
            print(f"[test-gate] 重跑通過、判定為 flaky（記錄不擋）：{', '.join(newly_flaky)}")
    else:
        real = []

    if real:
        strikes[key] = strikes.get(key, 0) + 1
        _save(path, base)
        print(f"[test-gate] BLOCK: 新增穩定失敗 {len(real)} 個：", file=sys.stderr)
        for t in real:
            print(f"  - {t}", file=sys.stderr)
        print(f"[test-gate] {key} 連續失敗第 {strikes[key]} 次", file=sys.stderr)
        if strikes[key] >= 2:
            print(
                "[test-gate] 已達 2 次上限：停止自行修復，"
                "把卡住的測試與已嘗試的修法回報使用者裁決",
                file=sys.stderr,
            )
        sys.exit(2)

    strikes[key] = 0
    _save(path, base)
    ignored = fails & known
    print(
        f"[test-gate] PASS: 無新增穩定失敗"
        + (f"（{len(ignored)} 個 baseline 既有失敗已略過）" if ignored else "")
    )


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def cmd_related(args):
    stems = set()
    for f in args.files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem:
            stems.add(stem)
    related = set()
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        in_test_dir = any(part in TEST_DIR_NAMES for part in dirpath.split(os.sep))
        for name in filenames:
            if not (TEST_FILE_RE.match(name) or in_test_dir):
                continue
            path = os.path.join(dirpath, name).lstrip("./")
            if any(s in name for s in stems):
                related.add(path)
                continue
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            if any(re.search(rf"\b{re.escape(s)}\b", content) for s in stems):
                related.add(path)
    for path in sorted(related):
        print(path)
    if not related:
        print(
            "[test-gate] 找不到相關測試檔（可能是新行為尚無測試，或對映不到慣例）；"
            "Tier 2 新行為必須有測試 item，請確認",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_base = sub.add_parser("baseline")
    p_base.add_argument("--cmd")
    p_base.add_argument("--runs", type=int, default=2)
    p_base.add_argument("--run-id")
    p_base.add_argument("--fresh", action="store_true")
    p_base.set_defaults(func=cmd_baseline)

    p_check = sub.add_parser("check")
    p_check.add_argument("--cmd")
    p_check.add_argument("--strike-key")
    p_check.add_argument("--run-id")
    p_check.set_defaults(func=cmd_check)

    p_rel = sub.add_parser("related")
    p_rel.add_argument("--files", nargs="+", required=True)
    p_rel.set_defaults(func=cmd_related)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
