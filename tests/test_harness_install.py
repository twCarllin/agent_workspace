"""Exercise shared installation and compatibility paths in real Git projects."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HarnessInstallTest(unittest.TestCase):
    def run_command(self, project, *args, **kwargs):
        result = subprocess.run(args, cwd=project, capture_output=True, text=True, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self, project, *args):
        return self.run_command(project, 'bash', str(ROOT / 'init.sh'), '--target', str(project), *args)

    def test_install_matrix_and_reinstall(self):
        for harness in ('claude', 'codex', 'both'):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory(prefix='harness space ') as tmp:
                project = Path(tmp)
                self.run_command(project, 'git', 'init', '-q')
                for name in ('CLAUDE.md', 'AGENTS.md'):
                    (project / name).write_text('Project convention\n')
                self.install(project, '--harness', harness)
                first = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*')
                         if p.is_file() and '.git' not in p.parts}
                self.install(project, '--harness', harness)
                second = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*')
                          if p.is_file() and '.git' not in p.parts}
                self.assertEqual(first, second)
                for name in ('CLAUDE.md', 'AGENTS.md'):
                    self.assertIn('Project convention', (project / name).read_text())
                self.assertEqual((project / '.codex/hooks.json').exists(), harness != 'claude')
                self.assertEqual((project / '.claude/settings.json').exists(), harness != 'codex')
                core = project / '.agent-flow/scripts/eval_state.py'
                legacy = project / '.claude/hooks/eval_state.py'
                self.assertTrue(legacy.is_symlink())
                self.assertEqual(legacy.resolve(), core.resolve())
                self.run_command(project, sys.executable, str(legacy), '--help')
                self.run_command(project, sys.executable, str(core), '--help')
                self.run_command(project, sys.executable, str(project / '.agent-flow/scripts/doctor.py'),
                                 '--harness', harness)
                for side in ('claude', 'codex') if harness == 'both' else (harness,):
                    entry = project / ('CLAUDE.md' if side == 'claude' else 'AGENTS.md')
                    self.assertIn(f'harness: "{side}"', entry.read_text())
                    self.assertIn('PRACTICES.md', entry.read_text())
                    settings = json.loads((project / ('.claude/settings.json' if side == 'claude' else '.codex/hooks.json')).read_text())
                    command = settings['hooks']['SessionStart'][0]['hooks'][0]['command']
                    payload = json.dumps({'cwd': str(project)})
                    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(project)}
                    result = self.run_command(project, 'bash', '-c', command, input=payload, env=env)
                    self.assertEqual(result.stdout, '')

    def test_default_both_and_preserves_mixed_hooks_and_custom_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / '.claude/agents').mkdir(parents=True)
            custom = project / '.claude/agents/code-writer.md'
            custom.write_text('Custom role\n')
            settings = {'env': {'USER_VALUE': 'keep'}, 'hooks': {'PreToolUse': [
                {'matcher': 'Bash', 'hooks': [
                    {'type': 'command', 'command': '$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh'},
                    {'type': 'command', 'command': 'echo user hook'},
                ]}]}}
            path = project / '.claude/settings.json'
            path.write_text(json.dumps(settings))
            self.install(project)
            self.install(project)
            data = json.loads(path.read_text())
            self.assertEqual(data['env'], settings['env'])
            commands = [h['command'] for e in data['hooks']['PreToolUse'] for h in e['hooks']]
            self.assertEqual(commands.count('echo user hook'), 1)
            self.assertEqual(sum('eval_gates.py' in c for c in commands), 1)
            self.assertEqual(custom.read_text(), 'Custom role\n')
            self.assertTrue((project / '.codex/hooks.json').exists())

    def test_codex_config_preserves_custom_roles_and_uses_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / '.codex').mkdir()
            path = project / '.codex/config.toml'
            path.write_text('[agents.code-writer]\nconfig_file = "custom.toml"\n')
            self.install(project, '--p', 'codex')
            config = tomllib.loads(path.read_text())
            self.assertEqual(config['agents']['code-writer']['config_file'], 'custom.toml')
            reviewer = path.parent / config['agents']['code-reviewer']['config_file']
            self.assertTrue(reviewer.is_file())
            self.assertIn('independent', (project / 'AGENTS.md').read_text())

    def test_generated_roles_share_body_and_models(self):
        profiles = json.loads((ROOT / '.agent-flow/harnesses/models.json').read_text())
        for role, values in profiles['codex'].items():
            with self.subTest(role=role):
                common = (ROOT / '.agent-flow/roles' / f'{role}.md').read_text()
                codex = tomllib.loads((ROOT / '.codex/agents' / f'{role}.toml').read_text())
                claude = (ROOT / '.claude/agents' / f'{role}.md').read_text().split('---', 2)[2].lstrip()
                self.assertEqual(claude, common)
                self.assertTrue(codex['developer_instructions'].startswith(common))
                self.assertEqual(codex['model'], values['model'])
                self.assertEqual(codex['model_reasoning_effort'], values['reasoning_effort'])
                self.assertNotIn('model:', common)

    def test_known_legacy_claude_router_is_replaced_but_custom_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            # Use the original repository Router as the recognized upgrade input.
            legacy = (ROOT / 'tests/fixtures/legacy_claude_router.md').read_bytes()
            known = json.loads((ROOT / '.agent-flow/harnesses/legacy.json').read_text())['routers']
            self.assertIn(hashlib.sha256(legacy).hexdigest(), known)
            (project / 'CLAUDE.md').write_bytes(legacy)
            self.install(project, '--harness', 'claude')
            self.assertLess(len((project / 'CLAUDE.md').read_text()), 2000)
            self.assertIn('ROUTER.md', (project / 'CLAUDE.md').read_text())


if __name__ == '__main__':
    unittest.main()
