"""Record inputs that affect a live evaluation without copying its fixture."""

import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True
    ).stdout


def source_changes_digest():
    """Hash working changes; include untracked source paths and their bytes."""
    state = hashlib.sha256()
    state.update(git("diff", "HEAD", "--binary"))
    for name in sorted(
        filter(
            None, git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        )
    ):
        path = ROOT / name.decode("utf-8", errors="surrogateescape")
        state.update(name)
        if path.is_file():
            state.update(path.read_bytes())
    return state.hexdigest()


def collect(case, runner, harness, permissions, timeout):
    case = Path(case)
    case_files = {
        name: digest(case / name)
        for name in ("prompt.md", "setup.py", "check.py")
        if (case / name).is_file()
    }
    try:
        version = subprocess.run(
            [harness, "--version"], capture_output=True, text=True, timeout=10
        )
        cli_version = (
            (version.stdout or version.stderr).strip()
            if version.returncode == 0
            else None
        )
    except (OSError, subprocess.TimeoutExpired):
        cli_version = None
    return {
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "source_changes_sha256": source_changes_digest(),
        "source_clean": not bool(git("status", "--porcelain")),
        "case_files_sha256": case_files,
        "runner_sha256": digest(runner),
        "python_version": sys.version.split()[0],
        "cli_version": cli_version,
        "permissions": permissions,
        "timeout_seconds": timeout,
    }
