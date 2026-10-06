#!/usr/bin/env python3
"""Link the installed toolchain into a linked git worktree.

The toolchain (.agent-flow/, .agents/, .claude/, roles, retro, CLAUDE.local.md) stays out
of the project's commits, so a new worktree starts without it. ensure_links() creates
relative symlinks from the worktree back to the main checkout for every toolchain path
that the worktree lacks. run/ and task/ are per-run state and are never shared.

Called by the PreToolUse and SessionStart hooks after the worktree root is resolved, and by
`flow.py worktree-link` for worktrees created by hand. Fail-open: errors return [].
"""
import os
import subprocess
import sys
from pathlib import Path

# Keep equal to harness_install_transaction.ROOTS plus CLAUDE.local.md (locked by tests).
LINK_ROOTS = ('.agent-flow', '.agents/skills', '.claude/agents', '.claude/hooks',
              '.claude/skills', '.claude/settings.json', '.codex/agents',
              '.codex/config.toml', '.codex/hooks.json', 'AGENTS.md', 'CLAUDE.md',
              'CLAUDE.local.md', 'retro/RETRO.md', 'retro/BUGLOG.md')


def _git_path(root, flag):
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', flag],
                            capture_output=True, text=True, errors='replace', timeout=5)
    if result.returncode:
        return None
    path = Path(result.stdout.strip())
    return (path if path.is_absolute() else root / path).resolve()


def main_checkout(root):
    """Return the main working tree when root is a linked worktree, else None."""
    git_dir = _git_path(root, '--git-dir')
    common = _git_path(root, '--git-common-dir')
    if git_dir is None or common is None or git_dir == common:
        return None
    return common.parent


def ensure_links(root):
    """Create missing toolchain links in the worktree at root; return the created paths."""
    try:
        root = Path(root).resolve()
        main = main_checkout(root)
        if main is None or main == root or not main.is_dir():
            return []
        created = []
        for name in LINK_ROOTS:
            source, destination = main / name, root / name
            if destination.exists() or destination.is_symlink():
                continue
            if not (source.exists() or source.is_symlink()):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.path.relpath(source, destination.parent))
            created.append(name)
        return created
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    created = ensure_links(argv[0] if argv else os.getcwd())
    print('已為 worktree 建立工具鏈連結：' + ', '.join(created) if created else '無需建立連結')
    return 0


if __name__ == '__main__':
    sys.exit(main())
