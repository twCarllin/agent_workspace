#!/usr/bin/env python3
"""step 5 簿記 wrapper：跑驗證指令＋記 verification_commands＋寫事件，一次完成。

用法：python3 .claude/hooks/run_verify.py --run-id <id> [--sub-task <int>] --cmd "<指令>"

- 指令以 shell=True 執行、輸出原樣直通（R-009：同 test_baseline.py run_tests 基準）
- 記錄面：eval_state.json 存在且給 --sub-task → 寫該 sub_task 的 verification_commands
  （Tier 2 路徑；事件沿 eval_state.append_event 慣例記 add-verification）；
  否則寫 manifest run/<run_id>.json 的 verification_commands 並記 verify_cmd 事件（Tier 1 路徑）
- exit code＝被包指令的 exit code（gate 語義不變）
- 記錄目標的存在性在跑指令**前**檢查（配置錯誤早退）；指令跑完後的記錄寫入失敗
  僅 stderr warning、不改 exit code（旁路不得變主路，同 append_event 慣例）
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_state  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sub-task", type=int, default=None, dest="sub_task")
    parser.add_argument("--cmd", required=True)
    args = parser.parse_args()

    manifest_path = os.path.join("run", f"{args.run_id}.json")
    use_state = os.path.exists(eval_state.STATE_PATH) and args.sub_task is not None

    # 前置檢查（跑指令之前）：記錄目標必須存在
    if use_state:
        eval_state.find_subtask(eval_state.load(), args.sub_task)  # 找不到 → fail() 非零退出
    elif not os.path.exists(manifest_path):
        print(f"[run-verify] 找不到 {manifest_path}——先建 manifest（Tier 2 記 sub_task 需同時給 --sub-task 且 eval_state.json 存在）",
              file=sys.stderr)
        sys.exit(2)

    proc = subprocess.run(args.cmd, shell=True)
    exit_code = proc.returncode

    record = {"command": args.cmd, "exit_code": exit_code}
    try:
        if use_state:
            state = eval_state.load()
            st = eval_state.find_subtask(state, args.sub_task)
            st.setdefault("verification_commands", []).append(record)
            eval_state.save(state)
            eval_state.append_event(
                state.get("run_id"), "add-verification",
                argparse.Namespace(id=args.sub_task, command=args.cmd, exit_code=exit_code))
        else:
            with open(manifest_path, encoding="utf-8") as f:
                m = json.load(f)
            m.setdefault("verification_commands", []).append(record)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
            eval_state.append_event(
                args.run_id, "verify_cmd",
                argparse.Namespace(command=args.cmd, exit_code=exit_code))
        print(f"[run-verify] 已記錄 verification（exit={exit_code}）"
              f" -> {'eval_state.json sub_task ' + str(args.sub_task) if use_state else manifest_path}")
    except Exception as e:
        print(f"[run-verify] 警告：verification 記錄寫入失敗（{e}），不影響指令 exit code", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
