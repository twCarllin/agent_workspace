#!/usr/bin/env python3
"""Git commit-msg hook: validate the message Git will actually commit."""

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import eval_gates

TRAILER = re.compile(r"^Run-Id:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


def check(message_path):
    with open(message_path, encoding="utf-8") as stream:
        message = stream.read()
    import work_root

    os.chdir(work_root.state_root(os.getcwd()))
    staged = eval_gates._git_diff_cached_paths()
    if staged is None:
        eval_gates.block("無法讀取 Git staging area")
    staged = set(staged)
    eval_gates.check_manifest_deletion()
    if eval_gates.check_abort_failed_narrow_exception(staged):
        return
    if os.path.exists("eval_state.json"):
        eval_gates.block("eval_state.json 尚未歸檔")
    pending = []
    for path in sorted(glob.glob("run/*.json")):
        if not eval_gates.MANIFEST_RE.fullmatch(path):
            continue
        manifest = eval_gates.load_json_quiet(path)
        if (
            isinstance(manifest, dict)
            and manifest.get("status") in eval_gates.PENDING_STATUSES
        ):
            pending.append(path)
    if not pending:
        manifests = [
            path for path in sorted(staged) if eval_gates.MANIFEST_RE.fullmatch(path)
        ]
        for path in manifests:
            eval_gates.check_manifest(path, staged)
        if manifests:
            eval_gates.check_staged_test_lint(staged)
        return
    trailers = TRAILER.findall(message)
    if len(trailers) != 1:
        eval_gates.block("未完成的 run 存在；commit message 須有唯一的 Run-Id trailer")
    path = f"run/{trailers[0]}.json"
    if path not in pending:
        eval_gates.block(f"Run-Id {trailers[0]} 未指向待提交的 run")
    if len(pending) != 1:
        eval_gates.block(f"工作樹有 {len(pending)} 個未完成的 run，先處理單一 run 原則")
    eval_gates.check_manifest(path, staged)
    for staged_path in sorted(staged):
        if staged_path != path and eval_gates.MANIFEST_RE.fullmatch(staged_path):
            eval_gates.check_manifest(staged_path, staged)
    eval_gates.check_staged_test_lint(staged)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: commit_message_gate.py MESSAGE_FILE", file=sys.stderr)
        sys.exit(2)
    try:
        check(sys.argv[1])
    except (OSError, ValueError) as error:
        print(f"[commit-message-gate] {error}", file=sys.stderr)
        sys.exit(2)
