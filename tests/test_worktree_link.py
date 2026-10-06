"""worktree_link.ensure_links 契約：在真實 git worktree 內補建指回主工作區的相對 symlink。

所有操作在 TemporaryDirectory 的拋棄式 repo 內，絕不觸碰真實 repo。
執行：python3 -m unittest tests.test_worktree_link
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".agent-flow" / "scripts"))
import harness_install_transaction as tx  # noqa: E402
import worktree_link  # noqa: E402

SCRIPT = ROOT / ".agent-flow" / "scripts" / "worktree_link.py"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class EnsureLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.main = base / "main"
        self.main.mkdir()
        git(self.main, "init", "-q")
        git(self.main, "config", "user.email", "t@t.com")
        git(self.main, "config", "user.name", "T")
        (self.main / ".gitkeep").write_text("")
        git(self.main, "add", ".gitkeep")
        git(self.main, "commit", "-q", "-m", "init")
        # 主工作區的工具鏈（未追蹤）
        (self.main / ".agent-flow" / "scripts").mkdir(parents=True)
        (self.main / ".agent-flow" / "scripts" / "x.py").write_text("x = 1\n")
        (self.main / ".agents" / "skills" / "s").mkdir(parents=True)
        (self.main / ".agents" / "skills" / "s" / "SKILL.md").write_text("# s\n")
        (self.main / ".claude").mkdir()
        (self.main / ".claude" / "settings.json").write_text("{}\n")
        (self.main / ".codex").mkdir()
        (self.main / ".codex" / "config.toml").write_text("model = 'm'\n")
        (self.main / "retro").mkdir()
        (self.main / "retro" / "RETRO.md").write_text("# retro\n")
        (self.main / "run").mkdir()
        (self.main / "run" / "r.json").write_text("{}\n")
        (self.main / "task").mkdir()
        (self.main / "task" / "t.md").write_text("# t\n")
        self.worktree = base / "wt"
        git(self.main, "worktree", "add", "--detach", "-q", str(self.worktree))

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_missing_toolchain_with_relative_symlinks(self):
        created = worktree_link.ensure_links(self.worktree)
        self.assertIn(".agent-flow", created)
        link = self.worktree / ".agent-flow"
        self.assertTrue(link.is_symlink())
        self.assertFalse(os.path.isabs(os.readlink(link)))
        self.assertEqual(link.resolve(), (self.main / ".agent-flow").resolve())
        self.assertEqual((link / "scripts" / "x.py").read_text(), "x = 1\n")
        self.assertIn(".agents/skills", created)
        self.assertTrue((self.worktree / ".agents" / "skills").is_symlink())

    def test_file_paths_get_real_parent_and_file_symlink(self):
        worktree_link.ensure_links(self.worktree)
        self.assertTrue((self.worktree / "retro").is_dir())
        self.assertFalse((self.worktree / "retro").is_symlink())
        self.assertTrue((self.worktree / "retro" / "RETRO.md").is_symlink())
        self.assertTrue((self.worktree / ".claude" / "settings.json").is_symlink())
        self.assertEqual((self.worktree / ".claude" / "settings.json").read_text(), "{}\n")

    def test_existing_path_is_left_alone_and_not_reported(self):
        (self.worktree / ".codex").mkdir()
        (self.worktree / ".codex" / "config.toml").write_text("model = 'mine'\n")
        created = worktree_link.ensure_links(self.worktree)
        self.assertNotIn(".codex/config.toml", created)
        self.assertFalse((self.worktree / ".codex" / "config.toml").is_symlink())
        self.assertEqual((self.worktree / ".codex" / "config.toml").read_text(), "model = 'mine'\n")

    def test_paths_missing_in_main_are_not_created(self):
        created = worktree_link.ensure_links(self.worktree)
        for name in ("AGENTS.md", "CLAUDE.local.md", ".codex/hooks.json", "retro/BUGLOG.md"):
            self.assertNotIn(name, created)
            self.assertFalse((self.worktree / name).exists() or (self.worktree / name).is_symlink())

    def test_run_and_task_are_never_shared(self):
        self.assertNotIn("run", worktree_link.LINK_ROOTS)
        self.assertNotIn("task", worktree_link.LINK_ROOTS)
        worktree_link.ensure_links(self.worktree)
        self.assertFalse((self.worktree / "run").exists())
        self.assertFalse((self.worktree / "task").exists())

    def test_main_checkout_and_non_git_dir_return_empty(self):
        self.assertEqual(worktree_link.ensure_links(self.main), [])
        self.assertFalse((self.main / ".agent-flow").is_symlink())
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        self.assertEqual(worktree_link.ensure_links(plain), [])
        self.assertEqual(list(plain.iterdir()), [])

    def test_second_call_creates_nothing(self):
        self.assertTrue(worktree_link.ensure_links(self.worktree))
        self.assertEqual(worktree_link.ensure_links(self.worktree), [])

    def test_cli_prints_created_then_nothing(self):
        first = subprocess.run([sys.executable, str(SCRIPT), str(self.worktree)],
                               capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("已為 worktree 建立工具鏈連結", first.stdout)
        self.assertIn(".agent-flow", first.stdout)
        second = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.worktree,
                                capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "無需建立連結")


class LinkRootsLockTest(unittest.TestCase):
    def test_link_roots_match_installer_roots_plus_local_claude_md(self):
        self.assertEqual(set(worktree_link.LINK_ROOTS), set(tx.ROOTS) | {"CLAUDE.local.md"})


if __name__ == "__main__":
    unittest.main()
