"""Plan installation in a temporary tree and roll back caught write failures.

Only installer-owned paths are staged. No target writes occur during planning.
Rollback covers ordinary process errors, not power loss or forced termination.
"""
import hashlib
import json
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

OWNERSHIP = '.agent-flow/install-manifest.json'
ROOTS = ('.agent-flow', '.agents/skills', '.claude/agents', '.claude/hooks',
         '.claude/skills', '.claude/settings.json', '.codex/agents',
         '.codex/config.toml', '.codex/hooks.json', 'AGENTS.md', 'CLAUDE.md',
         'CLAUDE.local.md', 'retro/RETRO.md', 'retro/BUGLOG.md')
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', 'worktrees')


def snapshot(root):
    result = {}
    def visit(path):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            result[rel] = ('link', os.readlink(path), 0)
        elif path.is_file():
            result[rel] = ('file', path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        elif path.is_dir():
            for child in path.iterdir():
                if child.name not in IGNORE(str(path), [child.name]):
                    visit(child)
    for name in ROOTS:
        visit(root / name)
    return result


def managed_hash(name, state):
    """Mixed instruction/config files own only the framework section."""
    if state is None:
        return None
    kind, value, mode = state
    if kind == 'file':
        text = value.decode('utf-8', errors='replace')
        if name in ('AGENTS.md', 'CLAUDE.md', 'CLAUDE.local.md'):
            harness = 'codex' if name == 'AGENTS.md' else 'claude'
            start = f'<!-- agent-workspace {harness} instructions -->'
            end = f'<!-- /agent-workspace {harness} instructions -->'
            if start not in text or end not in text:
                return None  # No framework section: the project owns the whole file.
            value = text[text.index(start):text.index(end) + len(end)].encode()
        elif name in ('.claude/settings.json', '.codex/hooks.json'):
            data = json.loads(text)
            owned = {}
            for event, entries in data.get('hooks', {}).items():
                selected = []
                for entry in entries:
                    hooks = [h for h in entry.get('hooks', []) if any(
                        f'/{folder}/' in h.get('command', '')
                        for folder in ('.agent-flow/scripts', '.claude/hooks'))]
                    if hooks:
                        selected.append({**entry, 'hooks': hooks})
                if selected:
                    owned[event] = selected
            value = json.dumps(owned, sort_keys=True).encode()
        elif name == '.codex/config.toml':
            config = tomllib.loads(text)
            agents = config.get('agents', {})
            owned = {k: v for k, v in agents.items() if k == 'default_subagent_model' or
                     (isinstance(v, dict) and v.get('config_file') == f'agents/{k}.toml')}
            notes = config.get('developer_instructions')
            start, end = '<!-- agent-workspace codex instructions -->', '<!-- /agent-workspace codex instructions -->'
            if isinstance(notes, str) and start in notes and end in notes:
                owned['developer_instructions'] = notes[notes.index(start):notes.index(end) + len(end)]
            value = json.dumps(owned, sort_keys=True).encode()
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(kind.encode() + str(mode).encode() + raw).hexdigest()


def _validate_paths(target):
    for name in ROOTS:
        path = target / name
        for parent in (path, *path.parents):
            if parent == target.parent:
                break
            if parent.is_symlink():
                raise ValueError(f'preserving symlink path; installation refuses to follow: {parent}')
    for name, state in snapshot(target).items():
        if state[0] != 'link':
            continue
        # Skills are replaced by unlinking, never by writing through the link.
        if name.startswith(('.agents/skills/', '.claude/skills/')):
            continue
        if os.path.isabs(state[1]):
            raise ValueError(f'refusing absolute symlink during planning: {name}')
        resolved = (target / name).resolve()
        if resolved.is_dir():
            raise ValueError(f'refusing directory symlink: {name}')
        if not resolved.is_relative_to(target):
            raise ValueError(f'unsafe external symlink: {name}')


def build_plan(target, harness, populate, source=None):
    _validate_paths(target)
    before = snapshot(target)
    previous = json.loads((target / OWNERSHIP).read_text()) if (target / OWNERSHIP).exists() else {'files': {}}
    if not isinstance(previous.get('files'), dict):
        raise ValueError('invalid install ownership manifest')
    with tempfile.TemporaryDirectory(prefix='harness-plan-') as tmp:
        stage = Path(tmp) / 'project'
        stage.mkdir()
        for name in ROOTS:
            src, dst = target / name, stage / name
            if src.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to(os.readlink(src))
            elif src.is_dir():
                shutil.copytree(src, dst, symlinks=True, ignore=IGNORE)
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        repo_mode = source is not None and target == source
        if repo_mode:
            shutil.copytree(source / 'skills', stage / 'skills', ignore=IGNORE)
        populate(stage, harness, repo_mode)
        after = snapshot(stage)
    before.pop(OWNERSHIP, None)
    after.pop(OWNERSHIP, None)
    changes, conflicts = {}, []
    owned = dict(previous['files'])
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            # Claim matching generated assets, but not arbitrary preserved files.
            if name not in owned and new and _generated(name, new) and _provided(name, source):
                owned[name] = managed_hash(name, new)
            continue
        expected = previous['files'].get(name)
        if expected and managed_hash(name, old) != expected and managed_hash(name, old) != managed_hash(name, new):
            conflicts.append(name)
        elif old and not expected and not repo_mode and _generated(name, old) and managed_hash(name, old) != managed_hash(name, new):
            # On first adoption, a marker alone cannot prove that edits are disposable.
            # Mixed files are merged by the existing installer, so preserve user sections.
            if name not in ('AGENTS.md', 'CLAUDE.md', 'CLAUDE.local.md', '.claude/settings.json', '.codex/hooks.json', '.codex/config.toml'):
                conflicts.append(name)
        elif old and new is None and not expected:
            conflicts.append(name)
        changes[name] = new
        if new is None or managed_hash(name, new) is None:
            owned.pop(name, None)
        else:
            owned[name] = managed_hash(name, new)
    manifest = json.dumps({'schema': 1, 'files': owned}, indent=2, sort_keys=True).encode() + b'\n'
    old_manifest = (target / OWNERSHIP).read_bytes() if (target / OWNERSHIP).exists() else None
    if manifest != old_manifest:
        changes[OWNERSHIP] = ('file', manifest, 0o644)
    return {'target': target, 'before': snapshot(target), 'changes': changes, 'conflicts': conflicts}


def _provided(name, source):
    if source is None:
        return True
    if name.startswith('.agent-flow/'):
        return (source / name).is_file()
    if name.startswith('.agents/skills/'):
        return (source / 'skills' / name.removeprefix('.agents/skills/')).exists()
    if name.startswith('.claude/hooks/'):
        return (source / '.agent-flow/scripts' / Path(name).name).is_file()
    return True


def _generated(name, state):
    if state[0] == 'link':
        return name.startswith(('.claude/hooks/', '.claude/skills/', '.agents/skills/'))
    value = state[1]
    return (name.startswith(('.agent-flow/', '.agents/skills/')) or
            value.startswith(b'# Generated by agent_workspace/') or b'agent-workspace shared role' in value)


def replace_state(path, state):
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if child.is_dir() and not child.is_symlink():
                child.rmdir()  # Never remove a remaining file.
        path.rmdir()
    if state is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.harness-write-', dir=path.parent)
    temp = Path(name)
    try:
        if state[0] == 'link':
            os.close(fd)
            temp.unlink()
            temp.symlink_to(state[1])
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(state[1])
            temp.chmod(state[2])
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def apply_plan(plan, writer=replace_state, finalize=None, external=None):
    target = plan['target']
    if plan['conflicts']:
        raise ValueError('modified managed files: ' + ', '.join(plan['conflicts']))
    _validate_paths(target)
    if snapshot(target) != plan['before']:
        raise ValueError('target changed after planning; rebuild plan')
    external = external or {}
    existing_dirs = {p for p in target.rglob('*') if p.is_dir() and not p.is_symlink()} if target.exists() else set()
    target_existed = target.exists()
    applied = []
    changes = plan['changes']
    order = sorted(changes, key=lambda n: (changes[n] is not None, -len(Path(n).parts) if changes[n] is None else len(Path(n).parts), n))
    # Ownership is written last, after all installed assets.
    order = [n for n in order if n != OWNERSHIP] + ([OWNERSHIP] if OWNERSHIP in changes else [])
    try:
        for name in order:
            applied.append(name)
            writer(target / name, changes[name])
        if finalize:
            finalize()
    except Exception:
        for path, old in external.items():
            replace_state(path, old)
        for name in reversed(applied):
            replace_state(target / name, plan['before'].get(name))
        if target.exists():
            for path in sorted(target.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir() and not path.is_symlink() and path not in existing_dirs:
                    try:
                        path.rmdir()
                    except OSError:
                        pass
            if not target_existed:
                target.rmdir()
        raise
