#!/usr/bin/env python3
"""Eval Flow gate 檢查。

兩種模式：
  --hook            PreToolUse hook：stdin 讀 hook JSON。
                    Bash → 攔 `git commit`，跑 commit gate；
                    Task/Agent → 依 manifest.phase 狀態機攔亂序的 subagent 呼叫
  --validate <path> 獨立驗證單一 eval_state / eval 歸檔檔的不變量

exit 0 = 放行；exit 2 = block（stderr 說明原因，回饋給 Claude 修正）。
"""
import json
import os
import re
import subprocess
import sys

GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-[A-Za-z0-9-]+(?:[= ]\S+)?\s+)*commit\b")
MANIFEST_RE = re.compile(r"^run/(?P<run_id>[^/]+?)\.json$")

# phase 狀態機：manifest.phase 依前置步驟推進，subagent 呼叫需達到對應 phase
PHASES = ["init", "risk_done", "usage_confirmed", "decomposed", "completed"]
AGENT_MIN_PHASE = {
    "usage-analyzer": "risk_done",      # 前置 1（風險分析）完成才可跑前置 2
    "task-decomposer": "usage_confirmed",  # 前置 2 使用者確認後才可分拆
    "code-writer": "decomposed",        # 前置 3 完成才可進循環
    "eval-scorer": "decomposed",
}


def block(msg):
    print(f"[gate-check] BLOCK: {msg}", file=sys.stderr)
    sys.exit(2)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        block(f"{path} 無法讀取或非合法 JSON（{e}）")


def check_rounds_invariant(sub_task, source):
    name = sub_task.get("name") or sub_task.get("id")
    for rnd in sub_task.get("rounds", []):
        score = rnd.get("quality_score")
        if not isinstance(score, (int, float)):
            block(f"{source} sub_task「{name}」round {rnd.get('round')} 缺 quality_score")
        lost = sum(d.get("points_lost", 0) for d in rnd.get("deduction_reasons", []))
        if lost != 10 - score:
            block(
                f"{source} sub_task「{name}」round {rnd.get('round')} 不變量違反："
                f"扣分總和 {lost} != 10 - quality_score({score})"
            )


def validate_state(state, source, require_passed=False):
    if not state.get("run_id"):
        block(f"{source} 缺 run_id")
    for st in state.get("sub_tasks", []):
        check_rounds_invariant(st, source)
        if require_passed:
            name = st.get("name") or st.get("id")
            if st.get("status") != "passed":
                block(f"{source} sub_task「{name}」status 非 passed（{st.get('status')}）")
            if st.get("local_test_passed") is not True:
                block(f"{source} sub_task「{name}」local_test_passed 非 true：本地測試 gate 未通過")


def check_manifest(manifest_path, staged):
    m = load_json(manifest_path)
    run_id = MANIFEST_RE.match(manifest_path).group("run_id")

    if not (m.get("spec_path") or m.get("spec_inline")):
        block(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空")
    if m.get("status") != "completed":
        block(f"{manifest_path} status 非 completed（{m.get('status')}），不可 commit")

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

    if agent == "eval-scorer":
        in_progress = [st for st in state.get("sub_tasks", []) if st.get("status") == "in_progress"]
        if not in_progress:
            block("eval-scorer 被擋：eval_state.json 無 in_progress 的 sub_task 可評分")
        for st in in_progress:
            if st.get("local_test_passed") is not True:
                name = st.get("name") or st.get("id")
                block(f"eval-scorer 被擋：sub_task「{name}」local_test_passed 非 true（step 5 本地測試 gate 未通過）")

    sys.exit(0)


def run_hook():
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

    for path in sorted(staged):
        if MANIFEST_RE.match(path) and not path.endswith(".eval.json"):
            check_manifest(path, staged)
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
