#!/usr/bin/env python3
"""eval_state.json 操作 helper：eval-flow 循環的欄位更新一律走這裡，不手動 Edit。

用法：
  python3 .claude/hooks/eval_state.py init --run-id ID
  python3 .claude/hooks/eval_state.py add-subtask --id N --name "名稱"
  python3 .claude/hooks/eval_state.py set-step <id> <writing|reviewing|fixing|verifying|testing|done>
  python3 .claude/hooks/eval_state.py set-files <id> <file...>
  python3 .claude/hooks/eval_state.py set-test <id> (--passed --evidence "指令＋結果摘要" | --failed)
  python3 .claude/hooks/eval_state.py set-status <id> <passed|failed|in_progress> [--warning]
  python3 .claude/hooks/eval_state.py set-review <id> <reds> [--dimensions '<json>']
                                                   # step 3 首輪 code-reviewer 🔴 數（修正前原始數）
                                                   # --dimensions: 維度→問題數，如 '{"Clarity":1,"Completeness":2}'
  python3 .claude/hooks/eval_state.py set-verify <id>          # step 4 reviewer 完成度節通過時呼叫
  python3 .claude/hooks/eval_state.py add-verification <id> --command "<指令>" --exit-code <int>
                                                   # step 5 每跑一條驗證指令 append 一筆（純記錄，無 gate）
  python3 .claude/hooks/eval_state.py list-files      # 所有 sub_task files 聯集（餵 related --files）
  python3 .claude/hooks/eval_state.py archive         # 驗證後歸檔 run/<run_id>.eval.json 並刪除 eval_state.json

archive 前驗證全部 sub_task passed 且測試欄位齊備（同 eval_gates 的 commit gate 標準），
驗證不過即 exit 2 不落盤。exit 0 = 成功；exit 1 = 使用錯誤；exit 2 = 驗證不過。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402

STATE_PATH = "eval_state.json"
STEPS = ["writing", "reviewing", "fixing", "verifying", "testing", "done"]
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
    save({"run_id": args.run_id, "sub_tasks": []})
    print(f"[eval-state] init: run_id={args.run_id}")


def cmd_add_subtask(args):
    state = load()
    if any(st.get("id") == args.id for st in state["sub_tasks"]):
        fail(f"id={args.id} 已存在")
    state["sub_tasks"].append({
        "id": args.id, "name": args.name, "status": "in_progress", "step": None,
        "files": [], "warning": False,
        "local_test_passed": False, "local_test_evidence": None,
        "verification_commands": [],
        "review_reds": None, "verify_passed": False,
        "risk_analysis": None, "review_dimensions": None,
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


VALID_DIMENSIONS = {"Clarity", "Completeness", "Testability", "Non-functional", "Technical_constraints"}


def cmd_set_review(args):
    if args.reds < 0:
        fail(f"reds 必須為非負整數（收到 {args.reds}）")
    dims = None
    if args.dimensions is not None:
        try:
            dims = json.loads(args.dimensions)
        except json.JSONDecodeError as e:
            fail(f"--dimensions 非合法 JSON（{e}）", code=2)
        if not isinstance(dims, dict):
            fail("--dimensions 必須為 JSON 物件（維度→問題數）", code=2)
        for k, v in dims.items():
            if k not in VALID_DIMENSIONS:
                fail(
                    f"--dimensions 含非法維度鍵「{k}」；"
                    f"合法值：{', '.join(sorted(VALID_DIMENSIONS))}",
                    code=2,
                )
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                fail(f"--dimensions 維度「{k}」的值必須為非負整數（收到 {v!r}）", code=2)
    state = load()
    st = find_subtask(state, args.id)
    st["review_reds"] = args.reds
    if dims is not None:
        st["review_dimensions"] = dims
    save(state)
    msg = f"[eval-state] sub_task {args.id} review_reds -> {args.reds}"
    if dims is not None:
        msg += f"，review_dimensions -> {dims}"
    print(msg)


def cmd_set_verify(args):
    state = load()
    find_subtask(state, args.id)["verify_passed"] = True
    save(state)
    print(f"[eval-state] sub_task {args.id} verify_passed -> True")


def cmd_add_verification(args):
    """step 5 的驗證指令留痕（append 累積）。純記錄欄位、不被任何 gate 消費——
    與 local_test_evidence 並存：後者記推理留痕（散文），本欄記「跑了哪些指令、結果如何」。"""
    if not args.command.strip():
        fail("--command 不可為空字串")
    state = load()
    st = find_subtask(state, args.id)
    # 舊 eval_state.json 的 sub_task 無此鍵（本欄位為後加的可選欄位）→ 補上再 append
    st.setdefault("verification_commands", []).append(
        {"command": args.command, "exit_code": args.exit_code}
    )
    save(state)
    print(f"[eval-state] sub_task {args.id} verification_commands "
          f"+1（共 {len(st['verification_commands'])} 筆）exit={args.exit_code}")


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

    p = sub.add_parser("set-review")
    p.add_argument("id", type=int)
    p.add_argument("reds", type=int)
    p.add_argument("--dimensions", default=None,
                   help="維度→問題數 JSON，如 '{\"Clarity\":1}'")
    p.set_defaults(func=cmd_set_review)

    p = sub.add_parser("set-verify")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_set_verify)

    p = sub.add_parser("add-verification")
    p.add_argument("id", type=int)
    p.add_argument("--command", required=True)
    p.add_argument("--exit-code", type=int, required=True, dest="exit_code")
    p.set_defaults(func=cmd_add_verification)

    p = sub.add_parser("list-files")
    p.set_defaults(func=cmd_list_files)

    p = sub.add_parser("archive")
    p.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
