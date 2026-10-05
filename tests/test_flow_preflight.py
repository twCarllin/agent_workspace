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

    def test_nested_repository_is_reported_before_verification(self):
        git = shutil.which('git', path=self.old_path)
        (self.root / 'bin/git').symlink_to(git)
        subprocess.run([git, 'init', '-q'], check=True, capture_output=True)
        (self.root / 'agent_workspace').mkdir()
        subprocess.run([git, '-C', 'agent_workspace', 'init', '-q'], check=True, capture_output=True)
        (self.root / 'agent_workspace/code.py').write_text('one')
        result = flow_preflight.preflight()
        nested = self.check(result, 'nested_repositories')
        self.assertEqual(nested['status'], 'failed')
        self.assertIn('agent_workspace', nested['detail'])
        self.assertIn('approval', nested['detail'])
        self.assertEqual(result['readiness'], 'blocked')
        (self.root / '.git/info/exclude').write_text('agent_workspace/\n')
        self.assertEqual(self.check(flow_preflight.preflight(), 'nested_repositories')['status'], 'ok')
        self.assertTrue((self.root / 'agent_workspace/code.py').exists())

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

    def claude_cli(self, behavior='ok'):
        path = self.root / 'bin/claude'
        path.write_text('#!' + sys.executable + '\n' +
                        'import sys,time,json\n' +
                        'args=sys.argv[1:]\n' +
                        "print('SECRET_MUST_NOT_APPEAR',file=sys.stderr)\n" +
                        ('time.sleep(3)\n' if behavior == 'timeout' else '') +
                        ('sys.exit(1)\n' if behavior == 'fail' else '') +
                        "if args[0]=='--version':\n print(" + repr('weird' if behavior == 'format' else '2.1.0 (Claude Code)') + ")\n" +
                        "elif args[0]=='auth':\n print(" + ("'not json SECRET_MUST_NOT_APPEAR'" if behavior == 'badjson' else
                            "json.dumps({'loggedIn':" + ('False' if behavior == 'logged_out' else 'True') + ",'email':'SECRET_MUST_NOT_APPEAR'})") + ")\n" +
                        "else:\n print(json.dumps({'result':'FLOW_PREFLIGHT_OK','session_id':'s','is_error':False}))\n")
        path.chmod(0o755)

    def test_claude_version_auth_and_live_probe(self):
        self.claude_cli()
        result = flow_preflight.preflight(harness='claude', live=True)
        self.assertEqual(self.check(result, 'version')['detail'], '2.1.0 (Claude Code)')
        self.assertEqual(self.check(result, 'auth')['status'], 'ok')
        self.assertEqual(self.check(result, 'live_probe')['status'], 'ok')
        self.assertEqual(self.check(result, 'hook_trust')['status'], 'unknown')
        self.assertEqual(result['readiness'], 'unknown')
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', json.dumps(result))

    def test_claude_without_live_never_calls_prompt_mode(self):
        self.claude_cli()
        marker = self.root / 'bin/claude'
        marker.write_text(marker.read_text().replace("else:\n print(", "else:\n open('PROMPT_EXECUTED','w').close()\n print("))
        result = flow_preflight.preflight(harness='claude')
        self.assertFalse((self.root / 'PROMPT_EXECUTED').exists())
        self.assertNotIn('live_probe', [c['name'] for c in result['checks']])

    def test_claude_failures_block_and_hide_output(self):
        for behavior, version, auth in (('timeout', 'failed', 'failed'), ('fail', 'failed', 'failed'),
                                        ('logged_out', 'ok', 'failed'), ('badjson', 'ok', 'failed'), ('format', 'unknown', 'ok')):
            with self.subTest(behavior=behavior):
                self.claude_cli(behavior)
                result = flow_preflight.preflight(harness='claude', timeout=0.03 if behavior == 'timeout' else 30, live=True)
                self.assertEqual(self.check(result, 'version')['status'], version)
                self.assertEqual(self.check(result, 'auth')['status'], auth)
                self.assertEqual(self.check(result, 'live_probe')['status'], 'ok' if auth == 'ok' else 'failed')
                self.assertEqual(result['readiness'], 'unknown' if auth == 'ok' else 'blocked')
                self.assertNotIn('SECRET_MUST_NOT_APPEAR', json.dumps(result))

    def test_unknown_exit_and_invalid_timeout(self):
        process = subprocess.run([sys.executable, str(SCRIPTS / 'flow_preflight.py')], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(json.loads(process.stdout)['readiness'], 'unknown')
        for timeout in (0, -1, float('nan'), float('inf'), True, 301):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                flow_preflight.preflight(timeout=timeout)


if __name__ == '__main__':
    unittest.main()
