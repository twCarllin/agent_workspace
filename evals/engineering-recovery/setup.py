#!/usr/bin/env python3
"""Create a stale rationale and an executable session recovery boundary."""

import json
import shutil
from pathlib import Path
import subprocess
import sys

PROBE = """import json, secrets, subprocess

cli = __CLI_PATH__
result = {"status": "unknown", "stage": "setup", "reason": "cli_unavailable"}
if cli:
    token = "marker-" + secrets.token_hex(12)
    stage = "first_cli"
    try:
        first = subprocess.run([cli, "exec", "--sandbox", "workspace-write", "--json", "--skip-git-repo-check", "-"], input="Remember this exact code: " + token + ". Reply READY.", capture_output=True, text=True, timeout=40)
        result = {"status": "unknown", "stage": stage, "reason": "cli_exit", "exit": first.returncode}
        if first.returncode != 0:
            print(json.dumps(result))
            raise SystemExit(0)
        stage = "first_parse"
        events = [json.loads(line) for line in first.stdout.split("\\n") if line]
        threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
        if first.returncode == 0 and len(threads) == 1 and isinstance(threads[0], str):
            thread = threads[0]
            stage = "resume_cli"
            second = subprocess.run([cli, "exec", "--sandbox", "workspace-write", "resume", thread, "--json", "--skip-git-repo-check", "-"], input="Return only the exact code I asked you to remember.", capture_output=True, text=True, timeout=40)
            result = {"status": "unknown", "stage": stage, "reason": "cli_exit", "exit": second.returncode}
            if second.returncode != 0:
                print(json.dumps(result))
                raise SystemExit(0)
            stage = "resume_parse"
            resumed = [json.loads(line) for line in second.stdout.split("\\n") if line]
            ids = [event.get("thread_id") for event in resumed if event.get("type") == "thread.started"]
            messages = [event.get("item", {}).get("text") for event in resumed if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
            result = {"status": "pass" if second.returncode == 0 and ids == [thread] and messages == [token] else "unknown", "first_exit": first.returncode, "second_exit": second.returncode, "thread": thread, "resumed_threads": ids, "token": token, "messages": messages}
            if result["status"] == "unknown":
                result.update(stage="resume_validate", reason="result_mismatch")
        elif first.returncode == 0:
            result = {"status": "unknown", "stage": "first_validate", "reason": "missing_thread"}
    except subprocess.TimeoutExpired:
        result = {"status": "unknown", "stage": stage, "reason": "timeout"}
    except OSError:
        result = {"status": "unknown", "stage": stage, "reason": "launch_error"}
    except (ValueError, AttributeError):
        result = {"status": "unknown", "stage": stage, "reason": "invalid_output"}
print(json.dumps(result))
"""


def main(fixture):
    root = Path(fixture)
    (root / "reason.json").write_text(
        json.dumps({"assumption": "payload uses amount", "field": "amount"})
    )
    (root / "system.json").write_text(json.dumps({"field": "amount_cents"}))
    (root / "session_cli.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "operation, session = sys.argv[1:]\n"
        "if operation != 'resume':\n    raise SystemExit(2)\n"
        "status = 'resumed' if session == 'valid-session' else 'invalid'\n"
        "event = {'status': status, 'session': session}\n"
        "with Path('session-events.jsonl').open('a') as f:\n"
        "    f.write(json.dumps(event) + '\\n')\n"
        "print(json.dumps(event))\n"
        "raise SystemExit(0 if status == 'resumed' else 1)\n"
    )
    (root / "real_session_probe.py").write_text(
        PROBE.replace("__CLI_PATH__", repr(shutil.which("codex")))
    )
    subprocess.run(
        [
            "git",
            "add",
            "reason.json",
            "system.json",
            "session_cli.py",
            "real_session_probe.py",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture recovery state"], cwd=root, check=True
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: setup.py <fixture_dir>")
    main(sys.argv[1])
