#!/usr/bin/env python3
"""Exercise the order CLI and the installed dispatch via real child processes."""

import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import Checker, load_result  # noqa: E402


def main(fixture, result_path):
    root = Path(fixture).resolve()
    checker = Checker()
    for price, discount, expected in ((1000, 200, 880), (1000, 0, 1100)):
        result = subprocess.run(
            [sys.executable, str(root / "pipeline.py"), str(price), str(discount)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        output = None
        if result.returncode == 0:
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        checker.check(f"資料流 {price}/{discount}", output == {"total_cents": expected})
    notes = root / "user-notes.txt"
    checker.check(
        "保留使用者既有 dirty", notes.is_file() and notes.read_text() == "user edit\n"
    )
    evidence = load_result(root / "dispatch-evidence.json")
    expected = {
        "changed": {"exit": 4, "paths": ["user-notes.txt"]},
        "untouched": {"exit": 0, "paths": []},
    }
    checker.check("派工證據完整", evidence == expected)
    probe = root / "dispatch_probe.py"
    source = Path(__file__).resolve().parents[2] / ".agent-flow/scripts"
    installed = root / ".agent-flow/scripts"
    for name in (
        "dispatch.py",
        "harness_adapter.py",
        "flow_rules.py",
        "run_evidence.py",
        "report_envelope_check.py",
        "retro_select.py",
    ):
        reference = source / name
        target = installed / name
        checker.check(
            f"派工來源一致 {name}",
            reference.is_file()
            and target.is_file()
            and reference.read_bytes() == target.read_bytes(),
        )
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "dispatch_probe.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    checker.check("probe 未修改", diff.returncode == 0 and not diff.stdout)
    result = load_result(result_path)
    source = result.get("native_stdout_source") if isinstance(result, dict) else None
    raw = result.get("native_stdout") if isinstance(result, dict) else None
    verified = False
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
                or item.get("status") != "completed"
            ):
                continue
            try:
                args = shlex.split(item.get("command", ""))
                if (
                    len(args) == 3
                    and Path(args[0]).name in ("sh", "bash", "zsh")
                    and args[1] in ("-c", "-lc")
                ):
                    args = shlex.split(args[2])
                output = json.loads(item.get("aggregated_output", ""))
            except (ValueError, TypeError):
                continue
            if (
                len(args) == 2
                and Path(args[0]).name in ("python", "python3")
                and Path(args[1]).is_absolute()
                and Path(args[1]).resolve() == probe
                and item.get("exit_code") == 0
                and output == expected
                and output == evidence
            ):
                verified = True
    checker.check("派工 probe 直接完成事件", verified, "缺少可驗證的直接事件，來源未知")
    return checker.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check.py <fixture_dir> <result_json>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
