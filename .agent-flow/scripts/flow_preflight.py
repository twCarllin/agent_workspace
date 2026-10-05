#!/usr/bin/env python3
"""Bounded local readiness checks. Installed hooks do not prove client trust."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import tomllib

import doctor
import harness_adapter
import verification_snapshot


def _command(argv, timeout, prompt=None):
    """Kill the whole probe process group on timeout; never publish raw output."""
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if prompt else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return 'failed', None
        return ('ok' if process.returncode == 0 else 'failed'), stdout
    except OSError:
        return 'failed', None


class ModelConfigurationError(ValueError):
    """Controlled messages identify configuration faults without raw input."""


def _models(harness):
    root = Path.cwd()
    source = Path(__file__).resolve().parent.parent / 'harnesses' / 'models.json'
    profiles = json.loads(source.read_text())[harness]
    if not isinstance(profiles, dict) or not profiles:
        raise ModelConfigurationError('Model profiles are missing or invalid.')
    if harness == 'codex':
        config = tomllib.loads((root / '.codex/config.toml').read_text())
        agents = config.get('agents')
        if not isinstance(agents, dict):
            raise ModelConfigurationError('.codex/config.toml is missing agents.')
        default = agents.get('default_subagent_model')
        for role, expected in profiles.items():
            if not isinstance(expected, dict) or not isinstance(expected.get('model'), str) or not expected['model']:
                raise ModelConfigurationError(f'Model profile for {role} is invalid.')
            definition = agents.get(role)
            if not isinstance(definition, dict) or not isinstance(definition.get('config_file'), str):
                raise ModelConfigurationError(f'.codex/config.toml is missing role {role}.')
            path = (root / '.codex' / definition['config_file']).resolve()
            if not path.is_relative_to((root / '.codex').resolve()):
                raise ModelConfigurationError(f'Role {role} config is outside .codex/.')
            actual = tomllib.loads(path.read_text())
            if actual.get('model') != expected['model'] or actual.get('model_reasoning_effort') != expected.get('reasoning_effort'):
                raise ModelConfigurationError(f'Role {role} model does not match .agent-flow/harnesses/models.json.')
            if default is not None and default != expected['model']:
                raise ModelConfigurationError('.codex/config.toml default model does not match model profiles.')
        return profiles['code-writer']['model']
    model = None
    for role, expected in profiles.items():
        frontmatter = expected['frontmatter']
        match = re.search(r'^model:\s*(\S+)\s*$', frontmatter, re.M)
        actual = (root / '.claude/agents' / (role + '.md')).read_text()
        header = actual.split('---', 2)
        if len(header) != 3 or not match or not re.search(r'^model:\s*' + re.escape(match[1]) + r'\s*$', header[1], re.M):
            raise ModelConfigurationError(f'Role {role} model does not match .agent-flow/harnesses/models.json.')
        if role == 'code-writer':
            model = match[1]
    return model


def _logged_in(output):
    """Claude prints account details as JSON; only loggedIn is inspected and nothing is echoed."""
    try:
        data = json.loads(output or '')
    except ValueError:
        return False
    return isinstance(data, dict) and data.get('loggedIn') is True


def _test_command(run_id):
    if run_id is not None:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id):
            raise ValueError('invalid run id')
        data = json.loads((Path('run') / (run_id + '.json')).read_text())
        if not isinstance(data, dict):
            raise ValueError('invalid manifest')
        command = data.get('test_command')
    else:
        command = 'python3 -m unittest discover -s tests' if Path('tests').is_dir() else None
    if not isinstance(command, str) or not command.strip():
        return 'unknown', 'Test command is not configured.'
    # Check the first executable only. Shell pipelines/scripts are never run here.
    parts = shlex.split(command)
    if not parts or not shutil.which(parts[0]):
        return 'failed', 'Test executable is unavailable.'
    if any(part in ('&&', '||', '|', ';', '>', '>>', '<') for part in parts):
        return 'unknown', 'Compound test commands require separate validation; nothing was executed.'
    if Path(parts[0]).name.startswith('python') and len(parts) > 1:
        if not parts[1].startswith('-') and not Path(parts[1]).is_file():
            return 'failed', 'Test script is unavailable.'
        if parts[1:4] == ['-m', 'unittest', 'discover']:
            if '-s' in parts:
                position = parts.index('-s') + 1
                if position == len(parts) or not Path(parts[position]).is_dir():
                    return 'failed', 'Test discovery directory is unavailable.'
    return 'ok', 'Test executable exists; command was not executed.'


def preflight(harness='codex', run_id=None, live=False, timeout=30):
    if harness not in ('codex', 'claude'):
        raise ValueError('unsupported harness')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError('timeout must be between 0 and 300 seconds')
    checks = []
    def add(name, status, detail):
        checks.append({'name': name, 'status': status, 'detail': detail})
    try:
        _, issues = doctor.run_checks(harness=harness)
        add('deployment', 'failed' if issues else 'ok', 'Deployment checks failed: ' + '; '.join(issues) if issues else 'Deployment checks passed.')
    except (OSError, ValueError, TypeError, AttributeError):
        add('deployment', 'failed', 'Deployment configuration is invalid.')
    try:
        hook_path = Path('.codex/hooks.json' if harness == 'codex' else '.claude/settings.json')
        hooks = json.loads(hook_path.read_text())['hooks']['PreToolUse']
        configured = isinstance(hooks, list) and any(
            isinstance(entry, dict) and isinstance(entry.get('matcher'), str) and
            any(isinstance(hook, dict) and hook.get('type') == 'command' and
                isinstance(hook.get('command'), str) and 'eval_gates.py' in hook['command']
                for hook in entry.get('hooks', []) if isinstance(entry.get('hooks'), list))
            for entry in hooks)
        add('hook_config', 'ok' if configured else 'failed',
            'Gate command is configured; execution is unverified.' if configured else 'Gate hook configuration is missing.')
    except (OSError, ValueError, KeyError, TypeError):
        add('hook_config', 'failed', 'Hook configuration is invalid.')
    try:
        model = _models(harness)
        add('models', 'ok', 'Installed roles match model profiles.')
    except ModelConfigurationError as error:
        model = None
        add('models', 'failed', str(error))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        model = None
        add('models', 'failed', 'Model profile or installed role configuration is invalid or mismatched.')
    try:
        with tempfile.TemporaryFile(dir=Path.cwd()) as probe:
            probe.write(b'flow-preflight')
            probe.flush()
        add('workspace', 'ok', 'Workspace write probe passed.')
    except OSError:
        add('workspace', 'failed', 'Workspace write probe failed.')
    try:
        status, detail = _test_command(run_id)
        add('test_command', status, detail)
    except (OSError, ValueError, TypeError):
        add('test_command', 'failed', 'Run manifest or test command is invalid.')
    try:
        verification_snapshot.check_nested_repositories()
        add('nested_repositories', 'ok', 'No unsupported nested repository inputs.')
    except subprocess.CalledProcessError:
        add('nested_repositories', 'unknown', 'Git repository metadata is unavailable.')
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            add('nested_repositories', 'unknown', 'Git executable is unavailable.')
        else:
            add('nested_repositories', 'failed', str(error))
    executable = shutil.which(harness)
    add('cli', 'ok' if executable else 'failed', 'CLI found.' if executable else 'CLI not found.')
    if executable:
        status, output = _command([executable, '--version'], timeout)
        version = (output or '').strip()
        pattern = (r'codex(?:-cli)?[ \t]+[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?' if harness == 'codex'
                   else r'[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?[ \t]+\(Claude Code\)')
        if status == 'ok' and re.fullmatch(pattern, version):
            add('version', 'ok', version)
        else:
            add('version', 'unknown' if status == 'ok' else 'failed',
                'CLI version format was not recognized.' if status == 'ok' else 'CLI version command failed or timed out.')
        if harness == 'codex':
            status, output = _command([executable, 'login', 'status'], timeout)
            # Codex login status writes its success notice to stderr. Its exit status
            # is the public auth contract; discard both streams to avoid credentials.
        else:
            status, output = _command([executable, 'auth', 'status'], timeout)
            status = 'ok' if status == 'ok' and _logged_in(output) else 'failed'
        add('auth', status, 'Login status passed.' if status == 'ok' else 'Login check failed or timed out.')
        if live:
            if model and status == 'ok':
                argv = harness_adapter.build_argv(harness, model=model, budget_usd=0.10 if harness == 'claude' else None)
                argv[0] = executable
                state, output = _command(argv, timeout, 'Do not use tools. Reply only FLOW_PREFLIGHT_OK.\n')
                result = harness_adapter.parse_result(harness, output or '', 0 if state == 'ok' else 1)
                success = state == 'ok' and not result['is_error'] and (result['result'] or '').strip() == 'FLOW_PREFLIGHT_OK'
                add('live_probe', 'ok' if success else 'failed', 'Model response verified; hook trust was not tested.' if success else 'Model response probe failed or timed out.')
            else:
                add('live_probe', 'failed', 'Model or login check failed; live probe was skipped.')
    else:
        add('version', 'failed', 'CLI unavailable.')
        add('auth', 'unknown', 'CLI unavailable; login status is unknown.')
        if live:
            add('live_probe', 'failed', 'CLI unavailable; live probe was skipped.')
    add('hook_trust', 'unknown', 'Installed hook configuration does not prove client trust or hook execution.')
    readiness = 'blocked' if any(c['status'] == 'failed' for c in checks) else ('unknown' if any(c['status'] == 'unknown' for c in checks) else 'ready')
    return {'harness': harness, 'run_id': run_id, 'checks': checks, 'readiness': readiness, 'ready': readiness == 'ready'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', choices=('codex', 'claude'), default='codex')
    parser.add_argument('--run-id')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    try:
        result = preflight(**vars(args))
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {'ready': 0, 'blocked': 1, 'unknown': 2}[result['readiness']]


if __name__ == '__main__':
    raise SystemExit(main())
