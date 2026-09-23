#!/usr/bin/env python3
"""Git commit-msg hook: validate the message Git will actually commit."""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates


TRAILER = re.compile(r"^Run-Id:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


def check(message_path):
    with open(message_path, encoding="utf-8") as stream:
        message = stream.read()
    pending = []
    for path in sorted(glob.glob("run/*.json")):
        if not eval_gates.MANIFEST_RE.fullmatch(path):
            continue
        manifest = eval_gates.load_json_quiet(path)
        if isinstance(manifest, dict) and manifest.get("status") in eval_gates.PENDING_STATUSES:
            pending.append(path)
    if not pending:
        return
    trailers = TRAILER.findall(message)
    if len(trailers) != 1:
        eval_gates.block("未完成的 run 存在；commit message 須有唯一的 Run-Id trailer")
    path = f"run/{trailers[0]}.json"
    if path not in pending:
        eval_gates.block(f"Run-Id {trailers[0]} 未指向待提交的 run")
    if len(pending) != 1:
        eval_gates.block(f"工作樹有 {len(pending)} 個未完成的 run，先處理單一 run 原則")
    if os.path.exists("eval_state.json"):
        eval_gates.block("eval_state.json 尚未歸檔")
    eval_gates.check_manifest(path, set())
    staged = eval_gates._git_diff_cached_paths()
    if staged is None:
        eval_gates.block("無法讀取 Git staging area")
    eval_gates.check_staged_test_lint(set(staged))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: commit_message_gate.py MESSAGE_FILE", file=sys.stderr)
        sys.exit(2)
    try:
        check(sys.argv[1])
    except OSError as error:
        print(f"[commit-message-gate] {error}", file=sys.stderr)
        sys.exit(2)
