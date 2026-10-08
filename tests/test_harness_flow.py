"""Same flow contract through installed scripts and Git hooks on both sides."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skill_eval', ROOT / '.agent-flow/scripts/skill_eval.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HarnessFlowTest(unittest.TestCase):
    def test_block_failure_repair_verify_commit_and_resume_matrix(self):
        for harness in ('claude', 'codex'):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
                root = Path(runner.build_fixture(str(ROOT / 'evals/tier1-routing'), tmp, harness))
                env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(root), 'AGENT_FLOW_HARNESS': harness}
                scripts = root / '.agent-flow/scripts'
                def call(*args, **kwargs):
                    return subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, **kwargs)
                manifest = root / 'run/flow.json'
                manifest.parent.mkdir(exist_ok=True)
                initialized = call(sys.executable, str(scripts / 'eval_state.py'), 'init-run',
                    '--run-id', 'flow', '--harness', harness, '--spec-inline', 'change answer to 2',
                    '--tier-rationale', 'bounded fixture', '--test-command', 'python3 -m unittest test_answer',
                    '--task-file', 'task/flow.md')
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                data = json.loads(manifest.read_text())
                payload = {'cwd': str(root), 'tool_name': 'apply_patch' if harness == 'codex' else 'Write',
                           'tool_input': {'command': '*** Add File: answer.py\n+value = 2', 'file_path': 'answer.py'}}
                blocked = call(sys.executable, str(scripts / 'eval_gates.py'), '--hook', input=json.dumps(payload))
                self.assertEqual(blocked.returncode, 2, blocked.stderr)
                data.update(phase='decomposed', hitl_confirmed_at='confirmed fixture plan')
                manifest.write_text(json.dumps(data))
                self.assertEqual(call(sys.executable, str(scripts / 'eval_gates.py'), '--hook', input=json.dumps(payload)).returncode, 0)
                (root / 'answer.py').write_text('value = 1\n')
                (root / 'test_answer.py').write_text('import unittest\nfrom answer import value\nclass AnswerTest(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value, 2)\n')
                command = 'python3 -m unittest test_answer'
                result = call(sys.executable, str(scripts / 'run_verify.py'), '--run-id', 'flow', '--cmd', command)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(call(sys.executable, str(scripts / 'run_commit.py'), 'prepare', 'flow').returncode, 2)
                self.assertEqual(call(sys.executable, str(scripts / 'run_commit.py'), 'finalize', 'flow').returncode, 2)
                events_path = root / 'run/flow.events.jsonl'
                self.assertNotIn('completed', [json.loads(line)['cmd'] for line in events_path.read_text().splitlines()])
                (root / 'answer.py').write_text('value = 2\n# repaired to the accepted contract\n')
                data = json.loads(manifest.read_text())
                reviewed = call(sys.executable, str(scripts / 'eval_state.py'), 'review-run', 'flow', '0',
                    '--checked-by', 'reviewer:manual', '--evidence', 'independent fixture review', '--passed')
                self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
                self.assertEqual(call('git', 'add', 'answer.py', 'test_answer.py').returncode, 0)
                result = call(sys.executable, str(scripts / 'run_verify.py'), '--run-id', 'flow', '--cmd', command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(call(sys.executable, str(scripts / 'run_commit.py'), 'prepare', 'flow').returncode, 0)
                commit = call('git', 'commit', '-qm', 'answer 2\n\nRun-Id: flow')
                self.assertEqual(commit.returncode, 0, commit.stderr)
                self.assertEqual(call(sys.executable, str(scripts / 'run_commit.py'), 'finalize', 'flow').returncode, 0)
                final = json.loads(manifest.read_text())
                self.assertEqual(final['status'], 'completed')
                event = json.loads(events_path.read_text().splitlines()[-1])
                self.assertEqual(event['cmd'], 'completed')
                self.assertEqual(event['args'], {'run_id': 'flow', 'commit_sha': final['commit_sha'],
                                                'completed_at': final['completed_at']})
            with self.subTest(harness=harness, scenario='resume'), tempfile.TemporaryDirectory() as tmp:
                root = Path(runner.build_fixture(str(ROOT / 'evals/resume-interrupted'), tmp, harness))
                state_before = json.loads((root / 'eval_state.json').read_text())
                proc = subprocess.run([sys.executable, str(root / '.agent-flow/scripts/session_start.py')],
                    cwd=root, input=json.dumps({'cwd': str(root)}), text=True, capture_output=True,
                    env={**os.environ, 'AGENT_FLOW_HARNESS': harness, 'CLAUDE_PROJECT_DIR': str(root)})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn('2026-10-01-greeting-module', proc.stdout)
                self.assertEqual(json.loads((root / 'eval_state.json').read_text())['sub_tasks'][0], state_before['sub_tasks'][0])
                self.assertEqual(state_before['sub_tasks'][1]['step'], 'reviewing')


if __name__ == '__main__':
    unittest.main()
