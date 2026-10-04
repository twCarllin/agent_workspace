"""Review checkpoints use real Git index trees, never imply approval."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('review_delta', Path(__file__).resolve().parents[1] / '.agent-flow/scripts/review_delta.py')
delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta)


class DeltaTest(unittest.TestCase):
    def test_reviewed_delta_and_fail_closed_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                def git(*args):
                    return subprocess.run(['git', *args], check=True, capture_output=True)
                git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@local')
                Path('a.py').write_text('value = 1\n')
                Path('contract.md').write_text('return 2\n')
                git('add', '.'); git('commit', '-qm', 'initial')
                Path('a.py').write_text('value = 2\n'); git('add', 'a.py')
                checkpoint = Path('run/checkpoint.json')
                delta.capture(checkpoint, ['a.py'], ['contract.md'])
                self.assertEqual(delta.diff(checkpoint, ['a.py'], ['contract.md'])[0], 'full')
                delta.mark_reviewed(checkpoint, 'independent-session')
                self.assertEqual(delta.diff(checkpoint, ['a.py'], ['contract.md']), ('delta', ''))
                Path('a.py').write_text('value = 3\n'); git('add', 'a.py')
                mode, diff = delta.diff(checkpoint, ['a.py'], ['contract.md'])
                self.assertEqual(mode, 'delta'); self.assertIn('-value = 2', diff); self.assertIn('+value = 3', diff)
                with self.assertRaises(ValueError):
                    delta.mark_reviewed(checkpoint, 'late-session')
                Path('contract.md').write_text('return 3\n')
                self.assertEqual(delta.diff(checkpoint, ['a.py'], ['contract.md'])[0], 'full')
                for invalid in ('{bad', '[]', 'null'):
                    checkpoint.write_text(invalid)
                    self.assertEqual(delta.diff(checkpoint, ['a.py'], ['contract.md'])[0], 'full')
                checkpoint.unlink()
                self.assertEqual(delta.diff(checkpoint, ['a.py'], ['contract.md'])[0], 'full')
                with self.assertRaises(ValueError):
                    delta.diff(checkpoint, ['../outside'], ['contract.md'])
            finally:
                os.chdir(old)
