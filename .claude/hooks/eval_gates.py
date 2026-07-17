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
# 不散落在各呼叫點用 endswith 補丁——新增衍生檔種類時只改這裡
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


def validate_state(state, source, require_passed=False):
    # rounds 品質不變量已隨 eval-scorer 移除；舊格式歸檔（含 rounds）寬容放行
    if not state.get("run_id"):
        block(f"{source} 缺 run_id")
    for st in state.get("sub_tasks", []):
        if require_passed:
            name = st.get("name") or st.get("id")
            if st.get("status") != "passed":
                block(f"{source} sub_task「{name}」status 非 passed（{st.get('status')}）")
            if st.get("local_test_passed") is not True:
                block(f"{source} sub_task「{name}」local_test_passed 非 true：本地測試 gate 未通過")
            evidence = st.get("local_test_evidence")
            if not (isinstance(evidence, str) and evidence.strip()):
                block(
                    f"{source} sub_task「{name}」local_test_evidence 為空："
                    f"step 5 須記錄驗證證據（跑了什麼指令、看到什麼結果）"
                )
            reds = st.get("review_reds")
            if not (isinstance(reds, int) and not isinstance(reds, bool)) or reds < 0:
                block(
                    f"{source} sub_task「{name}」review_reds 未留痕或非合法非負整數："
                    f"step 3 code-reviewer 結束後須執行 set-review <id> <🔴數>"
                )
            if st.get("verify_passed") is not True:
                block(
                    f"{source} sub_task「{name}」verify_passed 非 true："
                    f"step 4 task-verifier 尚未通過，須執行 set-verify <id>"
                )


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

    archive_path = f"run/{run_id}.eval.json"
    if archive_path not in staged:
        block(f"{manifest_path} 已 staged，但 {archive_path} 未 staged：須先歸檔 eval_state 再 commit")
    archive = load_json(archive_path)
    if archive.get("run_id") != run_id:
        block(f"{archive_path} 的 run_id（{archive.get('run_id')}）與 manifest 不一致")
    validate_state(archive, archive_path, require_passed=True)


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


def check_task_gate(tool_input):
    agent = tool_input.get("subagent_type", "")
    required = AGENT_MIN_PHASE.get(agent)
    if not required:
        sys.exit(0)  # 非流程管制的 agent，不擋

    if not os.path.exists("eval_state.json"):
        block(f"呼叫 {agent} 前須完成前置 0：eval_state.json 不存在（run 未初始化）")
    state = load_json("eval_state.json")
    run_id = state.get("run_id")
    if not run_id:
        block(f"eval_state.json 缺 run_id，無法定位 manifest；呼叫 {agent} 被擋")
    manifest_path = f"run/{run_id}.json"
    if not os.path.exists(manifest_path):
        block(f"{manifest_path} 不存在（前置 0 未完成），不可呼叫 {agent}")
    manifest = load_json(manifest_path)

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
        for st in state.get("sub_tasks", []):
            if (st.get("risk_analysis") or {}).get("blocking") is True:
                name = st.get("name") or st.get("id")
                block(f"sub_task「{name}」風險分析 blocking=true（🔴），須先修改 Spec 重新分析")

    sys.exit(0)


def run_hook():
    global _hint_enabled
    _hint_enabled = True  # 只在 hook 模式附提示；--validate 為人工自檢，不需要
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # 非預期輸入，不擋

    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
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
            "若為失敗收尾（status: failed），依規則由使用者裁決，不可由 Claude commit"
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
