#!/usr/bin/env python3
"""step 5 簿記 wrapper：跑驗證指令＋記 verification_commands＋寫事件，一次完成。

用法：python3 .agent-flow/scripts/run_verify.py --run-id <id> [--sub-task <int>] --cmd "<指令>"

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
import hashlib
import shlex
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import eval_state  # noqa: E402
import verification_snapshot  # noqa: E402


def environment_digest():
    """Keep environment values private; compare only their digest."""
    return hashlib.sha256(json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest()


def live_command(command):
    tokens = shlex.split(command)
    return (any(os.path.basename(token) in ("codex", "claude") for token in tokens)
            or (any("harness_smoke" in token for token in tokens) and "--live" in tokens)
            or (any("skill_eval" in token for token in tokens) and "--dry-run" not in tokens))


def combined_evidence(target, result):
    """Keep arbitration and exemption notes alongside command results."""
    previous = target.get("local_test_evidence")
    if not isinstance(previous, str) or not previous.strip():
        return result
    if result in previous.splitlines():
        return previous
    return previous + "\n" + result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sub-task", type=int, default=None, dest="sub_task")
    parser.add_argument("--cmd", required=True)
    parser.add_argument("--reuse", action="store_true", help="Reuse matching local success in this run")
    args = parser.parse_args()

    manifest_path = os.path.join("run", f"{args.run_id}.json")
    use_state = os.path.exists(eval_state.STATE_PATH) and args.sub_task is not None

    # 前置檢查（跑指令之前）：記錄目標必須存在
    if use_state:
        state = eval_state.load()
        if state.get("run_id") != args.run_id:
            print("[run-verify] eval_state run_id 不符", file=sys.stderr)
            sys.exit(2)
        eval_state.find_subtask(state, args.sub_task)  # 找不到 → fail() 非零退出
    elif not os.path.exists(manifest_path):
        print(f"[run-verify] 找不到 {manifest_path}——先建 manifest（Tier 2 記 sub_task 需同時給 --sub-task 且 eval_state.json 存在）",
              file=sys.stderr)
        sys.exit(2)

    with open(manifest_path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    schema2 = manifest.get("evidence_schema") == 2
    if args.reuse and (not schema2 or live_command(args.cmd)):
        print("[run-verify] --reuse 只適用 schema 2 本地驗證", file=sys.stderr)
        sys.exit(2)
    started = time.monotonic()
    record = {"command": args.cmd, "reused": False, "executed": False}
    before = None
    if schema2:
        record.update(snapshot_kind="inputs-v2", context={"environment": environment_digest()})
        try:
            before = verification_snapshot.input_snapshot_v2()
        except (OSError, subprocess.CalledProcessError) as error:
            record["error"] = str(error)
    target = eval_state.find_subtask(eval_state.load(), args.sub_task) if use_state else manifest
    history = target.get("verification_commands", [])
    previous_index = next((index for index in range(len(history) - 1, -1, -1)
                           if history[index].get("command") == args.cmd), None)
    previous = history[previous_index] if previous_index is not None else {}
    reusable = (args.reuse and before is not None and previous.get("exit_code") == 0
                and previous.get("snapshot_kind") == "inputs-v2"
                and previous.get("snapshot") == before
                and previous.get("context") == record.get("context"))
    if schema2 and before is None:
        exit_code = 2
    elif reusable:
        exit_code = 0
        record["reused"] = True
        record["reused_from"] = {"run_id": args.run_id, "sub_task": args.sub_task,
                                 "record_index": previous_index}
    else:
        record["executed"] = True
        exit_code = subprocess.run(args.cmd, shell=True).returncode
    if schema2 and before is not None:
        try:
            after = verification_snapshot.input_snapshot_v2()
            if after != before:
                record["error"] = "Verification inputs changed during command"
                exit_code = exit_code or 2
            elif exit_code == 0:
                record["snapshot"] = after
        except (OSError, subprocess.CalledProcessError) as error:
            record["error"] = str(error)
            exit_code = exit_code or 2
    record.update(exit_code=exit_code, elapsed_seconds=time.monotonic() - started)
    evidence = f"{args.cmd} -> exit={exit_code}; executed={record['executed']}; reused={record['reused']}"
    try:
        if use_state:
            state = eval_state.load()
            st = eval_state.find_subtask(state, args.sub_task)
            st.setdefault("verification_commands", []).append(record)
            st.update(local_test_passed=exit_code == 0,
                      local_test_evidence=combined_evidence(st, evidence))
            eval_state.save(state)
            # 鍵名用 verify_command：append_event 過濾 `command` 鍵（子命令 dest 同名），見 eval_state.cmd_add_verification
            eval_state.append_event(
                state.get("run_id"), "add-verification",
                argparse.Namespace(id=args.sub_task, verify_command=args.cmd, exit_code=exit_code))
        else:
            with open(manifest_path, encoding="utf-8") as f:
                m = json.load(f)
            m.setdefault("verification_commands", []).append(record)
            m.update(local_test_passed=exit_code == 0,
                     local_test_evidence=combined_evidence(m, evidence))
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
            eval_state.append_event(
                args.run_id, "verify_cmd",
                argparse.Namespace(verify_command=args.cmd, exit_code=exit_code))
        if exit_code == 0:
            eval_state.append_event(args.run_id, "verified", argparse.Namespace(
                sub_task=args.sub_task, verify_command=args.cmd, exit_code=exit_code,
                executed=record["executed"], reused=record["reused"], evidence=evidence))
        print(f"[run-verify] 已記錄 verification（exit={exit_code}）"
              f" -> {'eval_state.json sub_task ' + str(args.sub_task) if use_state else manifest_path}")
    except Exception as e:
        print(f"[run-verify] verification 記錄寫入失敗（{e}）", file=sys.stderr)
        if schema2:
            exit_code = exit_code or 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
