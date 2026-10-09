"""Shared observable CLI and hook contracts; no model calls."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agent-flow/scripts'
spec = importlib.util.spec_from_file_location('harness_adapter', SCRIPTS / 'harness_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class AdapterTest(unittest.TestCase):
    def test_permissions_are_explicit_and_resume_is_preserved(self):
        for harness, flag in (('claude', '--dangerously-skip-permissions'),
                              ('codex', '--dangerously-bypass-approvals-and-sandbox')):
            with self.subTest(harness=harness):
                self.assertNotIn(flag, adapter.build_argv(harness))
                argv = adapter.build_argv(harness, resume='session', permissions='unrestricted')
                self.assertIn(flag, argv)
                self.assertIn('session', argv)
                self.assertEqual(argv[-1], '-')
        for kwargs in ({'permissions': 'unknown'}, {'budget_usd': float('nan')}, {'budget_usd': 1}):
            with self.assertRaises(ValueError):
                adapter.build_argv('codex', **kwargs)
        with self.assertRaises(ValueError):
            adapter.build_argv('unknown')

    def test_edits_permission_allows_file_edits_only(self):
        for harness, flag, value, full in (('claude', '--permission-mode', 'acceptEdits', '--dangerously-skip-permissions'),
                                           ('codex', '--sandbox', 'workspace-write',
                                            '--dangerously-bypass-approvals-and-sandbox')):
            with self.subTest(harness=harness):
                argv = adapter.build_argv(harness, permissions='edits')
                self.assertEqual(argv[argv.index(flag) + 1], value)
                self.assertNotIn(full, argv)
                inherit = adapter.build_argv(harness)
                self.assertNotIn('--permission-mode', inherit)
                self.assertNotIn('--sandbox', inherit)

    def test_claude_permission_denials_are_tool_names(self):
        denied = json.dumps({'result': 'r', 'permission_denials': [{'tool_name': 'Write'}, {'tool_name': 'Edit'}]})
        self.assertEqual(adapter.parse_result('claude', denied)['permission_denials'], ['Write', 'Edit'])
        for raw in (json.dumps({'result': 'r'}), json.dumps({'result': 'r', 'permission_denials': 'x'})):
            self.assertEqual(adapter.parse_result('claude', raw)['permission_denials'], [])
        codex = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'r'}})
        self.assertEqual(adapter.parse_result('codex', codex)['permission_denials'], [])

    def test_both_formats_preserve_report_and_errors(self):
        claude = json.dumps({'result': 'report', 'session_id': 'c', 'total_cost_usd': .1})
        codex = '\n'.join(json.dumps(e) for e in [
            {'type': 'thread.started', 'thread_id': 'x'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'report'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 7}}])
        for harness, raw in (('claude', claude), ('codex', codex)):
            out = adapter.parse_result(harness, raw)
            self.assertEqual(out['result'], 'report')
            self.assertFalse(out['is_error'])
            self.assertTrue(adapter.parse_result(harness, raw, 1)['is_error'])
            self.assertTrue(adapter.parse_result(harness, '[]')['is_error'])
        self.assertIsNone(adapter.parse_result('codex', codex)['total_cost_usd'])
        failed = codex + '\n' + json.dumps({'type': 'turn.failed', 'error': {'message': 'denied'}})
        self.assertTrue(adapter.parse_result('codex', failed)['is_error'])
        budget = adapter.parse_result('claude', json.dumps({'is_error': True, 'subtype': 'error_max_budget_usd'}))
        self.assertTrue(budget['budget_exhausted'])

    def test_hook_input_types_and_raw_shell(self):
        for payload in (None, [], 'text', {'tool_input': []}):
            self.assertEqual(adapter.normalize_hook(payload)['tool_input'], {})
        out = adapter.normalize_hook({'tool_name': 'exec_command', 'tool_input': {'cmd': 'git commit'}})
        self.assertEqual(out['tool_name'], 'Bash')
        self.assertEqual(out['tool_input']['command'], 'git commit')

    def test_patch_all_targets_block_before_early_return(self):
        with tempfile.TemporaryDirectory(prefix='patch space ') as tmp:
            project = Path(tmp)
            (project / 'run').mkdir()
            (project / 'run/r.json').write_text(json.dumps({'run_id': 'r', 'tier': 1,
                'status': 'in_progress', 'phase': 'init', 'spec_inline': 'goal'}))
            for patch in ('*** Add File: spec/ok.md\n+ok\n*** Add File: src/block.py\n+bad',
                          '*** Update File: spec/ok.md\n*** Move to: src/block.py\n@@\n-old\n+new',
                          '*** Delete File: src/block.py'):
                data = {'cwd': tmp, 'tool_name': 'apply_patch', 'tool_input': {'command': patch}}
                proc = subprocess.run([sys.executable, str(SCRIPTS / 'eval_gates.py'), '--hook'],
                    cwd=tmp, input=json.dumps(data), text=True, capture_output=True,
                    env={**os.environ, 'CLAUDE_PROJECT_DIR': tmp})
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn('BLOCK', proc.stderr)


if __name__ == '__main__':
    unittest.main()
