"""Exercise Flow CLI in isolated Git repositories using real verification and commits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / '.agent-flow/scripts/flow.py'


class FlowCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Flow Test')
        (self.repo / '.gitignore').write_text('run/\neval_state.json\n')
        (self.repo / 'code.py').write_text('value = 1\n')
        self.git('add', '.gitignore', 'code.py')
        self.git('commit', '-qm', 'initial')
        (self.repo / 'run').mkdir()
        self.manifest = dict(run_id='r1', tier=1, harness='codex', evidence_schema=2,
                             status='in_progress', phase='reviewing', spec_inline='task',
                             test_command='python3 -c pass', local_test_passed=True,
                             local_test_evidence='test command passed', review_reds=0,
                             verify_passed=True)
        self.save()
        (self.repo / 'code.py').write_text('value = 2\n')
        self.git('add', 'code.py')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True).strip()

    def save(self, manifest=None):
        data = manifest or self.manifest
        (self.repo / 'run' / (data['run_id'] + '.json')).write_text(json.dumps(data))

    def cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], cwd=self.repo,
                              text=True, capture_output=True)

    def finish(self, *extra):
        return self.cli('finish', '--run-id', 'r1', '--message', 'Complete work',
                        '--files', 'code.py', *extra)

    def read_manifest(self):
        return json.loads((self.repo / 'run/r1.json').read_text())

    def test_finish_real_verify_prepare_commit_finalize(self):
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = self.read_manifest()
        self.assertEqual(manifest['status'], 'completed')
        self.assertEqual(manifest['commit_sha'], self.git('rev-parse', 'HEAD'))
        self.assertEqual(manifest['verification_commands'][-1]['exit_code'], 0)
        self.assertIn('Run-Id: r1', self.git('log', '-1', '--format=%B'))
        sha = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.finish().returncode, 0)
        self.assertEqual(sha, self.git('rev-parse', 'HEAD'))

    def test_missing_review_rejects_before_verify(self):
        self.manifest['verify_passed'] = False
        self.save()
        before = self.git('rev-parse', 'HEAD')
        result = self.finish()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertNotIn('verification_commands', self.read_manifest())

    def test_verification_failure_keeps_original_output(self):
        before = self.git('rev-parse', 'HEAD')
        result = self.finish('--verify-command', "python3 -c 'print(\"specific-failure\"); raise SystemExit(7)'")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('specific-failure', result.stdout + result.stderr)
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertNotEqual(self.read_manifest()['status'], 'completed')

    def test_extra_staged_paths_rejected(self):
        (self.repo / 'other.py').write_text('other = 1\n')
        self.git('add', 'other.py')
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn('extra=', result.stderr)

    def test_unstaged_scope_change_rejected(self):
        (self.repo / 'code.py').write_text('value = 3\n')
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn('working files differ', result.stderr)

    def test_other_hot_run_rejected_without_archive(self):
        hot = self.repo / 'eval_state.json'
        hot.write_text(json.dumps(dict(run_id='other', sub_tasks=[])))
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn('run_id mismatch', result.stderr)
        self.assertTrue(hot.exists())
        self.assertNotIn('verification_commands', self.read_manifest())

    def test_tier2_archives_only_matching_passed_state(self):
        self.manifest['tier'] = 2
        self.save()
        task = dict(id=1, name='task', status='passed', step='done',
                    local_test_passed=True, local_test_evidence='tests passed',
                    review_reds=0, verify_passed=True)
        hot = self.repo / 'eval_state.json'
        hot.write_text(json.dumps(dict(run_id='r1', sub_tasks=[task])))
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(hot.exists())
        archive = json.loads((self.repo / 'run/r1.eval.json').read_text())
        self.assertEqual(archive['run_id'], 'r1')
        self.assertEqual(self.read_manifest()['status'], 'completed')

    def test_tier2_failed_task_stops_before_verification(self):
        self.manifest['tier'] = 2
        self.save()
        (self.repo / 'eval_state.json').write_text(json.dumps(dict(run_id='r1', sub_tasks=[dict(id=1, status='failed')])))
        result = self.finish()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('verification_commands', self.read_manifest())
        self.assertTrue((self.repo / 'eval_state.json').exists())

    def test_invalid_tier2_task_shapes_refuse_before_verification(self):
        self.manifest['tier'] = 2
        self.save()
        before = self.git('rev-parse', 'HEAD')
        malformed = [dict(run_id='r1'), dict(run_id='r1', sub_tasks=[]),
                     dict(run_id='r1', sub_tasks=None), dict(run_id='r1', sub_tasks={}),
                     dict(run_id='r1', sub_tasks='bad'), dict(run_id='r1', sub_tasks=[None]),
                     dict(run_id='r1', sub_tasks=[1])]
        for location in ('eval_state.json', 'run/r1.eval.json'):
            for state in malformed:
                with self.subTest(location=location, state=state):
                    record = self.repo / location
                    original = json.dumps(state)
                    record.write_text(original)
                    result = self.finish()
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('sub_tasks must be a nonempty list', result.stderr)
                    self.assertNotIn('verification_commands', self.read_manifest())
                    self.assertEqual(before, self.git('rev-parse', 'HEAD'))
                    self.assertEqual(record.read_text(), original)
                    self.assertNotEqual(self.read_manifest()['status'], 'completed')
                    record.unlink()

    def test_atomic_lock_rejected(self):
        lock = self.repo / '.git/flow-finish.lock'
        lock.write_text('another process')
        self.assertEqual(self.finish().returncode, 2)
        self.assertEqual(lock.read_text(), 'another process')

    def test_resume_finalize_does_not_commit_again(self):
        self.assertEqual(self.finish().returncode, 0)
        manifest = self.read_manifest()
        manifest['status'] = 'ready_to_commit'
        manifest.pop('commit_sha')
        self.save(manifest)
        before = self.git('rev-parse', 'HEAD')
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.read_manifest()['status'], 'completed')

    def test_initial_commit_finish(self):
        # New repository with staged code and no HEAD exercises prepare's null parent.
        subprocess.run(['git', 'update-ref', '-d', 'HEAD'], cwd=self.repo, check=True)
        result = self.finish('--files', '.gitignore', 'code.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self.read_manifest()['pre_commit_head'])

    def test_status_excludes_other_run_state(self):
        (self.repo / 'eval_state.json').write_text(json.dumps(dict(run_id='other', sub_tasks=[dict(id=99)])))
        result = self.cli('status', '--run-id', 'r1', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['tasks'], [])

    def test_ambiguous_auto_selection_rejected(self):
        self.save(dict(self.manifest, run_id='r2'))
        self.assertEqual(self.cli('status').returncode, 2)
        self.assertEqual(self.cli('status', '--run-id', 'r1').returncode, 0)

    def test_watch_is_bounded_emits_only_changes(self):
        result = self.cli('watch', '--run-id', 'r1', '--json', '--timeout', '0.12', '--interval', '0.05')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(self.cli('watch', '--timeout', '999999').returncode, 2)

    def test_completed_watch_exits_immediately(self):
        self.manifest['status'] = 'completed'
        self.save()
        result = self.cli('watch', '--run-id', 'r1', '--json', '--timeout', '10')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_real_commit_msg_hook_failure_keeps_run_unfinished(self):
        hook = self.repo / '.git/hooks/commit-msg'
        hook.write_text('#!/bin/sh\necho hook-rejected >&2\nexit 1\n')
        hook.chmod(0o755)
        before = self.git('rev-parse', 'HEAD')
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn('hook-rejected', result.stderr)
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.read_manifest()['status'], 'ready_to_commit')
        hook.unlink()
        self.assertEqual(self.finish().returncode, 0)
        self.assertNotIn('finish_error', self.read_manifest())

    def test_status_reports_existing_failed_reason_and_dispatch(self):
        self.manifest['failed_reason'] = 'known failure'
        self.save()
        (self.repo / 'run/r1.dispatch.jsonl').write_text(json.dumps(dict(role='writer', exit_code=9)) + '\n')
        value = json.loads(self.cli('status', '--run-id', 'r1', '--json').stdout)
        self.assertEqual(value['error_reason'], 'known failure')
        self.assertEqual(value['last_dispatch']['exit_code'], 9)

    def test_untracked_scope_files_cannot_be_committed(self):
        (self.repo / 'new.py').write_text('new = 1\n')
        result = self.finish('--files', 'code.py', 'new.py')
        self.assertEqual(result.returncode, 2)
        self.assertIn('missing=', result.stderr)

    def test_crash_recovery_rejects_wrong_commit_parent(self):
        self.assertEqual(self.finish().returncode, 0)
        manifest = self.read_manifest()
        manifest.update(status='ready_to_commit', pre_commit_head='bad-parent')
        self.save(manifest)
        before = self.git('rev-parse', 'HEAD')
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))


if __name__ == '__main__':
    unittest.main()
