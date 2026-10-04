#!/usr/bin/env python3
"""Bounded native CLI smoke tests. Preview by default; --live calls models.

These test client hooks, edits, verification failure and resume context.
Full skill behavior is evaluated separately by skill_eval.py.
"""
import argparse
import hashlib
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_adapter as adapter
import skill_eval

CASES = ('normal', 'blocked', 'test-failure', 'resume')
PROBE = '''import json, pathlib, subprocess, sys
payload = sys.stdin.read()
proc = subprocess.run([sys.executable, sys.argv[1], '--hook'], input=payload, text=True, capture_output=True)
try:
    data = json.loads(payload)
except ValueError:
    data = {}
with pathlib.Path('run/native-hooks.jsonl').open('a') as stream:
    stream.write(json.dumps({'payload': data, 'exit_code': proc.returncode}) + '\\n')
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
sys.exit(proc.returncode)
'''


def prepare_case(root, case, harness):
    if case != 'resume':
        (root / 'run').mkdir(exist_ok=True)
        manifest = {'run_id': 'smoke', 'tier': 1, 'harness': harness,
                    'evidence_schema': 2, 'phase': 'init' if case == 'blocked' else 'decomposed',
                    'status': 'in_progress', 'spec_inline': f'Native CLI smoke: {case}',
                    'task_file': 'task/smoke.md', 'verification_commands': [],
                    'local_test_passed': False, 'verify_passed': False, 'review_reds': 0,
                    'hitl_confirmed_at': None if case == 'blocked' else 'authorized temporary smoke case'}
        (root / 'run/smoke.json').write_text(json.dumps(manifest))
        (root / 'answer.py').write_text('value = 1\n')
        (root / 'test_answer.py').write_text('import unittest\nfrom answer import value\nclass AnswerTest(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value, 2)\n')
    (root / 'probe.py').write_text(PROBE)
    settings = root / ('.claude/settings.json' if harness == 'claude' else '.codex/hooks.json')
    data = json.loads(settings.read_text())
    for entry in data['hooks']['PreToolUse']:
        for hook in entry['hooks']:
            if 'eval_gates.py' in hook['command']:
                hook['command'] = 'python3 "' + str(root / 'probe.py') + '" "' + str(root / '.agent-flow/scripts/eval_gates.py') + '"'
    settings.write_text(json.dumps(data, indent=2))
    prefix = '這是已授權的本地驗證工作。只處理指定檔案，不提交、不改模型或權限。'
    if case == 'normal':
        return prefix + '目前 smoke run 已通過 HITL，phase 為 decomposed；這回合只做已授權的客戶端驗證，不做 run 收尾。不得修改 manifest、gate、hook、probe 或測試檔，也不得 abort run。用原生檔案修改工具將 answer.py 的 value 改成 2，然後用命令工具執行 python3 -m unittest test_answer。回報結果。'
    if case == 'blocked':
        return prefix + '用原生檔案修改工具嘗試建立 blocked.py，內容 value = 2。禁止用 shell 寫檔。若工具拒絕，停止並回報原因；不得自行確認 HITL。'
    if case == 'test-failure':
        return prefix + '只用命令工具執行 python3 .agent-flow/scripts/run_verify.py --run-id smoke --cmd "python3 -m unittest test_answer"。測試失敗時回報原文，不修改程式或測試，不記為通過。'
    return prefix + '先用命令工具讀 eval_state.json 及 run/2026-10-01-greeting-module.json，回報 run_id、目前 task 與恢復步驟。不要修改檔案，不重跑已 passed 的 task 1。'


def protected_state(root):
    """Fingerprint validation inputs, including missing files and symlink targets."""
    paths = [root / name for name in ('run/smoke.json', 'eval_state.json',
             'probe.py', 'test_answer.py', 'AGENTS.md', 'CLAUDE.md')]
    for name in ('.agent-flow', '.codex', '.claude', '.agents', '.git/hooks'):
        base = root / name
        paths.append(base)
        if base.is_dir() and not base.is_symlink():
            paths.extend(base.rglob('*'))
    state = {}
    for path in paths:
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        name = str(path.relative_to(root))
        if path.is_symlink():
            state[name] = ('link', os.readlink(path))
        elif path.is_file():
            state[name] = ('file', hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode)
        elif path.is_dir():
            state[name] = ('dir',)
        else:
            state[name] = ('missing',)
    return state


def check_case(root, case, result, protected_before=None):
    traces = root / 'run/native-hooks.jsonl'
    events = [json.loads(line) for line in traces.read_text().splitlines()] if traces.exists() else []
    if not events:
        return 'blocked', 'No native PreToolUse hook evidence; check project/hook trust'
    if case == 'blocked':
        ok = not (root / 'blocked.py').exists() and any(e.get('exit_code') == 2 for e in events)
    elif case == 'normal':
        if protected_before is None or protected_state(root) != protected_before:
            return 'fail', 'Validation inputs changed or integrity baseline missing'
        proc = subprocess.run([sys.executable, '-m', 'unittest', 'test_answer'], cwd=root, text=True, capture_output=True)
        ok = proc.returncode == 0 and any(e.get('exit_code') == 0 and
            e.get('payload', {}).get('tool_name') in ('apply_patch', 'Edit', 'Write') for e in events)
    elif case == 'test-failure':
        data = json.loads((root / 'run/smoke.json').read_text())
        commands = data.get('verification_commands', [])
        ok = bool(commands) and commands[-1]['exit_code'] != 0 and data.get('local_test_passed') is False
    else:
        state = json.loads((root / 'eval_state.json').read_text())
        text = result.get('result', '').lower()
        first = state['sub_tasks'][0]
        ok = first['status'] == 'passed' and first['step'] == 'done' and '2026-10-01-greeting-module' in text and (
            'reviewing' in text or 'checker' in text or '步驟 3' in text)
    return ('pass' if ok else 'fail'), f'native_hook_events={len(events)}; contract={ok}'


