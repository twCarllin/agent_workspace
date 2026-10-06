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
sys.path.insert(0, str(ROOT))
import install_harness as installer  # noqa: E402


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
                # No harness rewrites the project's own CLAUDE.md; the Claude section lives in CLAUDE.local.md.
                self.assertEqual((project / 'CLAUDE.md').read_text(), 'Project convention\n')
                exclude = (project / '.git/info/exclude').read_text()
                self.assertEqual(exclude.count(installer.EXCLUDE_START), 1)
                self.assertEqual(exclude.count(installer.EXCLUDE_END), 1)
                for entry in installer.EXCLUDE_PATHS:
                    self.assertIn(f'\n{entry}\n', exclude)
                status = self.run_command(project, 'git', 'status', '--porcelain').stdout
                for entry in installer.EXCLUDE_PATHS:
                    self.assertNotIn(entry.strip('/'), status)
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
                    entry = project / ('CLAUDE.local.md' if side == 'claude' else 'AGENTS.md')
                    self.assertIn(f'harness: "{side}"', entry.read_text())
                    self.assertIn('PRACTICES.md', entry.read_text())
                    settings = json.loads((project / ('.claude/settings.json' if side == 'claude' else '.codex/hooks.json')).read_text())
                    command = settings['hooks']['SessionStart'][0]['hooks'][0]['command']
                    payload = json.dumps({'cwd': str(project)})
                    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(project)}
                    result = self.run_command(project, 'bash', '-c', command, input=payload, env=env)
                    self.assertEqual(result.stdout, '')

    def test_exclude_keeps_user_lines_updates_stale_block_and_skips_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.run_command(project, 'git', 'init', '-q')
            exclude = project / '.git/info/exclude'
            stale = f'my.log\n{installer.EXCLUDE_START}\nold-entry/\n{installer.EXCLUDE_END}\ntrailing.tmp\n'
            exclude.write_text(stale)
            self.install(project, '--harness', 'claude', '--dry-run')
            self.assertEqual(exclude.read_text(), stale)
            self.install(project, '--harness', 'claude')
            text = exclude.read_text()
            self.assertTrue(text.startswith('my.log\n'))
            self.assertTrue(text.endswith(f'{installer.EXCLUDE_END}\ntrailing.tmp\n'))
            self.assertNotIn('old-entry/', text)
            self.assertEqual(text.count(installer.EXCLUDE_START), 1)
            self.assertIn('\n/.agent-flow\n', text)
            self.install(project, '--harness', 'claude')
            self.assertEqual(exclude.read_text(), text)
            self.install(project, '--git-hook-only')
            self.assertEqual(exclude.read_text(), text)
            # Anchored entries ignore only root toolchain paths; a nested run/ stays visible.
            (project / 'src/run').mkdir(parents=True)
            (project / 'src/run/app.py').write_text('x = 1\n')
            status = self.run_command(project, 'git', 'status', '--porcelain', '-uall').stdout
            self.assertIn('src/run/app.py', status)

    def test_linked_worktree_stays_clean(self):
        """Worktree toolchain paths are symlinks; the exclude block must ignore them too."""
        sys.path.insert(0, str(ROOT / '.agent-flow/scripts'))
        import worktree_link
        with tempfile.TemporaryDirectory() as tmp:
            project, worktree = Path(tmp) / 'proj', Path(tmp) / 'wt'
            project.mkdir()
            self.run_command(project, 'git', 'init', '-q')
            self.run_command(project, 'git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                             'commit', '-q', '--allow-empty', '-m', 'init')
            self.install(project, '--harness', 'both')
            self.run_command(project, 'git', 'worktree', 'add', '-q', '--detach', str(worktree))
            self.assertIn('.agent-flow', worktree_link.ensure_links(worktree))
            status = lambda root: self.run_command(root, 'git', 'status', '--porcelain').stdout
            # Links add nothing untracked beyond what the main checkout already shows (AGENTS.md for Codex).
            self.assertEqual(status(worktree), status(project))
            self.assertNotIn('.agent-flow', status(worktree))

    def test_git_hook_only_does_not_write_exclude(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.run_command(project, 'git', 'init', '-q')
            exclude = project / '.git/info/exclude'
            before = exclude.read_bytes()
            self.install(project, '--git-hook-only')
            self.assertEqual(exclude.read_bytes(), before)
            self.assertTrue((project / '.git/hooks/commit-msg').exists())

    def test_claude_section_moves_out_of_claude_md_and_merges_into_local(self):
        marker = '<!-- agent-workspace claude instructions -->'
        end_marker = '<!-- /agent-workspace claude instructions -->'
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / 'CLAUDE.md').write_text(f'Custom rule\n\n{marker}\nold section\n{end_marker}\n\nTail rule\n')
            (project / 'CLAUDE.local.md').write_text('Personal note\n')
            self.install(project, '--harness', 'claude')
            self.assertEqual((project / 'CLAUDE.md').read_text(), 'Custom rule\n\nTail rule\n')
            local = (project / 'CLAUDE.local.md').read_text()
            self.assertTrue(local.startswith('Personal note\n'))
            self.assertEqual(local.count(marker), 1)
            self.assertIn('harness: "claude"', local)
            self.install(project, '--harness', 'claude')
            self.assertEqual((project / 'CLAUDE.local.md').read_text(), local)
            self.assertEqual((project / 'CLAUDE.md').read_text(), 'Custom rule\n\nTail rule\n')
            self.assertFalse((project / '.git').exists())

    def test_repo_mode_keeps_claude_md_and_skips_exclude(self):
        self.assertIsNone(installer.exclude_target(installer.SOURCE))
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.run_command(project, 'git', 'init', '-q')
            self.assertEqual(installer.exclude_target(project), project / '.git/info/exclude')
            installer.instructions(project, 'claude', repo_mode=True)
            self.assertIn('harness: "claude"', (project / 'CLAUDE.md').read_text())
            self.assertFalse((project / 'CLAUDE.local.md').exists())
            installer.instructions(project, 'claude', repo_mode=False)
            self.assertEqual((project / 'CLAUDE.md').read_text(), '')
            self.assertIn('harness: "claude"', (project / 'CLAUDE.local.md').read_text())

    def test_failed_finalize_restores_exclude_and_hook(self):
        sys.path.insert(0, str(ROOT))
        import harness_install_transaction as tx
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.run_command(project, 'git', 'init', '-q')
            exclude = project / '.git/info/exclude'
            exclude.write_text('user.log\n')
            hook = installer.git_hook_path(project)
            plan = tx.build_plan(project, 'claude', installer.populate, source=ROOT)
            finalize, external = installer.git_side_effects(project, hook, exclude)
            self.assertEqual(external[exclude], ('file', b'user.log\n', exclude.stat().st_mode & 0o777))
            self.assertIsNone(external[hook])

            def failing():
                finalize()
                self.assertIn(installer.EXCLUDE_START, exclude.read_text())
                raise OSError('injected failure after git writes')
            with self.assertRaises(OSError):
                tx.apply_plan(plan, finalize=failing, external=external)
            self.assertEqual(exclude.read_text(), 'user.log\n')
            self.assertFalse(hook.exists())
            self.assertFalse((project / '.agent-flow').exists())

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
