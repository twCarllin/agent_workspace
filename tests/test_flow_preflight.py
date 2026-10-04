"""Isolated project fixtures exercise readiness and real bounded child probes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agent-flow/scripts'
sys.path.insert(0, str(SCRIPTS))
import flow_preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_cwd = Path.cwd()
        self.old_path = os.environ.get('PATH', '')
        os.chdir(self.root)
        (self.root / '.agents').mkdir()
        (self.root / '.agents/skills').symlink_to(ROOT / 'skills', target_is_directory=True)
        shutil.copytree(ROOT / '.codex', self.root / '.codex')
        shutil.copytree(ROOT / '.claude', self.root / '.claude')
        (self.root / 'retro').mkdir()
        (self.root / 'retro/RETRO.md').write_text('seed')
        (self.root / 'AGENTS.md').write_text('flow')
        (self.root / 'tests').mkdir()
        (self.root / 'bin').mkdir()
        (self.root / 'bin/python3').symlink_to(sys.executable)
        os.environ['PATH'] = str(self.root / 'bin')
        self.cli()

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ['PATH'] = self.old_path
        self.temp.cleanup()

    def cli(self, behavior='ok'):
        path = self.root / 'bin/codex'
        path.write_text('#!' + sys.executable + '\n' +
                        'import sys,time,json\n' +
                        'args=sys.argv[1:]\n' +
                        "print('SECRET_MUST_NOT_APPEAR',file=sys.stderr)\n" +
                        ('time.sleep(3)\n' if behavior == 'timeout' else '') +
                        ('sys.exit(1)\n' if behavior == 'fail' else '') +
                        "if args[0]=='exec':\n print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'FLOW_PREFLIGHT_OK'}}))\nelse:\n print('codex 1.0')\n")
        path.chmod(0o755)

    def check(self, result, name):
        return next(c for c in result['checks'] if c['name'] == name)

    def test_static_unknown_trust_is_never_ready_and_output_redacted(self):
        result = flow_preflight.preflight()
        self.assertEqual(result['readiness'], 'unknown')
        self.assertFalse(result['ready'])
        for name in ('deployment', 'hook_config', 'models', 'workspace', 'test_command', 'cli', 'version', 'auth'):
            self.assertEqual(self.check(result, name)['status'], 'ok', result)
        self.assertEqual(self.check(result, 'hook_trust')['status'], 'unknown')
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', json.dumps(result))

    def test_live_probe_verifies_response_but_not_hook_trust(self):
        result = flow_preflight.preflight(live=True)
        self.assertEqual(self.check(result, 'live_probe')['status'], 'ok')
        self.assertEqual(result['readiness'], 'unknown')

    def test_missing_cli_blocks_and_cli_exit_is_nonzero(self):
        (self.root / 'bin/codex').unlink()
        result = flow_preflight.preflight()
        self.assertEqual(result['readiness'], 'blocked')
        process = subprocess.run([sys.executable, str(SCRIPTS / 'flow_preflight.py')], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(json.loads(process.stdout)['readiness'], 'blocked')

    def test_timeout_and_failed_login_block(self):
        for behavior in ('timeout', 'fail'):
            with self.subTest(behavior=behavior):
                self.cli(behavior)
                result = flow_preflight.preflight(timeout=0.03, live=True)
                self.assertEqual(result['readiness'], 'blocked')
                self.assertEqual(self.check(result, 'auth')['status'], 'failed')
                self.assertEqual(self.check(result, 'live_probe')['status'], 'failed')
                self.assertNotIn('SECRET_MUST_NOT_APPEAR', json.dumps(result))

    def test_malformed_config_and_model_mismatch_block(self):
        config = self.root / '.codex/config.toml'
        original = config.read_text()
        for malformed in ('[agents', 'agents = []', original.replace('gpt-6.1-sol', 'wrong-model')):
            with self.subTest(value=malformed):
                config.write_text(malformed)
                result = flow_preflight.preflight()
                self.assertEqual(result['readiness'], 'blocked')
                self.assertEqual(self.check(result, 'models')['status'], 'failed')
        config.write_text(original)
        (self.root / '.codex/agents/code-writer.toml').write_text('model="wrong"')
        self.assertEqual(self.check(flow_preflight.preflight(), 'models')['status'], 'failed')

    def test_invalid_hooks_are_reported_separately_from_trust(self):
        hook_path = self.root / '.codex/hooks.json'
        for value in ([], None, {'hooks': []}, {'hooks': {'PreToolUse': []}}):
            with self.subTest(value=value):
                hook_path.write_text(json.dumps(value))
                result = flow_preflight.preflight()
                self.assertEqual(result['readiness'], 'blocked')
                self.assertEqual(self.check(result, 'hook_config')['status'], 'failed')
                self.assertEqual(self.check(result, 'hook_trust')['status'], 'unknown')

    def test_manifest_shapes_missing_executable_and_command_not_executed(self):
        (self.root / 'run').mkdir()
        manifest = self.root / 'run/probe.json'
        for value in ([], None, {'test_command': 'missing-executable'}, {'test_command': '"broken'},
                      {'test_command': 'python3 missing.py'},
                      {'test_command': 'python3 -m unittest discover -s missing-directory'}):
            with self.subTest(value=value):
                manifest.write_text(json.dumps(value))
                result = flow_preflight.preflight(run_id='probe')
                self.assertEqual(result['readiness'], 'blocked')
        manifest.write_text(json.dumps({'test_command': 'python3 -c "open(\'SHOULD_NOT_EXIST\',\'w\')"'}))
        self.assertEqual(self.check(flow_preflight.preflight(run_id='probe'), 'test_command')['status'], 'ok')
        self.assertFalse((self.root / 'SHOULD_NOT_EXIST').exists())
        result = flow_preflight.preflight(run_id='../escape')
        self.assertEqual(self.check(result, 'test_command')['status'], 'failed')

    def test_claude_cli_never_runs_even_with_live_requested(self):
        marker = self.root / 'CLAUDE_EXECUTED'
        cli = self.root / 'bin/claude'
        cli.write_text('#!' + sys.executable + '\nopen(' + repr(str(marker)) + ', "w").close()\n')
        cli.chmod(0o755)
        result = flow_preflight.preflight(harness='claude', live=True)
        self.assertEqual(self.check(result, 'version')['status'], 'unknown')
        self.assertEqual(self.check(result, 'auth')['status'], 'unknown')
        self.assertEqual(self.check(result, 'live_probe')['status'], 'unknown')
        self.assertFalse(marker.exists())

    def test_unknown_exit_and_invalid_timeout(self):
        process = subprocess.run([sys.executable, str(SCRIPTS / 'flow_preflight.py')], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(json.loads(process.stdout)['readiness'], 'unknown')
        for timeout in (0, -1, float('nan'), float('inf'), True, 301):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                flow_preflight.preflight(timeout=timeout)


if __name__ == '__main__':
    unittest.main()