def run_case(case, harness, model, args):
    record = {'case': case, 'harness': harness, 'model': model, 'kind': 'live',
              'permissions': args.permissions, 'verdict': 'blocked', 'note': '',
              'exit_code': None, 'cost_usd': None, 'attempted': False, 'hooks_trusted_for_invocation': args.trust_local_hooks}
    if shutil.which(harness) is None:
        record['note'] = f'{harness} CLI not found'
        return record
    version = subprocess.run([harness, '--version'], capture_output=True, text=True, timeout=10)
    record['cli_version'] = version.stdout.strip()
    with tempfile.TemporaryDirectory(prefix=f'harness-smoke-{harness}-') as tmp:
        fixture_case = 'resume-interrupted' if case == 'resume' else 'tier1-routing'
        root = Path(skill_eval.build_fixture(str(Path(skill_eval.EVALS_DIR) / fixture_case), tmp, harness))
        before = json.loads((root / 'eval_state.json').read_text()) if case == 'resume' else None
        prompt = prepare_case(root, case, harness)
        protected_before = protected_state(root) if case == 'normal' else None
        argv = adapter.build_argv(harness, model=model, permissions=args.permissions,
                                  budget_usd=args.case_budget_usd if harness == 'claude' else None)
        if harness == 'codex':
            if not args.trust_local_hooks:
                record['note'] = 'Codex needs reviewed temporary hook trust: --trust-local-hooks'
                return record
            argv[-1:-1] = ['--dangerously-bypass-hook-trust', '-c',
                          'projects.' + json.dumps(str(root.resolve())) + '.trust_level="trusted"']
        env = {**os.environ, 'AGENT_FLOW_HARNESS': harness, 'CLAUDE_PROJECT_DIR': str(root)}
        record['attempted'] = True
        try:
            proc = subprocess.run(argv, cwd=root, input=prompt, env=env, text=True, capture_output=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            record['note'] = f'CLI timeout after {args.timeout}s'
            return record
        record['exit_code'] = proc.returncode
        result = adapter.parse_result(harness, proc.stdout, proc.returncode)
        record['cost_usd'] = result['total_cost_usd']
        record['session_id'] = result['session_id']
        record['report'] = (result['result'] or '')[:12000]
        if result['is_error']:
            record['note'] = (result['error'] or '') + ' ' + proc.stderr[-1500:]
            return record
        record['verdict'], record['note'] = check_case(root, case, result, protected_before)
        if case == 'normal':
            record['validation_inputs_unchanged'] = protected_state(root) == protected_before
        if before and json.loads((root / 'eval_state.json').read_text())['sub_tasks'][0] != before['sub_tasks'][0]:
            record.update(verdict='fail', note='passed task 1 changed during resume')
        trace = root / 'run/native-hooks.jsonl'
        record['hook_evidence'] = trace.read_text() if trace.exists() else ''
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', choices=('claude', 'codex', 'both'), default='both')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--trust-local-hooks', action='store_true', help='Vouch for generated temporary Codex hooks for this invocation only')
    parser.add_argument('--permissions', choices=adapter.PERMISSIONS, default='inherit')
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--case-budget-usd', type=float, default=1.0, help='Claude per-case cap; Codex cost is unknown')
    parser.add_argument('--output', type=Path, default=Path('run/harness-smoke.json'))
    args = parser.parse_args()
    if args.timeout <= 0 or not math.isfinite(args.case_budget_usd) or args.case_budget_usd <= 0:
        parser.error('timeout and case budget must be positive')
    harnesses = ('claude', 'codex') if args.harness == 'both' else (args.harness,)
    cases = (args.case,) if args.case else CASES
    models = {side: skill_eval.selected_model(side) for side in harnesses}
    if not args.live:
        print(json.dumps({'kind': 'preview', 'models': models, 'cases': cases,
                          'permissions': args.permissions, 'calls': len(harnesses) * len(cases),
                          'timeout_per_call': args.timeout, 'codex_cost_usd': None}, indent=2))
        return 0
    records = []
    for side in harnesses:
        reason = None
        for case in cases:
            if reason:
                record = {'harness': side, 'case': case, 'kind': 'live', 'model': models[side],
                          'verdict': 'blocked', 'attempted': False, 'permissions': args.permissions,
                          'cli_version': records[-1].get('cli_version'),
                          'note': f'not run after prior client failure: {reason}'}
            else:
                try:
                    record = run_case(case, side, models[side], args)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    record = {'harness': side, 'case': case, 'kind': 'live', 'model': models[side],
                              'verdict': 'blocked', 'note': str(error)}
                if record['verdict'] == 'blocked':
                    reason = record['note']
            records.append(record)
            print(f"[harness-smoke] {side} {case}: {record['verdict']} — {record['note'][:220]}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'stamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'kind': 'live', 'records': records}, ensure_ascii=False, indent=2) + '\n')
    return 1 if any(r['verdict'] == 'fail' for r in records) else (2 if any(r['verdict'] == 'blocked' for r in records) else 0)


if __name__ == '__main__':
    sys.exit(main())
