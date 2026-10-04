#!/usr/bin/env python3
"""Translate CLI arguments and tool events into the shared flow contract."""
import json
import math
import re

HARNESSES = ('claude', 'codex')
PERMISSIONS = ('inherit', 'unrestricted')


def capabilities(harness):
    if harness not in HARNESSES:
        raise ValueError(f'unsupported harness: {harness}')
    return {'cost_limit_usd': harness == 'claude', 'resume': True,
            'command_hooks': True, 'file_hooks': True}


def build_argv(harness, *, role=None, model=None, reasoning_effort='low',
               resume=None, permissions='inherit', budget_usd=None):
    capabilities(harness)
    if permissions not in PERMISSIONS:
        raise ValueError(f'unsupported permissions: {permissions}')
    if budget_usd is not None and (not math.isfinite(budget_usd) or budget_usd <= 0):
        raise ValueError('budget_usd must be finite and positive')
    if harness == 'claude':
        argv = ['claude', '-p', '--output-format', 'json']
        if role:
            argv += ['--agent', role]
        if model:
            argv += ['--model', model]
        if resume:
            argv += ['--resume', resume]
        if budget_usd is not None:
            argv += ['--max-budget-usd', f'{budget_usd:.2f}']
        if permissions == 'unrestricted':
            argv += ['--dangerously-skip-permissions']
    else:
        if budget_usd is not None:
            raise ValueError('Codex CLI cannot enforce a USD budget; use bounded runs and timeout')
        argv = ['codex', 'exec'] + (['resume', resume] if resume else [])
        argv += ['--json', '--skip-git-repo-check']
        if model:
            argv += ['-m', model]
        argv += ['-c', f'model_reasoning_effort={reasoning_effort}']
        if permissions == 'unrestricted':
            argv += ['--dangerously-bypass-approvals-and-sandbox']
    return argv + ['-']


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_result(harness, stdout, returncode=0):
    capabilities(harness)
    out = {'result': None, 'session_id': None, 'model': None, 'num_turns': None,
           'total_cost_usd': None, 'usage': {}, 'is_error': False,
           'error': None, 'budget_exhausted': False}
    errors = []
    if harness == 'claude':
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            data = None
        if not isinstance(data, dict):
            errors.append('Claude output is not a JSON object')
        else:
            out['result'] = data.get('result') if isinstance(data.get('result'), str) else None
            out['session_id'] = data.get('session_id') if isinstance(data.get('session_id'), str) else None
            out['num_turns'] = _integer(data.get('num_turns'))
            cost = data.get('total_cost_usd')
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
                out['total_cost_usd'] = cost
            out['usage'] = data.get('usage') if isinstance(data.get('usage'), dict) else {}
            models = data.get('modelUsage')
            if isinstance(models, dict):
                out['model'] = next(iter(models), None)
            out['budget_exhausted'] = bool(data.get('is_error') and 'budget' in str(data.get('subtype', '')))
            if data.get('is_error'):
                errors.append(str(data.get('result') or data.get('errors') or data.get('subtype') or 'Claude reported an error'))
    else:
        for line in (stdout or '').splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get('type')
            if kind == 'thread.started':
                out['session_id'] = event.get('thread_id') if isinstance(event.get('thread_id'), str) else None
            elif kind == 'item.completed':
                item = event.get('item')
                if isinstance(item, dict) and item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
                    out['result'] = item['text']
            elif kind == 'turn.completed':
                out['num_turns'] = (out['num_turns'] or 0) + 1
                usage = event.get('usage')
                if isinstance(usage, dict):
                    for key, value in usage.items():
                        out['usage'][key] = out['usage'].get(key, 0) + _integer(value)
            elif kind in ('error', 'turn.failed'):
                errors.append(str(event.get('message') or event.get('error') or kind))
    if returncode:
        errors.append(f'{harness} exit {returncode}')
    if not isinstance(out['result'], str) or not out['result'].strip():
        errors.append('missing agent_message report' if harness == 'codex' else 'missing result report')
    out['is_error'] = bool(errors)
    out['error'] = '; '.join(errors) if errors else None
    return out


def normalize_hook(payload):
    """Keep the canonical hook schema; translate raw local tools and patch paths."""
    if not isinstance(payload, dict):
        return {'tool_name': '', 'tool_input': {}}
    out = dict(payload)
    name = payload.get('tool_name', '')
    value = payload.get('tool_input')
    data = dict(value) if isinstance(value, dict) else {}
    if name in ('exec_command', 'shell', 'shell_command'):
        name = 'Bash'
        command = data.get('cmd', data.get('command', ''))
        data['command'] = command if isinstance(command, str) else ''
    if name == 'spawn_agent':
        name = 'Agent'
        data['subagent_type'] = data.get('agent_type', '')
    if name == 'apply_patch':
        patch = data.get('command', data.get('patch', value if isinstance(value, str) else ''))
        data['_write_paths'] = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M) if isinstance(patch, str) else []
    if 'command' in data and not isinstance(data['command'], str):
        data['command'] = ''
    out.update(tool_name=name, tool_input=data)
    return out
