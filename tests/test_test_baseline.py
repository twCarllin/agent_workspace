"""test_baseline.py 的端到端測試：在暫存目錄以假測試指令驗證
baseline 建立、flaky 過濾、新失敗攔截、strike 計數、manifest test_command 回退、related 對映。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "test_baseline.py"

# test_a 永遠失敗（既有壞測試）；test_b 每隔一次失敗（flaky，靠計數檔 n）
CMD_STABLE_PLUS_FLAKY = (
    'n=$(cat n 2>/dev/null || echo 0); n=$((n+1)); echo $n > n; '
    'echo "FAILED tests/test_broken.py::test_a"; '
    '[ $((n % 2)) -eq 1 ] && echo "FAILED tests/test_flaky.py::test_b"; exit 1'
)
CMD_NEW_FAILURE = (
    'echo "FAILED tests/test_broken.py::test_a"; '
    'echo "FAILED tests/test_new.py::test_c"; exit 1'
)
# test_d 只在第一次呼叫失敗（新出現的 flaky，靠計數檔 m）
CMD_NEW_FLAKY = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; '
    'echo "FAILED tests/test_broken.py::test_a"; '
    '[ $m -eq 1 ] && echo "FAILED tests/test_d.py::test_d"; exit 1'
)


class BaselineScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.dir, capture_output=True, text=True,
        )

    def read_baseline(self):
        return json.loads((self.dir / "run" / "t.test_baseline.json").read_text(encoding="utf-8"))

    def build_baseline(self):
        result = self.run_script("baseline", "--cmd", CMD_STABLE_PLUS_FLAKY)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read_baseline()

    def test_baseline_splits_stable_and_flaky(self):
        data = self.build_baseline()
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertEqual(data["flaky"], ["tests/test_flaky.py::test_b"])

    def test_check_passes_when_only_known_failures(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_STABLE_PLUS_FLAKY, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_check_blocks_new_stable_failure_and_counts_strikes(self):
        self.build_baseline()
        first = self.run_script("check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1")
        self.assertEqual(first.returncode, 2)
        self.assertIn("tests/test_new.py::test_c", first.stderr)
        self.assertIn("第 1 次", first.stderr)

        second = self.run_script("check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1")
        self.assertEqual(second.returncode, 2)
        self.assertIn("第 2 次", second.stderr)
        self.assertIn("2 次上限", second.stderr)
        self.assertEqual(self.read_baseline()["strikes"]["s1"], 2)

    def test_new_flaky_failure_passes_and_is_recorded(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_NEW_FLAKY, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.read_baseline()
        self.assertIn("tests/test_d.py::test_d", data["flaky"])
        self.assertEqual(data["strikes"]["s1"], 0)

    def test_pass_resets_strike_counter(self):
        self.build_baseline()
        self.run_script("check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1")
        self.assertEqual(self.read_baseline()["strikes"]["s1"], 1)
        self.run_script("check", "--cmd", CMD_STABLE_PLUS_FLAKY, "--strike-key", "s1")
        self.assertEqual(self.read_baseline()["strikes"]["s1"], 0)

    def test_check_without_baseline_fails_with_instruction(self):
        result = self.run_script("check", "--cmd", "exit 0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("先跑 baseline", result.stderr)

    def test_cmd_falls_back_to_manifest_test_command(self):
        (self.dir / "run").mkdir()
        (self.dir / "run" / "t.json").write_text(
            json.dumps({"run_id": "t", "test_command": "exit 0"}), encoding="utf-8"
        )
        result = self.run_script("baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_baseline()["cmd"], "exit 0")
        check = self.run_script("check")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_missing_cmd_and_manifest_field_errors(self):
        result = self.run_script("baseline")
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_command", result.stderr)

    def init_git(self):
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "x"],
            cwd=self.dir, check=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.dir,
            capture_output=True, text=True,
        ).stdout.strip()

    def write_prev_baseline(self, head_sha, cmd):
        (self.dir / "run").mkdir(exist_ok=True)
        (self.dir / "run" / "prev.test_baseline.json").write_text(
            json.dumps({
                "run_id": "prev", "cmd": cmd, "head_sha": head_sha,
                "stable_failures": ["tests/test_old.py::test_z"],
                "flaky": [], "strikes": {"s9": 1},
            }), encoding="utf-8",
        )

    # 沿用側效檔：baseline 若真的執行測試指令會留下 ran 檔
    CMD_TOUCH = 'touch ran; exit 0'

    def test_baseline_reuses_same_head_and_cmd(self):
        head = self.init_git()
        self.write_prev_baseline(head, self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("沿用 prev", result.stdout)
        self.assertFalse((self.dir / "ran").exists())  # 沒有真的跑測試
        data = self.read_baseline()
        self.assertEqual(data["reused_from"], "prev")
        self.assertEqual(data["stable_failures"], ["tests/test_old.py::test_z"])
        self.assertEqual(data["strikes"], {})  # strikes 不沿用，歸零重計

    def test_baseline_no_reuse_when_head_differs(self):
        self.init_git()
        self.write_prev_baseline("deadbeef", self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())  # 真的重跑了
        self.assertNotIn("reused_from", self.read_baseline())

    def test_baseline_no_reuse_when_cmd_differs(self):
        head = self.init_git()
        self.write_prev_baseline(head, "exit 0")
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())
        self.assertNotIn("reused_from", self.read_baseline())

    def test_fresh_flag_forces_rebuild(self):
        head = self.init_git()
        self.write_prev_baseline(head, self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH, "--fresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())
        self.assertNotIn("reused_from", self.read_baseline())

    def test_related_maps_by_name_and_content(self):
        (self.dir / "src").mkdir()
        (self.dir / "tests").mkdir()
        (self.dir / "src" / "foo.py").write_text("def foo(): pass\n", encoding="utf-8")
        (self.dir / "tests" / "test_foo.py").write_text("from src.foo import foo\n", encoding="utf-8")
        (self.dir / "tests" / "test_service.py").write_text("import src.foo\n", encoding="utf-8")
        (self.dir / "tests" / "test_unrelated.py").write_text("def test_x(): pass\n", encoding="utf-8")
        result = self.run_script("related", "--files", "src/foo.py")
        paths = set(result.stdout.split())
        self.assertIn("tests/test_foo.py", paths)
        self.assertIn("tests/test_service.py", paths)
        self.assertNotIn("tests/test_unrelated.py", paths)


if __name__ == "__main__":
    unittest.main()
