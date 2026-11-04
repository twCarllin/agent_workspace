#!/usr/bin/env python3
"""Check recovery against actual session events and fixture state."""

import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import Checker, load_result  # noqa: E402
from setup import PROBE  # noqa: E402


def main(fixture, result_path):
    root = Path(fixture).resolve()
    checker = Checker()
    report = load_result(root / "recovery.json")
    reason = load_result(root / "reason.json")
    system = load_result(root / "system.json")
    if not all(isinstance(value, dict) for value in (report, reason, system)):
        checker.check("恢復與來源資料可讀", False)
        return checker.finish()
    diff = subprocess.run(
        [
            "git",
            "diff",
            "HEAD",
            "--",
            "reason.json",
            "system.json",
            "session_cli.py",
            "real_session_probe.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    checker.check(
        "來源與 session 執行程式未修改", diff.returncode == 0 and not diff.stdout
    )
    checker.check(
        "舊理由符合目前資料",
        report.get("reason_valid") is (reason.get("field") == system.get("field"))
        and report.get("correction") == system.get("field"),
    )
    valid = {"status": "resumed", "session": "valid-session"}
    expired = {"status": "invalid", "session": "expired-session"}
    checker.check(
        "有效與無效 session 結論",
        report.get("valid") == valid and report.get("expired") == expired,
    )
    event_path = root / "session-events.jsonl"
    events = []
    if event_path.is_file():
        for line in event_path.read_text().split("\n"):
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    checker.check("事件格式有效", False)
                    return checker.finish()
    checker.check("續用與無效事件均有紀錄", valid in events and expired in events)
    result = load_result(result_path)
    raw = result.get("native_stdout") if isinstance(result, dict) else None
    source = result.get("native_stdout_source") if isinstance(result, dict) else None
    completed = []
    real_results = []
    python_paths = {Path(sys.executable).resolve()}
    if shutil.which("python3"):
        python_paths.add(Path(shutil.which("python3")).resolve())
    if source == "codex CLI stdout" and isinstance(raw, str):
        for line in raw.split("\n"):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if (
                not isinstance(item, dict)
                or item.get("type") != "command_execution"
                or item.get("status") not in ("completed", "failed")
            ):
                continue
            command = item.get("command")
            if not isinstance(command, str):
                continue
            try:
                args = shlex.split(command)
                if (
                    len(args) == 3
                    and Path(args[0]).name in ("sh", "bash", "zsh")
                    and args[1] in ("-c", "-lc")
                ):
                    args = shlex.split(args[2])
            except ValueError:
                continue
            if (
                len(args) == 3
                and shutil.which(args[0])
                and Path(shutil.which(args[0])).resolve() in python_paths
                and args[1] == "-I"
                and Path(args[2]).is_absolute()
                and Path(args[2]).resolve() == root / "real_session_probe.py"
            ):
                try:
                    real_output = json.loads(item.get("aggregated_output", ""))
                except (json.JSONDecodeError, TypeError):
                    continue
                if (
                    item.get("status") == "completed"
                    and item.get("exit_code") == 0
                    and isinstance(real_output, dict)
                ):
                    real_results.append(real_output)
                continue
            if (
                len(args) != 4
                or not shutil.which(args[0])
                or Path(shutil.which(args[0])).resolve() not in python_paths
                or not Path(args[1]).is_absolute()
                or Path(args[1]).resolve() != (root / "session_cli.py").resolve()
                or args[2] != "resume"
                or args[3] not in ("valid-session", "expired-session")
            ):
                continue
            try:
                output = json.loads(item.get("aggregated_output", ""))
            except (json.JSONDecodeError, TypeError):
                continue
            expected_status = "completed" if item.get("exit_code") == 0 else "failed"
            if item.get("status") != expected_status:
                continue
            completed.append((args[3], item.get("exit_code"), output))
    checker.check(
        "session 呼叫來源可驗證",
        ("valid-session", 0, valid) in completed
        and ("expired-session", 1, expired) in completed,
        "缺少可信的直接命令完成事件，來源未知",
    )
    probe = root / "real_session_probe.py"
    cli = shutil.which("codex")
    trusted_probe = (
        bool(cli)
        and probe.is_file()
        and probe.read_text() == PROBE.replace("__CLI_PATH__", repr(cli))
    )
    real_pass = False
    for observed in real_results:
        token = observed.get("token")
        thread = observed.get("thread")
        if (
            observed.get("status") == "pass"
            and observed.get("first_exit") == 0
            and observed.get("second_exit") == 0
            and isinstance(thread, str)
            and thread
            and observed.get("resumed_threads") == [thread]
            and isinstance(token, str)
            and re.fullmatch(r"marker-[0-9a-f]{24}", token)
            and observed.get("messages") == [token]
        ):
            real_pass = True
    checker.check(
        "真實 session 續用證據",
        bool(trusted_probe and real_pass),
        "缺少可信 probe 及直接完成事件，真實續用未知",
    )
    refs = report.get("evidence")
    required = {"reason.json", "system.json", "session-events.jsonl"}
    checker.check(
        "必要證據可讀",
        isinstance(refs, list)
        and all(isinstance(ref, str) and (root / ref).is_file() for ref in refs)
        and required.issubset(refs),
    )
    with tempfile.TemporaryDirectory() as tmp:
        for session, expected, expected_exit in (
            ("valid-session", valid, 0),
            ("expired-session", expired, 1),
        ):
            result = subprocess.run(
                [sys.executable, str(root / "session_cli.py"), "resume", session],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            observed = load_result(Path(tmp) / "session-events.jsonl")
            checker.check(
                f"session 執行 {session}",
                result.returncode == expected_exit and observed == expected,
                result.stderr,
            )
            (Path(tmp) / "session-events.jsonl").unlink()
    return checker.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check.py <fixture_dir> <result_json>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
