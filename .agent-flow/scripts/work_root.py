"""Resolve per-worktree state without a registry or a mutable active target."""

import json
import os
from pathlib import Path
import subprocess
import sys

import flow_rules


def git_root(start):
    start = Path(start).resolve()
    while not start.is_dir() and start != start.parent:
        start = start.parent
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=5,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def state_root(start):
    """Find known markers inside one Git worktree, including legacy subdir runs.

    Git pathspecs bound discovery to the existing marker names. Git excludes nested
    repositories and does not follow directory symlinks. No general tree walk or
    persisted index is needed. Ignored state must also be found (info/exclude).
    """
    start = Path(start).resolve()
    while not start.is_dir() and start != start.parent:
        start = start.parent
    top = git_root(start)
    if top is None:
        return start
    candidates = {top}
    for ignored in (False, True):
        argv = [
            "git",
            "-C",
            str(top),
            "ls-files",
            "-z",
            "--others",
            "--exclude-standard",
        ]
        argv += ["--ignored"] if ignored else ["--cached"]
        result = subprocess.run(
            argv
            + [
                "--",
                ":(glob)**/eval_state.json",
                ":(glob)**/run/*.json",
                ":(glob)**/.agent-flow/ROUTER.md",
            ],
            capture_output=True,
            check=True,
            timeout=10,
        )
        for raw in result.stdout.split(b"\0"):
            if raw:
                path = top / os.fsdecode(raw)
                root = (
                    path.parent
                    if path.name == "eval_state.json"
                    else path.parent.parent
                )
                if root.is_relative_to(top):
                    candidates.add(root)
    # An ancestor can own a symlinked installation, e.g. a linked worktree.
    directory = start if start.is_dir() else start.parent
    while directory.is_relative_to(top):
        candidates.add(directory)
        if directory == top:
            break
        directory = directory.parent
    installed, active, historic = set(), set(), set()
    for root in sorted(candidates):
        if (root / ".agent-flow/ROUTER.md").is_file() and (
            root / ".agent-flow/scripts/eval_state.py"
        ).is_file():
            installed.add(root)
        state_path = root / "eval_state.json"
        if state_path.is_file():
            # Even damaged hot state must remain visible to the existing gate.
            active.add(root)
        for path in (root / "run").glob("*.json"):
            relative = "run/" + path.name
            match = flow_rules.MANIFEST_RE.fullmatch(relative)
            if not match:
                continue
            try:
                manifest = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            # This is an untrusted discovery boundary, not full run validation.
            # Do not let arbitrary run/ or unrelated JSON select a working root.
            if not (
                isinstance(manifest, dict)
                and manifest.get("run_id") == match["run_id"]
                and manifest.get("tier") in (1, "1", 2, "2", "B", "hotfix")
                and manifest.get("status")
                in (
                    *flow_rules.PENDING_STATUSES,
                    "completed",
                    "partial",
                    "aborted",
                    "failed",
                )
                and (manifest.get("spec_path") or manifest.get("spec_inline"))
            ):
                continue
            historic.add(root)
            if manifest["status"] in flow_rules.PENDING_STATUSES:
                active.add(root)
    # An active run owns the worktree even when an older installation is elsewhere.
    roots = active or installed or historic
    if len(roots) > 1:
        raise ValueError(
            "工作根衝突；請先處理各位置的狀態：\n" + "\n".join(map(str, sorted(roots)))
        )
    return next(iter(roots), top)


def require_cwd(*, new_run=False, toolchain=False):
    """Reject the wrong directory without changing relative argument semantics."""
    cwd = Path.cwd().resolve()
    root = state_root(cwd)
    if cwd != root:
        raise ValueError(f"請在工作根執行：{root}（目前：{cwd}）；未切換目錄")
    if new_run and git_root(cwd) is None:
        raise ValueError("完整 flow 需要 Git 工作樹；非 Git 目錄不可建立新 run")
    if toolchain:
        local = target_toolchain(root)
        current = Path(__file__).resolve().parent
        if local is not None and local.resolve() != current:
            raise ValueError(f"請使用目標已接入的工具鏈：{local}")
    return root


def target_toolchain(root, *, installed_only=False):
    """An existing installation or shared hook owns the toolchain for this target."""
    top = git_root(root)
    directory = Path(root).resolve()
    while top is not None and directory.is_relative_to(top):
        scripts = directory / ".agent-flow/scripts"
        if (scripts / "eval_state.py").is_file() and (
            directory / ".agent-flow/ROUTER.md"
        ).is_file():
            return scripts.resolve()
        if directory == top:
            break
        directory = directory.parent
    if top is None or installed_only:
        return None
    hook = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks/commit-msg"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    path = Path(hook.stdout.strip())
    if not path.is_absolute():
        path = Path(root) / path
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("# agent-workspace shared scripts: "):
                return Path(
                    line.removeprefix("# agent-workspace shared scripts: ")
                ).resolve()
    return None


def check_cli(**kwargs):
    """CLI error boundary shared by the compatible executable entry points."""
    try:
        return require_cwd(**kwargs)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"[work-root] {error}", file=sys.stderr)
        sys.exit(2)


def require_commit_hook(root):
    """Check the target's installed gate without executing user hooks as a probe."""
    # --git-path honors core.hooksPath. A manually integrated custom hook may be
    # used, but its existence alone does not mean that our gate was connected.
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks/commit-msg"],
        capture_output=True,
        text=True,
        check=True,
    )
    hook = Path(root) / result.stdout.strip()
    text = hook.read_text() if hook.is_file() else ""
    scripts = target_toolchain(root)
    managed = (
        "agent-workspace managed commit message gate" in text
        and "commit_message_gate.py" in text
    )
    integrated = scripts is not None and str(scripts / "commit_message_gate.py") in text
    if not os.access(hook, os.X_OK) or not (managed or integrated):
        raise ValueError(
            "目標 commit gate 未啟用：請先完整安裝或執行 install_harness.py --attach --target <目標>；自訂 hook 不會被覆蓋"
        )
