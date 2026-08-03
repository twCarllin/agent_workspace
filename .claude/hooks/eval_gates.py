#!/usr/bin/env python3
"""Eval Flow gate 檢查。

兩種模式：
  --hook            PreToolUse hook：stdin 讀 hook JSON。
                    Bash → 攔 `git commit`，跑 commit gate；
                    Task/Agent → 依 manifest.phase 狀態機攔亂序的 subagent 呼叫
  --validate <path> 獨立驗證單一 eval_state / eval 歸檔檔的不變量

exit 0 = 放行；exit 2 = block（stderr 說明原因，回饋給 Claude 修正）。
"""
import glob
import json
import os
import re
import subprocess
import sys

GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-[A-Za-z0-9-]+(?:[= ]\S+)?\s+)*commit\b")
# 衍生檔（.eval.json / .test_baseline.json）的排除寫進 pattern 本身（單一判定點），
# 不散落在各呼叫點用 endswith 補丁——新增衍生檔種類時只改這裡。
#
# 本 pattern 的合法匹配對象：
#   - run/<run_id>.json                       一般主 manifest
#   - run/<run_id>-item-<id>.json             Tier 2 fan-out 子 manifest
#       └ run_id 群組捕捉結果含「-item-<id>」後綴；子 manifest 是獨立合法 manifest，
#         與主 manifest 平行受同一 gate 管轄；各子 run 各自歸檔自己的 .eval.json。
#
# 負向後查排除的衍生檔（不屬於 manifest）：
#   - *.eval.json          （主 run 歸檔）
#   - *.test_baseline.json （測試基線快照）
#   - *-item-<id>.eval.json（子 run 歸檔，同樣被「(?<!\.eval)」正確排除）
#
# 子 manifest 額外欄位：
#   parent_run_id（可選）— 指向父 run_id（契約定義於 eval-flow / parallel-run skill）。
#   本檔 gate 目前不消費此欄（故多帶此欄不影響任何判定、不會 KeyError）；
#   未來任何消費點須以 .get() 讀取，以相容無此欄的舊版 manifest。
#
# !! 本 pattern 是「以檔名識別 manifest 身分」的唯一判定點 !!
# 新增子 manifest 命名規則或衍生檔種類時，必須先在此更新 pattern 與上方說明，
# 不可在呼叫點用 endswith / startswith 補丁繞過（違反單一判定點原則）。
MANIFEST_RE = re.compile(
    r"^run/(?P<run_id>[^/]+?)(?<!\.eval)(?<!\.test_baseline)\.json$"
)

TEST_FILE_NAME_RE = re.compile(r"^(test_.*|.*_test)\.py$")
TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec"}

# phase 狀態機：manifest.phase 依前置步驟推進，subagent 呼叫需達到對應 phase
PHASES = ["init", "risk_done", "usage_confirmed", "decomposed", "completed"]
AGENT_MIN_PHASE = {
    "usage-analyzer": "risk_done",      # 前置 1（風險分析）完成才可跑前置 2
    "impact-analyzer": "usage_confirmed",  # 前置 2 使用者確認後才可跑前置 2.5
    "task-decomposer": "usage_confirmed",  # 前置 2 使用者確認後才可分拆
    "code-writer": "decomposed",        # 前置 3 完成才可進循環
}


# hook 模式下被擋時附上；流程細節不在常駐 context，被擋常代表 skill 未載入或已被 compact
SKILL_HINT = "（流程細節住在 eval-flow skill：若尚未載入或 context 被 compact，先載入 skills/eval-flow/SKILL.md，再依檔案狀態修正）"
_hint_enabled = False


def log_gate_hit(msg):
    """gate 命中遙測：append 到 run/gate_hits.log（stats.py 彙總用）。
    只在 run/ 已存在時寫（不在非 flow 專案留檔）；失敗不影響攔截本身。"""
    if not os.path.isdir("run"):
        return
    try:
        from datetime import datetime
        first_line = msg.splitlines()[0][:200]
        with open("run/gate_hits.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{first_line}\n")
    except OSError:
        pass


def block(msg):
    if _hint_enabled:
        log_gate_hit(msg)
    hint = f"\n[gate-check] {SKILL_HINT}" if _hint_enabled else ""
    print(f"[gate-check] BLOCK: {msg}{hint}", file=sys.stderr)
    sys.exit(2)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        block(f"{path} 無法讀取或非合法 JSON（{e}）")


