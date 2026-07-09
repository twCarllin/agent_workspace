#!/usr/bin/env python3
"""Eval Flow gate 檢查。

兩種模式：
  --hook            PreToolUse hook：stdin 讀 hook JSON，攔 `git commit`，跑全部 gate
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


def run_hook():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # 非預期輸入，不擋
    command = (payload.get("tool_input") or {}).get("command", "")
    if not GIT_COMMIT_RE.search(command):
        sys.exit(0)

    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    os.chdir(root)

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
