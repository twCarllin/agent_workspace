"""The deployed Codex project must include a usable flow entry point."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FlowInstallTest(unittest.TestCase):
    def test_codex_deployment_contains_cli_and_reference(self):
        with tempfile.TemporaryDirectory(prefix='flow install ') as tmp:
            project = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            install = subprocess.run(
                [sys.executable, str(ROOT / 'install_harness.py'), '--target', tmp,
                 '--harness', 'codex'], capture_output=True, text=True)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            self.assertTrue((project / '.agent-flow/FLOW_CLI.md').is_file())
            self.assertTrue((project / '.agent-flow/scripts/flow_preflight.py').is_file())
            result = subprocess.run(
                [sys.executable, '.agent-flow/scripts/flow.py', '--help'], cwd=tmp,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for command in ('preflight', 'status', 'watch', 'finish'):
                self.assertIn(command, result.stdout)
