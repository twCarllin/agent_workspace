"""Installer preview, drift and rollback contracts in temporary projects."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import harness_install_transaction as tx
import install_harness as installer


class TransactionTest(unittest.TestCase):
    def test_absolute_internal_symlink_plan_never_writes_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            scripts = target / '.agent-flow/scripts'
            scripts.mkdir(parents=True)
            victim = target / 'victim.py'
            victim.write_text('USER DATA\n')
            (scripts / 'dispatch.py').symlink_to(victim)
            before = tx.snapshot(target)
            with self.assertRaisesRegex(ValueError, 'absolute symlink'):
                tx.build_plan(target, 'codex', installer.populate, source=ROOT)
            self.assertEqual(victim.read_text(), 'USER DATA\n')
            self.assertEqual(tx.snapshot(target), before)
            result = subprocess.run([sys.executable, str(ROOT / 'install_harness.py'),
                '--target', tmp, '--harness', 'codex', '--dry-run'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(victim.read_text(), 'USER DATA\n')
            self.assertEqual(tx.snapshot(target), before)

    def test_codex_registration_preserves_top_level_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / '.codex').mkdir()
            path = target / '.codex/config.toml'
            original = {'model': 'project-model', 'sandbox_mode': 'read-only',
                        'approval_policy': 'never'}
            path.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key, value in original.items()) + '\n[projects."/project"]\ntrust_level = "trusted"\n')
            installer.register_codex_agents(target)
            data = tomllib.loads(path.read_text())
            for key, value in original.items():
                self.assertEqual(data[key], value)
                self.assertNotIn(key, data['agents'])
            self.assertEqual(data['projects']['/project']['trust_level'], 'trusted')
            self.assertEqual(data['agents']['default_subagent_model'], 'gpt-6.1-sol')

    def test_preview_does_not_create_target(self):
        with tempfile.TemporaryDirectory(prefix='preview space ') as tmp:
            target = Path(tmp) / 'new project'
            result = subprocess.run([sys.executable, str(ROOT / 'install_harness.py'),
                '--target', str(target), '--dry-run'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('create:', result.stdout)
            self.assertFalse(target.exists())

    def test_managed_drift_blocks_without_writing_and_user_sections_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            def install():
                return subprocess.run([sys.executable, str(ROOT / 'install_harness.py'),
                    '--target', tmp], capture_output=True, text=True)
            self.assertEqual(install().returncode, 0)
            (target / 'AGENTS.md').write_text('My project rule\n' + (target / 'AGENTS.md').read_text())
            settings = target / '.codex/hooks.json'
            data = json.loads(settings.read_text())
            data['hooks']['PreToolUse'].append({'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'echo my hook'}]})
            settings.write_text(json.dumps(data))
            self.assertEqual(install().returncode, 0)
            path = target / '.agent-flow/scripts/dispatch.py'
            path.write_text(path.read_text() + '\n# project edit\n')
            before = tx.snapshot(target)
            result = install()
            self.assertEqual(result.returncode, 1)
            self.assertIn('conflict:', result.stdout)
            self.assertEqual(tx.snapshot(target), before)
            self.assertIn('My project rule', (target / 'AGENTS.md').read_text())
            self.assertIn('echo my hook', settings.read_text())

    def test_failure_restores_files_links_modes_removed_skill_and_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / '.agents/skills/obsolete').mkdir(parents=True)
            marker = target / '.agents/skills/obsolete/.agent-workspace-managed'
            marker.write_text('managed')
            old = target / '.agents/skills/obsolete/SKILL.md'
            old.write_text('old skill')
            old.chmod(0o600)
            owned = {str(p.relative_to(target)): tx.managed_hash(str(p.relative_to(target)),
                     ('file', p.read_bytes(), p.stat().st_mode & 0o777)) for p in (marker, old)}
            (target / '.agent-flow').mkdir()
            (target / tx.OWNERSHIP).write_text(json.dumps({'schema': 1, 'files': owned}))
            before = tx.snapshot(target)
            hook = target / 'commit-msg'
            hook.write_text('original hook')
            hook.chmod(0o755)
            plan = tx.build_plan(target, 'both', installer.populate, source=ROOT)
            calls = []
            def faulty(path, state):
                calls.append(path)
                tx.replace_state(path, state)
                if len(calls) == 8:
                    raise OSError('injected failure after write')
            with self.assertRaises(OSError):
                tx.apply_plan(plan, writer=faulty)
            self.assertEqual(tx.snapshot(target), before)
            def finalize():
                hook.write_text('changed hook')
                raise OSError('hook write failed')
            with self.assertRaises(OSError):
                tx.apply_plan(plan, finalize=finalize,
                    external={hook: ('file', hook.read_bytes(), 0o755)})
            self.assertEqual(tx.snapshot(target), before)
            self.assertEqual(hook.read_text(), 'original hook')
            self.assertEqual(old.stat().st_mode & 0o777, 0o600)

    def test_external_symlink_refused_without_external_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target, outside = base / 'project', base / 'outside'
            target.mkdir(); outside.mkdir()
            (target / '.codex').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                tx.build_plan(target, 'codex', installer.populate, source=ROOT)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
