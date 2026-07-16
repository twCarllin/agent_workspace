"""eval_state.py helper 的操作與驗證測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（helper 以 cwd 的 eval_state.json 為對象）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_state  # noqa: E402


def run_cli(*argv):
    with mock.patch.object(sys, "argv", ["eval_state.py", *argv]):
        eval_state.main()


class EvalStateHelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def read_state(self):
        with open("eval_state.json", encoding="utf-8") as f:
            return json.load(f)

    def bootstrap(self):
        run_cli("init", "--run-id", "2026-07-15-demo")
        run_cli("add-subtask", "--id", "1", "--name", "demo")

    def test_init_creates_state(self):
        run_cli("init", "--run-id", "r1", "--threshold", "7")
        state = self.read_state()
        self.assertEqual(state["run_id"], "r1")
        self.assertEqual(state["threshold"], 7)
        self.assertEqual(state["sub_tasks"], [])

    def test_init_refuses_overwrite(self):
        run_cli("init", "--run-id", "r1")
        with self.assertRaises(SystemExit):
            run_cli("init", "--run-id", "r2")

    def test_set_step_and_files(self):
        self.bootstrap()
        run_cli("set-step", "1", "writing")
        run_cli("set-files", "1", "src/a.py", "src/b.py", "src/a.py")
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["step"], "writing")
        self.assertEqual(st["files"], ["src/a.py", "src/b.py"])  # 去重保序

    def test_set_test_passed_requires_evidence(self):
        self.bootstrap()
        with self.assertRaises(SystemExit):
            run_cli("set-test", "1", "--passed")
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        st = self.read_state()["sub_tasks"][0]
        self.assertTrue(st["local_test_passed"])

    def test_append_round_validates_invariant(self):
        self.bootstrap()
        bad = json.dumps({"round": 1, "quality_score": 8, "deduction_reasons": []})
        with self.assertRaises(SystemExit):
            run_cli("append-round", "1", "--json", bad)
        self.assertEqual(self.read_state()["sub_tasks"][0]["rounds"], [])  # 未落盤
        good = json.dumps({
            "round": 1, "quality_score": 9,
            "deduction_reasons": [
                {"points_lost": 1, "dimension": "Clarity", "reason": "r", "evidence": "a:1"}
            ],
        })
        run_cli("append-round", "1", "--json", good)
        self.assertEqual(len(self.read_state()["sub_tasks"][0]["rounds"]), 1)

    def test_list_files_unions_across_subtasks(self):
        self.bootstrap()
        run_cli("add-subtask", "--id", "2", "--name", "demo2")
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-files", "2", "src/b.py", "src/a.py")
        import io
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            run_cli("list-files")
        self.assertEqual(buf.getvalue().split(), ["src/a.py", "src/b.py"])

    def test_archive_blocks_unpassed_subtask(self):
        self.bootstrap()
        with self.assertRaises(SystemExit):
            run_cli("archive")
        self.assertTrue(os.path.exists("eval_state.json"))  # 不落盤、不清除

    def test_archive_writes_and_clears(self):
        self.bootstrap()
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        good = json.dumps({"round": 1, "quality_score": 10, "deduction_reasons": []})
        run_cli("append-round", "1", "--json", good)
        run_cli("set-status", "1", "passed")
        run_cli("archive")
        self.assertFalse(os.path.exists("eval_state.json"))
        with open("run/2026-07-15-demo.eval.json", encoding="utf-8") as f:
            archived = json.load(f)
        self.assertNotIn("status", archived)

    def test_unknown_subtask_id_fails(self):
        self.bootstrap()
        with self.assertRaises(SystemExit):
            run_cli("set-step", "99", "writing")


if __name__ == "__main__":
    unittest.main()
