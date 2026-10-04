"""Actual input snapshots in real temporary Git repositories."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.agent-flow/scripts'))
import verification_snapshot
import eval_gates


class InputSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.git('init', '-q')

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(['git', *args], check=True, capture_output=True)

    def write(self, path, text='one'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)

    def snap(self):
        return verification_snapshot.input_snapshot()

    def test_docs_and_bookkeeping_excluded_but_protected_markdown_included(self):
        self.write('code.py')
        before = self.snap()
        for name in ('README.md', 'TODO.md', 'CHANGELOG.md', 'docs/deep/a.md',
                     'run/r.json', 'task/t.md', 'eval_state.json'):
            self.write(name)
        self.git('add', '.')
        self.assertEqual(before, self.snap())
        for name in ('.agent-flow/a.md', '.agents/skills/a.md', '.claude/a.md', '.codex/a.md', 'docs/a.json'):
            before = self.snap()
            self.write(name)
            self.assertNotEqual(before, self.snap(), name)

    def test_content_mode_name_and_symlink_are_inputs(self):
        self.write('code.py')
        before = self.snap()
        self.write('code.py', 'two')
        self.assertNotEqual(before, self.snap())
        before = self.snap()
        os.chmod('code.py', 0o755)
        self.assertNotEqual(before, self.snap())
        before = self.snap()
        os.rename('code.py', 'other.py')
        self.assertNotEqual(before, self.snap())
        before = self.snap()
        os.symlink('other.py', 'README.md')
        self.assertNotEqual(before, self.snap())
        before = self.snap()
        os.unlink('README.md')
        os.symlink('missing', 'README.md')
        self.assertNotEqual(before, self.snap())

    def test_head_index_and_ignored_outputs_do_not_change_actual_inputs(self):
        self.write('.gitignore', 'output\n')
        self.write('code.py')
        before = self.snap()
        self.git('add', '.')
        self.assertEqual(before, self.snap())
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'initial')
        self.assertEqual(before, self.snap())
        self.write('output')
        self.assertEqual(before, self.snap())
        os.unlink('code.py')
        deleted = self.snap()
        self.assertNotEqual(before, deleted)
        self.git('add', '-u')
        self.assertEqual(deleted, self.snap())

    def test_gate_dispatches_legacy_new_and_rejects_unknown_kind(self):
        self.write('code.py')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'initial')
        for kind in (None, 'inputs-v1'):
            record = {'exit_code': 0, 'snapshot': verification_snapshot.snapshot() if kind is None else self.snap()}
            if kind:
                record['snapshot_kind'] = kind
            manifest = {'evidence_schema': 2, 'tier': 1, 'verification_commands': [record]}
            eval_gates._validate_evidence_snapshot(manifest, 'test')
        manifest['verification_commands'][0]['snapshot_kind'] = 'unknown'
        with self.assertRaises(SystemExit):
            eval_gates._validate_evidence_snapshot(manifest, 'test')
        manifest['verification_commands'][0]['snapshot_kind'] = 'inputs-v1'
        self.write('code.py', 'changed')
        with self.assertRaises(SystemExit):
            eval_gates._validate_evidence_snapshot(manifest, 'test')

    def test_external_symlink_fails_closed(self):
        os.symlink('/etc/hosts', 'README.md')
        with self.assertRaises(OSError):
            self.snap()
