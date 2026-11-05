"""memory_prune.py 真實子程序回歸：三類候選、apply 只搬結案記錄並同步索引、無目錄靜默。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agent-flow" / "scripts" / "memory_prune.py"
HOOK = ROOT / ".claude" / "hooks" / "session_start.py"
sys.path.insert(0, str(SCRIPT.parent))
import memory_prune  # noqa: E402


def write(path, text, age_days=0):
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))


class MemoryPruneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "memory"
        self.dir.mkdir()
        self.env = dict(os.environ, CLAUDE_MEMORY_DIR=str(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
            env=env or self.env, cwd=self.tmp.name,
        )

    def seed(self):
        write(self.dir / "MEMORY.md",
              "# Index\n- [old](old-run.md) — done\n- [veto](veto.md) — x\n- [fresh](fresh.md) — y\n")
        write(self.dir / "old-run.md", "---\nname: old-run\nmetadata:\n  type: project\n---\n10/14 run 進度\n", age_days=45)
        write(self.dir / "fresh.md", "---\nname: fresh\nmetadata:\n  type: project\n---\n進行中\n", age_days=3)
        write(self.dir / "veto.md", "---\nname: veto\nmetadata:\n  type: reference\n---\n加 prompt 規則效果不穩\n", age_days=60)

    def test_slug_matches_claude_code_layout(self):
        saved = os.environ.pop("CLAUDE_MEMORY_DIR", None)
        try:
            path = memory_prune.memory_dir("/Users/x/work/TW_Analysis")
        finally:
            if saved is not None:
                os.environ["CLAUDE_MEMORY_DIR"] = saved
        self.assertEqual(path.parts[-3:], ("projects", "-Users-x-work-TW-Analysis", "memory"))

    def test_dry_run_lists_three_kinds_and_apply_moves_only_stale(self):
        self.seed()
        write(self.dir / "MEMORY.md", (self.dir / "MEMORY.md").read_text() + "x" * 5000)
        listed = self.run_cli()
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("[index] MEMORY.md", listed.stdout)
        self.assertIn("[stale] old-run.md", listed.stdout)
        self.assertIn("[veto] veto.md", listed.stdout)
        self.assertNotIn("fresh.md", listed.stdout)
        self.assertTrue((self.dir / "old-run.md").exists())
        bare = self.run_cli("--apply")
        self.assertEqual(bare.returncode, 0)
        self.assertTrue((self.dir / "old-run.md").exists())
        self.assertIn("須指名", bare.stdout)
        unknown = self.run_cli("--apply", "fresh.md")
        self.assertEqual(unknown.returncode, 2)
        self.assertTrue((self.dir / "fresh.md").exists())
        applied = self.run_cli("--apply", "old-run.md", "veto.md")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue((self.dir / "_archive" / "old-run.md").exists())
        self.assertFalse((self.dir / "old-run.md").exists())
        self.assertTrue((self.dir / "_archive" / "veto.md").exists())
        index = (self.dir / "MEMORY.md").read_text()
        self.assertNotIn("(old-run.md)", index)
        self.assertNotIn("(veto.md)", index)
        self.assertIn("(fresh.md)", index)

    def test_notice_and_missing_dir_are_quiet(self):
        self.assertEqual(self.run_cli("--notice").stdout, "")
        self.assertEqual(self.run_cli().stdout.strip(), "[memory-prune] 無候選")
        self.seed()
        notice = self.run_cli("--notice")
        self.assertEqual(notice.returncode, 0)
        self.assertIn("記憶可整理 2 項", notice.stdout)
        missing = self.run_cli(env=dict(self.env, CLAUDE_MEMORY_DIR=str(self.dir / "nope")))
        self.assertEqual((missing.returncode, missing.stdout), (0, ""))

    def test_session_start_hook_appends_notice_only_when_candidates(self):
        project = Path(self.tmp.name) / "proj"
        (project / "run").mkdir(parents=True)
        payload = json.dumps({"cwd": str(project), "hook_event_name": "SessionStart"})
        self.env["HOME"] = self.tmp.name  # 隔離真實 ~/.claude，doctor 行不干擾

        def hook():
            return subprocess.run(
                [sys.executable, str(HOOK)], input=payload, capture_output=True,
                text=True, cwd=project, env=self.env, timeout=60,
            )

        before = hook()
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertNotIn("記憶可整理", before.stdout)
        self.seed()
        after = hook()
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn("記憶可整理 2 項", after.stdout)
        self.assertLessEqual(len(after.stdout.splitlines()), 10)


if __name__ == "__main__":
    unittest.main()