def _validate_credentials(obj, source):
    """驗四項憑據（per-subtask 與 Tier 1 manifest 共用單一判定點）。"""
    if obj.get("local_test_passed") is not True:
        block(f"{source} local_test_passed 非 true：本地測試 gate 未通過，須先完成 step 5 驗證\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-test <id> --passed --evidence \"指令＋結果摘要\"`；Tier 1 直接填 manifest 同名欄")
    evidence = obj.get("local_test_evidence")
    if not (isinstance(evidence, str) and evidence.strip()):
        block(f"{source} local_test_evidence 為空：須記錄驗證證據（跑了什麼指令、看到什麼結果）\n"
              f"→ 補救：同上，`set-test <id> --passed --evidence \"...\"` 的 --evidence 不可省；Tier 1 直接填 manifest 同名欄")
    reds = obj.get("review_reds")
    if not (isinstance(reds, int) and not isinstance(reds, bool)) or reds < 0:
        block(f"{source} review_reds 未留痕或非合法非負整數：step 3 須記錄 🔴 數（非負整數）\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-review <id> <reds 數字>`；Tier 1 直接填 manifest 同名欄")
    if obj.get("verify_passed") is not True:
        block(f"{source} verify_passed 非 true：reviewer 完成度節尚未通過\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-verify <id>`（無 --passed 旗標）；Tier 1 直接填 manifest 同名欄")


def validate_state(state, source, require_passed=False):
    # rounds 品質不變量已隨 eval-scorer 移除；舊格式歸檔（含 rounds）寬容放行
    if not state.get("run_id"):
        block(f"{source} 缺 run_id")
    for st in state.get("sub_tasks", []):
        if require_passed:
            name = st.get("name") or st.get("id")
            if st.get("status") != "passed":
                block(f"{source} sub_task「{name}」status 非 passed（{st.get('status')}）\n"
                      f"→ 補救：該 sub_task 走完循環後 `python3 .claude/hooks/eval_state.py set-status <id> passed`（status 可選 passed／failed／in_progress）")
            _validate_credentials(st, f"{source} sub_task「{name}」")


