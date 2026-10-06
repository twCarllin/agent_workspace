#!/usr/bin/env python3
"""Install the shared Eval Flow and selected harness adapters."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tomllib
import re
import sys
from harness_install_transaction import build_plan, apply_plan, snapshot
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE / '.agent-flow/scripts'))
from document_inventory import skill_directories
PROFILES = json.loads((SOURCE / '.agent-flow/harnesses/models.json').read_text())
CODEX_MODELS = {r: (v['model'], v['reasoning_effort']) for r, v in PROFILES['codex'].items()}
MANAGED = '<!-- agent-workspace managed -->'
LEGACY = json.loads((SOURCE / '.agent-flow/harnesses/legacy.json').read_text())


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)


def link_file(target, source):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(os.path.relpath(source, target.parent))


EXCLUDE_START = '# >>> agent-workspace managed >>>'
EXCLUDE_END = '# <<< agent-workspace managed <<<'
# Toolchain paths kept out of the project's commits. Written to the repository's
# info/exclude (shared by every worktree) instead of the tracked .gitignore.
# A leading slash anchors each entry to the repository root, so src/run/ stays tracked.
# No trailing slash: a worktree holds these paths as symlinks, and "dir/" matches directories only.
EXCLUDE_PATHS = ('/.agent-flow', '/.agents', '/.claude/agents', '/.claude/hooks', '/.claude/skills',
                 '/.claude/settings.json', '/.claude/worktrees', '/.codex/agents', '/.codex/config.toml',
                 '/.codex/hooks.json', '/CLAUDE.local.md', '/retro', '/run', '/task', '/eval_state.json')


def _with_section(text, marker, end_marker, block):
    start = text.find(marker)
    if start >= 0:
        end = text.find(end_marker, start)
        if end < 0:
            raise ValueError(f'unterminated managed section before {end_marker}')
        return text[:start] + block + text[end + len(end_marker):]
    return (text.rstrip() + '\n\n' if text.strip() else '') + block + '\n'


def _without_section(text, marker, end_marker):
    start = text.find(marker)
    if start < 0:
        return text
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError(f'unterminated managed section before {end_marker}')
    head, tail = text[:start].rstrip(), text[end + len(end_marker):].lstrip('\n')
    return (head + '\n' if head else '') + ('\n' + tail if head and tail else tail)


def instructions(target, harness, repo_mode=False):
    path = target / ('AGENTS.md' if harness == 'codex' else 'CLAUDE.md')
    marker = f'<!-- agent-workspace {harness} instructions -->'
    end_marker = f'<!-- /agent-workspace {harness} instructions -->'
    block = f'''{marker}
## Eval Flow

Read `.agent-flow/HARNESS.md`, `.agent-flow/{harness.upper()}_ADAPTER.md`, and `.agent-flow/PRACTICES.md`.
For implementation, read `.agent-flow/ROUTER.md`, then load only the selected `.agents/skills/<name>/SKILL.md`. Diagnose bugs before routing; use eval-flow-resume for an interrupted run.
New Tier 1/2 manifests use `harness: "{harness}"` and `evidence_schema: 2`. Keep independent review and test evidence. Run the final verification with `python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd "<project test command>"`; prepare, commit with Run-Id, then finalize with run_commit.py.
Use the matching role, with goal, context, constraints, and done conditions. Respect project instructions and current session permissions.
{end_marker}'''
    existing = path.read_text() if path.exists() else ''
    if harness == 'claude':
        if hashlib.sha256(existing.encode()).hexdigest() in LEGACY['routers']:
            # A legacy full Router is framework-owned: replace it in place.
            existing = ''
        elif not repo_mode:
            # The project's CLAUDE.md stays untouched (and uncommitted changes stay out of it);
            # the framework section lives in CLAUDE.local.md, which info/exclude keeps untracked.
            stripped = _without_section(existing, marker, end_marker)
            if stripped != existing:
                path.write_text(stripped)
            path = target / 'CLAUDE.local.md'
            existing = path.read_text() if path.exists() else ''
    path.write_text(_with_section(existing, marker, end_marker, block))


def git_exclude_path(target):
    result = subprocess.run(['git', '-C', str(target), 'rev-parse', '--git-path', 'info/exclude'],
                            capture_output=True, text=True)
    if result.returncode:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else target / path


def exclude_target(target):
    """info/exclude to manage for target; None for this repository itself or a non-Git directory."""
    return None if target == SOURCE else git_exclude_path(target)


def git_side_effects(target, hook, exclude):
    """Finalize step and pre-apply state for the Git files written outside the planned tree."""
    external = {}
    if hook:
        external[hook] = ('link', os.readlink(hook), 0) if hook.is_symlink() else (
            ('file', hook.read_bytes(), hook.stat().st_mode & 0o777) if hook.exists() else None)
    if exclude:
        external[exclude] = ('file', exclude.read_bytes(), exclude.stat().st_mode & 0o777) if exclude.exists() else None

    def finalize():
        install_git_hook(target)
        if exclude:
            install_git_exclude(target)
    return finalize, external


def install_git_exclude(target):
    path = git_exclude_path(target)
    if path is None:
        return
    existing = path.read_text() if path.exists() else ''
    block = '\n'.join((EXCLUDE_START, *EXCLUDE_PATHS, EXCLUDE_END))
    updated = _with_section(existing, EXCLUDE_START, EXCLUDE_END, block)
    if updated != existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated)


def install_core(target, repo_mode=False):
    for path in (SOURCE / '.agent-flow').glob('*.md'):
        if path.name == 'legacy-claude-router.md':
            continue
        destination = target / '.agent-flow' / path.name
        if destination.exists() and destination.resolve() != path.resolve():
            if not destination.read_text().startswith(MANAGED):
                raise ValueError(f'preserving custom shared document: {destination}')
        copy_file(path, destination)
    for folder in ('scripts', 'roles', 'harnesses'):
        for path in (SOURCE / '.agent-flow' / folder).iterdir():
            if path.is_file() and path.name != '.DS_Store':
                destination = target / '.agent-flow' / folder / path.name
                copy_file(path, destination)
                if folder == 'scripts':
                    link_file(target / '.claude/hooks' / path.name, destination)
    skills = target / '.agents/skills'
    skills.mkdir(parents=True, exist_ok=True)
    names = {p.name for p in skill_directories(SOURCE)}
    for path in skills.iterdir():
        if path.name not in names and (path / '.agent-workspace-managed').exists():
            if path.is_symlink():
                path.unlink()
            else:
                shutil.rmtree(path)
    for name in sorted(names):
        source = SOURCE / 'skills' / name
        destination = skills / name
        if target == SOURCE or repo_mode:
            if destination.is_symlink():
                destination.unlink()
            elif destination.exists():
                if not (destination / '.agent-workspace-managed').exists():
                    print(f'[harness] preserved custom skill: {destination}')
                    continue
                shutil.rmtree(destination)
            destination.symlink_to(os.path.relpath(target / "skills" / name if repo_mode else source, destination.parent))
            continue
        if destination.exists() or destination.is_symlink():
            if not (destination / '.agent-workspace-managed').exists():
                print(f'[harness] preserved custom skill: {destination}')
                continue
            if destination.is_symlink():
                destination.unlink()
            else:
                shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
        (destination / '.agent-workspace-managed').write_text('managed by agent_workspace\n')
    retro = target / 'retro'
    retro.mkdir(exist_ok=True)
    if not (retro / 'RETRO.md').exists():
        copy_file(SOURCE / 'seed/RETRO.seed.md', retro / 'RETRO.md')
    if not (retro / 'BUGLOG.md').exists():
        header, sep, _ = (SOURCE / 'retro/BUGLOG.md').read_text().partition('\n---\n')
        if not sep:
            raise ValueError('BUGLOG lacks header separator')
        (retro / 'BUGLOG.md').write_text(header + sep)


def install_agents(target, harness):
    for role, profile in PROFILES[harness].items():
        body = (SOURCE / '.agent-flow/roles' / f'{role}.md').read_text()
        suffix = 'md' if harness == 'claude' else 'toml'
        path = target / f'.{harness}/agents/{role}.{suffix}'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and target != SOURCE:
            old = path.read_text()
            known = hashlib.sha256(old.encode()).hexdigest() in LEGACY['agents'].get(role, [])
            if not known and not old.startswith('# Generated by agent_workspace/') and 'agent-workspace shared role' not in old:
                print(f'[harness] preserved custom agent: {path}')
                continue
        if harness == 'claude':
            content = '---\n' + profile['frontmatter'] + '\n---\n\n' + body
        else:
            values = {'name': role, 'description': profile['description'], 'model': profile['model'],
                      'model_reasoning_effort': profile['reasoning_effort'],
                      'developer_instructions': body + '\nUse the Codex adapter and current session tools and permissions.\n'}
            content = '# Generated by agent_workspace/install_harness.py\n' + ''.join(
                f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in values.items())
        path.write_text(content)


def merge_hooks(target, harness):
    path = target / ('.claude/settings.json' if harness == 'claude' else '.codex/hooks.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    prefix = '$CLAUDE_PROJECT_DIR' if harness == 'claude' else '$(git rev-parse --show-toplevel)'
    script = f'"{prefix}/.agent-flow/scripts/'
    entries = {
        'PreToolUse': {'matcher': 'Bash|Task|Agent|Write|Edit|MultiEdit|NotebookEdit' if harness == 'claude' else 'Bash|Agent|apply_patch',
                      'hooks': [{'type': 'command', 'command': f'python3 {script}eval_gates.py" --hook', 'timeout': 30}]},
        'SessionStart': {'matcher': 'startup|resume|compact',
                         'hooks': [{'type': 'command', 'command': f'AGENT_FLOW_HARNESS={harness} python3 {script}session_start.py"', 'timeout': 15}]},
    }
    if harness == 'claude':
        entries['PostToolUse'] = {'matcher': 'Task|Agent', 'hooks': [
            {'type': 'command', 'command': f'python3 {script}report_envelope_check.py"'}]}
    scripts = {'PreToolUse': ('gate-check.sh', 'eval_gates.py'), 'SessionStart': ('session_start.py',),
               'PostToolUse': ('report_envelope_check.py',)}
    for event, entry in entries.items():
        current = data.setdefault('hooks', {}).setdefault(event, [])
        # Recognize only framework paths, not arbitrary user commands with the
        # same basename. Preserve unrelated hooks and their order.
        kept = []
        for existing in current:
            remaining = [h for h in existing.get('hooks', []) if not any(
                f'/{folder}/{name}' in h.get('command', '')
                for folder in ('.claude/hooks', '.agent-flow/scripts') for name in scripts[event])]
            if remaining:
                kept.append({**existing, 'hooks': remaining})
        current[:] = kept
        current.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def register_codex_agents(target):
    path = target / '.codex/config.toml'
    text = path.read_text() if path.exists() else ''
    data = tomllib.loads(text)
    if 'default_subagent_model' not in data.get('agents', {}):
        model = PROFILES['codex']['code-writer']['model']
        setting = f'default_subagent_model = {json.dumps(model)}\n'
        header = re.search(r'^\[agents\]\s*$', text, re.M)
        if header:
            text = text[:header.end()] + '\n' + setting + text[header.end():]
        else:
            text += '\n[agents]\n' + setting
    for role in PROFILES['codex']:
        if role in data.get('agents', {}):
            continue
        text += f'\n[agents.{role}]\nconfig_file = "agents/{role}.toml"\n'
    path.write_text(text)


def install_git_hook(target):
    result = subprocess.run(['git', '-C', str(target), 'config', '--get', 'core.hooksPath'], capture_output=True, text=True)
    call = 'python3 "$(git rev-parse --show-toplevel)/.agent-flow/scripts/commit_message_gate.py" "$1"'
    if result.returncode == 0:
        print(f'[harness] existing core.hooksPath={result.stdout.strip()}; integrate: {call}')
        return
    result = subprocess.run(['git', '-C', str(target), 'rev-parse', '--git-path', 'hooks/commit-msg'], capture_output=True, text=True)
    if result.returncode:
        print('[harness] not a Git repository; commit-msg hook not installed')
        return
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = target / path
    if path.is_symlink() or (path.exists() and 'agent-workspace managed commit message gate' not in path.read_text()):
        print(f'[harness] preserved existing commit-msg hook: {path}; integrate: {call}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n# agent-workspace managed commit message gate\nexec ' + call + '\n')
    path.chmod(0o755)


def populate(target, harness, repo_mode=False):
    install_core(target, repo_mode)
    for side in ('claude', 'codex') if harness == 'both' else (harness,):
        instructions(target, side, repo_mode)
        install_agents(target, side)
        merge_hooks(target, side)
        if side == 'codex':
            register_codex_agents(target)
        else:
            for skill in (target / '.agents/skills').iterdir():
                destination = target / '.claude/skills' / skill.name
                if destination.exists() and not destination.is_symlink():
                    print(f'[harness] preserved custom Claude skill: {destination}')
                else:
                    link_file(destination, skill)


def git_hook_path(target):
    result = subprocess.run(['git', '-C', str(target), 'config', '--get', 'core.hooksPath'], capture_output=True, text=True)
    if result.returncode == 0:
        return None
    result = subprocess.run(['git', '-C', str(target), 'rev-parse', '--git-path', 'hooks/commit-msg'], capture_output=True, text=True)
    if result.returncode:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else target / path


def main(default='both'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', '--platform', '--p', choices=('claude', 'codex', 'both'), default=default)
    parser.add_argument('--target', type=Path, default=SOURCE.parent)
    parser.add_argument('--git-hook-only', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Preview without changing the target')
    args = parser.parse_args()
    # Resolve the parent, but reject a symlink target instead of following it.
    if args.target.is_symlink():
        parser.exit(1, f'[harness] refusing symlink target: {args.target}\n')
    target = args.target.resolve()
    try:
        plan = build_plan(target, args.harness, populate, source=SOURCE) if not args.git_hook_only else {
            'target': target, 'before': snapshot(target), 'changes': {}, 'conflicts': []}
        for name, state in plan['changes'].items():
            action = 'delete' if state is None else ('update' if name in plan['before'] else 'create')
            print(f'[harness] {action}: {name}')
        for name in plan['conflicts']:
            print(f'[harness] conflict: {name}')
        hook = git_hook_path(target)
        print(f'[harness] commit-msg: {hook if hook else "preserve / not a Git project"}')
        exclude = None if args.git_hook_only else exclude_target(target)
        print(f'[harness] info/exclude: {exclude if exclude else "preserve / not a Git project"}')
        if plan['conflicts']:
            parser.exit(1, '[harness] modified managed files; no target changes applied\n')
        if args.dry_run:
            print(f'[harness] preview {args.harness} in {target}; no target writes')
            return
        finalize, external = git_side_effects(target, hook, exclude)
        apply_plan(plan, finalize=finalize, external=external)
        print(f'[harness] installed {args.harness} in {target}')
    except (ValueError, OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        parser.exit(1, f'[harness] {error}\n')


if __name__ == '__main__':
    main()
