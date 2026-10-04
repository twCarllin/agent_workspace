"""Preview and evidence classification without starting a model session."""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agent-flow/scripts/harness_smoke.py'
spec = importlib.util.spec_from_file_location('harness_smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTest(unittest.TestCase):
    def test_normal_rejects_abort_or_modified_validation_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'run').mkdir()
            manifest = root / 'run/smoke.json'
            manifest.write_text('{"status":"in_progress","phase":"decomposed"}')
            hook = root / '.codex/hooks.json'
            hook.parent.mkdir()
            hook.write_text('{"hooks":{}}')
            gate = root / '.agent-flow/scripts/eval_gates.py'
            gate.parent.mkdir(parents=True)
            gate.write_text('original gate')
            (root / 'answer.py').write_text('value = 2\n')
            (root / 'test_answer.py').write_text('import unittest\nfrom answer import value\nclass Test(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value, 2)\n')
            (root / 'run/native-hooks.jsonl').write_text(json.dumps({'exit_code': 0,
                'payload': {'tool_name': 'apply_patch'}}) + '\n')
            before = smoke.protected_state(root)
            for path, replacement in ((manifest, '{"status":"aborted"}'),
                                      (hook, '{"hooks":{ "PreToolUse":[]}}'),
                                      (gate, 'disabled gate'),
                                      (root / 'test_answer.py', 'changed test')):
                with self.subTest(path=path):
                    old = path.read_bytes()
                    path.write_text(replacement)
                    verdict, note = smoke.check_case(root, 'normal', {'result': 'passed'}, before)
                    self.assertEqual(verdict, 'fail')
                    self.assertIn('Validation inputs', note)
                    path.write_bytes(old)
            verdict, _ = smoke.check_case(root, 'normal', {'result': 'passed'}, before)
            self.assertEqual(verdict, 'pass')
            (root / 'run/native-hooks.jsonl').write_text(json.dumps({'exit_code': 0,
                'payload': {'tool_name': 'Bash'}}) + '\n')
            verdict, _ = smoke.check_case(root, 'normal', {'result': 'passed'}, before)
            self.assertEqual(verdict, 'fail')

    def test_preview_never_calls_cli_or_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            proc = subprocess.run([sys.executable, str(SCRIPT), '--output', str(output)],
                capture_output=True, text=True, env={**os.environ, 'PATH': tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            plan = json.loads(proc.stdout)
            self.assertEqual(plan['kind'], 'preview')
            self.assertEqual(plan['calls'], 8)
            self.assertEqual(plan['models']['codex'], 'gpt-6.1-sol')
            self.assertFalse(output.exists())

    def test_missing_cli_is_blocked_and_remaining_calls_are_not_made(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            proc = subprocess.run([sys.executable, str(SCRIPT), '--live', '--harness', 'codex', '--output', str(output)],
                capture_output=True, text=True, env={**os.environ, 'PATH': tmp})
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(output.read_text())
            self.assertEqual(len(data['records']), 4)
            self.assertTrue(all(r['verdict'] == 'blocked' for r in data['records']))
            self.assertIn('not run', data['records'][1]['note'])

    def test_missing_hook_evidence_is_never_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, note = smoke.check_case(Path(tmp), 'normal', {'result': 'I passed'})
            self.assertEqual(verdict, 'blocked')
            self.assertIn('hook', note)

    def test_live_client_error_preserves_model_and_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            fake = bin_dir / 'codex'
            fake.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "fake-cli"; exit 0; fi\nprintf \'{"type":"turn.failed","error":{"message":"unsupported model"}}\\n\'\nexit 1\n')
            fake.chmod(0o755)
            old = os.environ.get('PATH', '')
            os.environ['PATH'] = str(bin_dir) + os.pathsep + old
            try:
                args = argparse.Namespace(permissions='inherit', trust_local_hooks=True,
                                          timeout=10, case_budget_usd=1.0)
                record = smoke.run_case('normal', 'codex', 'gpt-6.1-sol', args)
            finally:
                os.environ['PATH'] = old
            self.assertEqual(record['verdict'], 'blocked')
            self.assertEqual(record['model'], 'gpt-6.1-sol')
            self.assertIn('unsupported model', record['note'])


if __name__ == '__main__':
    unittest.main()