def check_manifest(manifest_path, staged):
    m = load_json(manifest_path)
    run_id = MANIFEST_RE.match(manifest_path).group("run_id")

    if not (m.get("spec_path") or m.get("spec_inline")):
        block(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空")
    if m.get("status") != "completed":
        block(f"{manifest_path} status 非 completed（{m.get('status')}），不可 commit")

    if m.get("tier") == "hotfix":
        if not isinstance(m.get("debt"), list):
            block(f"{manifest_path} 為 hotfix 但缺 debt 欄位（欠帳清單，如 [\"risk\", \"test\", \"retro\"]）")
        return  # hotfix 不走循環評分，豁免 eval 歸檔檔要求；欠帳由 debt gate 追討

    if m.get("tier") == "B":
        if m.get("bootstrap_verified") is not True:
            block(
                f"{manifest_path} 為 Tier B 但 bootstrap_verified 非 true："
                f"DoD 兩條（本地 build/run 跑得通、測試框架＋示範測試會跑）未驗證，不可 commit"
            )
        return  # Tier B 不走循環評分，豁免 eval 歸檔檔要求

    tier = m.get("tier")
    archive_path = f"run/{run_id}.eval.json"

    if archive_path in staged:
        # 歸檔檔已 staged：Tier 1（向後相容）＋ Tier 2（現行）共用此路徑（單一判定點）
        archive = load_json(archive_path)
        if archive.get("run_id") != run_id:
            block(f"{archive_path} 的 run_id（{archive.get('run_id')}）與 manifest 不一致")
        validate_state(archive, archive_path, require_passed=True)
    elif tier == 1 or tier == "1":
        # Tier 1 豁免歸檔檔，改驗 manifest 自身四欄憑據（與 validate_state 共用 _validate_credentials）
        _validate_credentials(m, manifest_path)
    else:
        block(f"{manifest_path} 已 staged，但 {archive_path} 未 staged：須先歸檔 eval_state 再 commit\n"
              f"→ 補救：`python3 .claude/hooks/eval_state.py archive` 產出 {archive_path}，再 `git add {archive_path}`")


def manifest_phase(manifest):
    """讀 manifest.phase；舊 manifest 無此欄時由既有欄位推導（向後相容）。"""
    phase = manifest.get("phase")
    if phase in PHASES:
        return phase
    if manifest.get("task_file"):
        return "decomposed"
    if manifest.get("usage_report_path"):
        return "usage_confirmed"
    return "init"


def load_json_quiet(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def check_other_runs(current_run_id):
    """欠帳 gate ＋ 單一 run gate：掃本工作區的其他 manifest。"""
    for path in sorted(glob.glob("run/*.json")):
        if not MANIFEST_RE.match(path):
            continue
        other = load_json_quiet(path)
        if not isinstance(other, dict):
            continue
        other_id = other.get("run_id")
        if other.get("debt"):
            block(
                f"{path} 有未清欠帳 debt={other.get('debt')}（hotfix 遺留）："
                f"須先還清（補 risk 分析／回歸測試／retro，還一項移除一項）才可啟動新 run"
            )
        if other_id != current_run_id and other.get("status") == "in_progress":
            block(
                f"本工作區已有另一個 in_progress 的 run（{path}）："
                f"一個 worktree 同時只允許一個 run。先收尾／封存該 run，"
                f"要並行請開 git worktree，中斷續跑依 eval-flow-resume skill"
            )


def is_test_file(path):
    if not path.endswith(".py"):
        return False
    if TEST_FILE_NAME_RE.match(os.path.basename(path)):
        return True
    return any(part in TEST_DIR_NAMES for part in path.split("/")[:-1])


def check_staged_test_lint(staged):
    """假測試 lint gate：flow 收尾 commit 時，staged 的 Python 測試檔須通過 test_lint.py。"""
    test_files = [p for p in sorted(staged) if is_test_file(p) and os.path.exists(p)]
    if not test_files:
        return
    lint = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_lint.py")
    if not os.path.exists(lint):
        return  # 部署未含 lint script 時不擋（防線以存在的工具為準）
    p = subprocess.run(
        [sys.executable, lint, *test_files], capture_output=True, text=True
    )
    if p.returncode != 0:
        detail = (p.stdout + p.stderr).strip()
        block(f"假測試 lint 未過（修測試或以行尾 `# testlint: allow` 豁免並留痕）：\n{detail}")


def _find_unique_tier1_inprogress():
    """掃 run/ 找唯一一個 tier==1 且 status==in_progress 的 manifest。
    回傳 (manifest_path, manifest_dict) 或 None（找不到或多個）。
    須重用 MANIFEST_RE（單一判定點，硬約束）。"""
    found = []
    for path in sorted(glob.glob("run/*.json")):
        if not MANIFEST_RE.match(path):
            continue
        m = load_json_quiet(path)
        if not isinstance(m, dict):
            continue
        tier = m.get("tier")
        if (tier == 1 or tier == "1") and m.get("status") == "in_progress":
            found.append((path, m))
    return found[0] if len(found) == 1 else None


def check_task_gate(tool_input):
    agent = tool_input.get("subagent_type", "")
    required = AGENT_MIN_PHASE.get(agent)
    if not required:
        sys.exit(0)  # 非流程管制的 agent，不擋

    # 前置步驟（單一判定點）：取得 manifest_path、manifest、state
    # eval_state.json 存在 → Tier 2 常規路徑；否則 → Tier 1 豁免路徑
    if os.path.exists("eval_state.json"):
        state = load_json("eval_state.json")
        run_id = state.get("run_id")
        if not run_id:
            block(f"eval_state.json 缺 run_id，無法定位 manifest；呼叫 {agent} 被擋\n"
                  f"→ 補救：`python3 .claude/hooks/eval_state.py init --run-id <run_id>` 重建（run_id 須與 run/<run_id>.json 一致）")
        manifest_path = f"run/{run_id}.json"
        if not os.path.exists(manifest_path):
            block(f"{manifest_path} 不存在（前置 0 未完成），不可呼叫 {agent}")
        manifest = load_json(manifest_path)
    else:
        state = None
        # DoD (a)：找唯一 tier 1 in_progress manifest 作為當前 run 依據
        tier1 = _find_unique_tier1_inprogress()
        if tier1 is None:
            block(f"呼叫 {agent} 前須完成前置 0：eval_state.json 不存在（run 未初始化）\n"
                  f"→ 補救：`python3 .claude/hooks/eval_state.py init --run-id <run_id>`（Tier 1 不建 eval_state.json，若本 run 為 Tier 1 請改走精簡路徑）")
        manifest_path, manifest = tier1
        run_id = MANIFEST_RE.match(manifest_path).group("run_id")

    # 以下 gate 邏輯為單一共用路徑（Tier 1 與 Tier 2 不再各有一份）
    check_other_runs(run_id)

    if not (manifest.get("spec_path") or manifest.get("spec_inline")):
        block(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空，不可呼叫 {agent}")

    phase = manifest_phase(manifest)
    if PHASES.index(phase) < PHASES.index(required):
        block(
            f"phase 狀態機：呼叫 {agent} 需 manifest.phase >= {required}，"
            f"目前為 {phase}。請先完成缺少的前置步驟並更新 manifest.phase"
        )

    if agent == "task-decomposer":
        urp = manifest.get("usage_report_path")
        if not urp:
            block(f"{manifest_path} usage_report_path 為空：前置 2 未經使用者確認，不可分拆 task")
        if urp == "skipped":
            block("Tier 1（usage_report_path: skipped）不呼叫 task-decomposer，由主 flow 直接建 task 檔")

    if agent == "code-writer":
        if not manifest.get("task_file"):
            block(f"{manifest_path} task_file 為空：前置 3 未完成，不可呼叫 code-writer")
        # risk_analysis.blocking 遍歷：僅在 state 存在（Tier 2）時執行，Tier 1 無 sub_tasks 可遍歷
        if state is not None:
            for st in state.get("sub_tasks", []):
                if (st.get("risk_analysis") or {}).get("blocking") is True:
                    name = st.get("name") or st.get("id")
                    block(f"sub_task「{name}」風險分析 blocking=true（🔴），須先修改 Spec 重新分析")

    sys.exit(0)


def _git_toplevel(path):
    """以 git rev-parse --show-toplevel 解析 path 所屬 git root；失敗回 None。
    capture_output=True 吸掉 stderr（非 git 目錄會輸出 fatal: not a git repository）。
    errors="replace"：路徑含非 UTF-8 位元組時不拋 UnicodeDecodeError（ValueError 子類，
    不在下方 except 涵蓋範圍內，逸出會使 hook 以非 2 的碼結束＝gate 靜默不套用）。
    兩側同屬一個 repo 時等量替換、比對仍相等 → 退回 CLAUDE_PROJECT_DIR（fail-safe）。
    跨 worktree 且僅一側含非 UTF-8 位元組時比對不相等，會回傳含 U+FFFD 的路徑、使
    run_hook 的 os.chdir 拋 OSError（fail-open）——此分支不另加防護：toplevel 是 cwd
    的祖先，payload.cwd 既為合法 UTF-8 字串，其祖先亦然，故實務上不可達。"""
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, errors="replace", timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve_root(payload):
    """解析 run_hook() 應 chdir 的工作區根目錄。H1 最小偏離設計：只有確認
    cwd 與 CLAUDE_PROJECT_DIR 屬不同 git worktree 時才改變行為，其餘一律回 CPD。
    """
    cpd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    cwd = payload.get("cwd")

    # H1: 無 cwd 鍵 → 嚴格回 CPD（不落到 os.getcwd()；CPD 為 None 時已於上行退路）
    if cwd is None:
        return cpd

    # H1: 字串相等短路，跳過 git（覆蓋主工作區最熱路徑）
    if cpd == cwd:
        return cpd

    # 各跑一次 git rev-parse 吸收 symlink/尾斜線差異
    cwd_top = _git_toplevel(cwd)
    cpd_top = _git_toplevel(cpd)

    # 兩者皆成功且 toplevel 不相等 → 回 cwd 的 toplevel（唯一改變行為的分支）
    if cwd_top is not None and cpd_top is not None and cwd_top != cpd_top:
        return cwd_top

    # 其餘所有情況（任一失敗、或相等）→ 回 CPD
    return cpd


def run_hook():
    global _hint_enabled
    _hint_enabled = True  # 只在 hook 模式附提示；--validate 為人工自檢，不需要
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # 非預期輸入，不擋

    root = _resolve_root(payload)
    os.chdir(root)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name in ("Task", "Agent"):
        check_task_gate(tool_input)

    command = tool_input.get("command", "")
    if not GIT_COMMIT_RE.search(command):
        sys.exit(0)

    if os.path.exists("eval_state.json"):
        block(
            "eval_state.json 仍存在。須先歸檔為 run/<run_id>.eval.json 並清除後才可 commit；"
            "若為失敗收尾（status: failed），依規則由使用者裁決，不可由 Claude commit\n"
            "→ 補救：`python3 .claude/hooks/eval_state.py archive`（會驗四項憑據、寫出歸檔檔並刪除 eval_state.json），"
            "再把 manifest 標 status: completed 並 git add 歸檔檔"
        )

    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        sys.exit(0)  # 非 git repo 等情況，不擋
    staged = set(out.split())

    manifests = [p for p in sorted(staged) if MANIFEST_RE.match(p)]
    for path in manifests:
        check_manifest(path, staged)
    if manifests:
        check_staged_test_lint(staged)
    sys.exit(0)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--hook"]:
        run_hook()
    elif args[:1] == ["--validate"] and len(args) == 2:
        validate_state(load_json(args[1]), args[1])
        print(f"[gate-check] OK: {args[1]} 不變量檢查通過")
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
