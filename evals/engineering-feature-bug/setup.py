#!/usr/bin/env python3
"""Create buggy order calculation and an existing user edit."""

from pathlib import Path
import subprocess
import sys

PROBE = """import json, os, subprocess, sys, tempfile
from pathlib import Path

dispatch = Path(__file__).resolve().parent / ".agent-flow/scripts/dispatch.py"
observed = {}
with tempfile.TemporaryDirectory() as tmp:
    project = Path(tmp)
    for cmd in (["git", "init", "-q"], ["git", "config", "user.name", "Eval"], ["git", "config", "user.email", "eval@example.test"]):
        subprocess.run(cmd, cwd=project, check=True, capture_output=True)
    (project / "user-notes.txt").write_text("original\\n")
    subprocess.run(["git", "add", "user-notes.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=project, check=True)
    (project / "user-notes.txt").write_text("user edit\\n")
    bindir = project / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text("#!/usr/bin/env python3\\nimport json, os\\nif os.environ.get('TOUCH_DIRTY') == '1':\\n    open('user-notes.txt', 'a').write('worker edit\\\\n')\\nprint(json.dumps({'type':'result','is_error':False,'result':'* _2026-11-04 10:00 (test)_\\\\nSelf-check: ok'}))\\n")
    fake.chmod(0o755)
    prompt = project / "prompt.txt"
    prompt.write_text("test\\n")
    for label, touch in (("untouched", "0"), ("changed", "1")):
        env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"], "TOUCH_DIRTY": touch}
        result = subprocess.run([sys.executable, str(dispatch), "code-writer", "--prompt-file", str(prompt), "--files", "allowed.txt"], cwd=project, env=env, capture_output=True, text=True, timeout=20)
        paths = ["user-notes.txt"] if "越界變更：user-notes.txt" in result.stderr else []
        observed[label] = {"exit": result.returncode, "paths": paths}
print(json.dumps(observed))
"""


def main(fixture):
    root = Path(fixture)
    (root / "pipeline.py").write_text(
        "def total(price, discount):\n    return price * 110 // 100 - discount\n",
        encoding="utf-8",
    )
    (root / "user-notes.txt").write_text("original\n", encoding="utf-8")
    (root / "dispatch_probe.py").write_text(PROBE, encoding="utf-8")
    subprocess.run(
        ["git", "add", "pipeline.py", "user-notes.txt", "dispatch_probe.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture pipeline"], cwd=root, check=True
    )
    (root / "user-notes.txt").write_text("user edit\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: setup.py <fixture_dir>")
    main(sys.argv[1])
