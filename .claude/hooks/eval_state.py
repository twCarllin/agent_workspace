#!/usr/bin/env python3
"""eval_state.json 操作 helper：eval-flow 循環的欄位更新一律走這裡，不手動 Edit。

用法：
  python3 .claude/hooks/eval_state.py init --run-id ID [--threshold 6]
  python3 .claude/hooks/eval_state.py add-subtask --id N --name "名稱"
  python3 .claude/hooks/eval_state.py set-step <id> <writing|reviewing|fixing|verifying|testing|scoring|done>
  python3 .claude/hooks/eval_state.py set-files <id> <file...>
  python3 .claude/hooks/eval_state.py set-test <id> (--passed --evidence "指令＋結果摘要" | --failed)
  python3 .claude/hooks/eval_state.py set-status <id> <passed|failed|in_progress> [--warning]
  python3 .claude/hooks/eval_state.py append-round <id> --json '<round JSON>'   # '-' 讀 stdin
  python3 .claude/hooks/eval_state.py list-files      # 所有 sub_task files 聯集（餵 related --files）
  python3 .claude/hooks/eval_state.py archive         # 驗證後歸檔 run/<run_id>.eval.json 並刪除 eval_state.json

append-round 寫入前驗證扣分不變量（總和 = 10 − quality_score）；archive 前驗證
全部 sub_task passed 且測試欄位齊備（同 eval_gates 的 commit gate 標準），
驗證不過即 exit 2 不落盤。exit 0 = 成功；exit 1 = 使用錯誤；exit 2 = 驗證不過。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402

STATE_PATH = "eval_state.json"
STEPS = ["writing", "reviewing", "fixing", "verifying", "testing", "scoring", "done"]
STATUSES = ["passed", "failed", "in_progress"]


def fail(msg, code=1):
    print(f"[eval-state] {msg}", file=sys.stderr)
    sys.exit(code)


def load():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"{STATE_PATH} 不存在：先跑 init（前置 0）")
    except json.JSONDecodeError as e:
        fail(f"{STATE_PATH} 非合法 JSON（{e}）")


def save(state, path=STATE_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def find_subtask(state, sid):
    for st in state.get("sub_tasks", []):
        if st.get("id") == sid:
            return st
    fail(f"找不到 id={sid} 的 sub_task")


def cmd_init(args):
    if os.path.exists(STATE_PATH):
        fail(f"{STATE_PATH} 已存在：一個 worktree 同時只跑一個 run，先收尾或歸檔既有 run")
    save({"run_id": args.run_id, "threshold": args.threshold,
          "sub_tasks": [], "status": "in_progress"})
    print(f"[eval-state] init: run_id={args.run_id} threshold={args.threshold}")


def cmd_add_subtask(args):
    state = load()
    if any(st.get("id") == args.id for st in state["sub_tasks"]):
        fail(f"id={args.id} 已存在")
    state["sub_tasks"].append({
        "id": args.id, "name": args.name, "status": "in_progress", "step": None,
        "files": [], "warning": False,
        "local_test_passed": False, "local_test_evidence": None,
        "risk_analysis": None, "rounds": [],
    })
    save(state)
    print(f"[eval-state] add-subtask: {args.id}「{args.name}」")


def cmd_set_step(args):
    state = load()
    find_subtask(state, args.id)["step"] = args.step
    save(state)
    print(f"[eval-state] sub_task {args.id} step -> {args.step}")


def cmd_set_files(args):
    state = load()
    find_subtask(state, args.id)["files"] = list(dict.fromkeys(args.files))
    save(state)
    print(f"[eval-state] sub_task {args.id} files -> {len(args.files)} 個檔案")


def cmd_set_test(args):
    state = load()
    st = find_subtask(state, args.id)
    if args.passed:
        if not (args.evidence and args.evidence.strip()):
            fail("--passed 必須帶 --evidence（指令＋結果摘要）")
        st["local_test_passed"] = True
        st["local_test_evidence"] = args.evidence
    else:
        st["local_test_passed"] = False
        if args.evidence:
            st["local_test_evidence"] = args.evidence
    save(state)
    print(f"[eval-state] sub_task {args.id} local_test_passed -> {st['local_test_passed']}")


def cmd_set_status(args):
    state = load()
    st = find_subtask(state, args.id)
    st["status"] = args.status
    if args.warning:
        st["warning"] = True
    save(state)
    print(f"[eval-state] sub_task {args.id} status -> {args.status}")


def cmd_append_round(args):
    raw = sys.stdin.read() if args.json == "-" else args.json
    try:
        rnd = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"--json 非合法 JSON（{e}）")
    state = load()
    st = find_subtask(state, args.id)
    st.setdefault("rounds", []).append(rnd)
    eval_gates.check_rounds_invariant(st, STATE_PATH)  # 不變量不過 → exit 2，不落盤
    save(state)
    print(f"[eval-state] sub_task {args.id} append round {rnd.get('round')}（score {rnd.get('quality_score')}）")


def cmd_list_files(args):
    state = load()
    seen = {}
    for st in state.get("sub_tasks", []):
        for f in st.get("files", []):
            seen[f] = True
    if seen:
        print("\n".join(seen))


def cmd_archive(args):
    state = load()
    run_id = state.get("run_id")
    if not run_id:
        fail("缺 run_id，無法歸檔", code=2)
    if not state.get("sub_tasks"):
        fail("sub_tasks 為空，無可歸檔內容", code=2)
    state["status"] = "completed"
    eval_gates.validate_state(state, STATE_PATH, require_passed=True)  # 不過 → exit 2
    archive_path = f"run/{run_id}.eval.json"
    os.makedirs("run", exist_ok=True)
    save(state, archive_path)
    os.remove(STATE_PATH)
    print(f"[eval-state] 已歸檔 {archive_path} 並清除 {STATE_PATH}（記得把 manifest 標 completed）")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--run-id", required=True)
    p.add_argument("--threshold", type=int, default=6)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-subtask")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add_subtask)

    p = sub.add_parser("set-step")
    p.add_argument("id", type=int)
    p.add_argument("step", choices=STEPS)
    p.set_defaults(func=cmd_set_step)

    p = sub.add_parser("set-files")
    p.add_argument("id", type=int)
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_set_files)

    p = sub.add_parser("set-test")
    p.add_argument("id", type=int)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--passed", action="store_true")
    g.add_argument("--failed", action="store_true")
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_set_test)

    p = sub.add_parser("set-status")
    p.add_argument("id", type=int)
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--warning", action="store_true")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("append-round")
    p.add_argument("id", type=int)
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_append_round)

    p = sub.add_parser("list-files")
    p.set_defaults(func=cmd_list_files)

    p = sub.add_parser("archive")
    p.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
