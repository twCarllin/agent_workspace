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
        run_cli("init", "--run-id", "r1")
        state = self.read_state()
        self.assertEqual(state["run_id"], "r1")
        self.assertEqual(state["sub_tasks"], [])
        self.assertNotIn("threshold", state)

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
        run_cli("set-review", "1", "1")
        run_cli("set-verify", "1")
        run_cli("set-status", "1", "passed")
        run_cli("archive")
        self.assertFalse(os.path.exists("eval_state.json"))
        with open("run/2026-07-15-demo.eval.json", encoding="utf-8") as f:
            archived = json.load(f)
        self.assertEqual(archived["run_id"], "2026-07-15-demo")

    def test_add_subtask_default_review_verify_fields(self):
        self.bootstrap()
        st = self.read_state()["sub_tasks"][0]
        self.assertIsNone(st["review_reds"])
        self.assertFalse(st["verify_passed"])

    def test_set_review_writes_reds(self):
        self.bootstrap()
        run_cli("set-review", "1", "3")
        self.assertEqual(self.read_state()["sub_tasks"][0]["review_reds"], 3)

    def test_set_review_negative_exits(self):
        self.bootstrap()
        with self.assertRaises(SystemExit):
            run_cli("set-review", "1", "-1")

    def test_set_verify_sets_true(self):
        self.bootstrap()
        run_cli("set-verify", "1")
        self.assertTrue(self.read_state()["sub_tasks"][0]["verify_passed"])

    def test_archive_blocks_missing_review_verify(self):
        # sub_task passed but review_reds/verify_passed not set → archive should exit 2
        self.bootstrap()
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        run_cli("set-status", "1", "passed")
        with self.assertRaises(SystemExit) as ctx:
            run_cli("archive")
        self.assertEqual(ctx.exception.code, 2)
        self.assertTrue(os.path.exists("eval_state.json"))

    def test_unknown_subtask_id_fails(self):
        self.bootstrap()
        with self.assertRaises(SystemExit):
            run_cli("set-step", "99", "writing")

    # set-review --dimensions 案例
    def test_set_review_with_valid_dimensions(self):
        self.bootstrap()
        run_cli("set-review", "1", "2", "--dimensions", '{"Clarity":1,"Completeness":1}')
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["review_reds"], 2)
        self.assertEqual(st["review_dimensions"], {"Clarity": 1, "Completeness": 1})

    def test_set_review_invalid_dimension_key_exits(self):
        self.bootstrap()
        with self.assertRaises(SystemExit) as ctx:
            run_cli("set-review", "1", "1", "--dimensions", '{"InvalidKey":1}')
        self.assertEqual(ctx.exception.code, 2)
        # 不落盤
        self.assertIsNone(self.read_state()["sub_tasks"][0]["review_dimensions"])

    def test_set_review_negative_dimension_value_exits(self):
        self.bootstrap()
        with self.assertRaises(SystemExit) as ctx:
            run_cli("set-review", "1", "1", "--dimensions", '{"Clarity":-1}')
        self.assertEqual(ctx.exception.code, 2)
        # 不落盤
        self.assertIsNone(self.read_state()["sub_tasks"][0]["review_dimensions"])

    def test_set_review_bad_json_dimensions_exits(self):
        self.bootstrap()
        with self.assertRaises(SystemExit) as ctx:
            run_cli("set-review", "1", "1", "--dimensions", '{not valid json}')
        self.assertEqual(ctx.exception.code, 2)
        # 不落盤
        self.assertIsNone(self.read_state()["sub_tasks"][0]["review_dimensions"])

    # --- add-verification（純記錄欄位，不被任何 gate 消費）---

    def test_add_subtask_skeleton_has_empty_verification_commands(self):
        self.bootstrap()
        self.assertEqual(self.read_state()["sub_tasks"][0]["verification_commands"], [])

    def test_add_verification_appends_in_order(self):
        self.bootstrap()
        run_cli("add-verification", "1", "--command", "pytest -q", "--exit-code", "0")
        run_cli("add-verification", "1", "--command", "ruff check .", "--exit-code", "1")
        vc = self.read_state()["sub_tasks"][0]["verification_commands"]
        self.assertEqual(vc, [
            {"command": "pytest -q", "exit_code": 0},
            {"command": "ruff check .", "exit_code": 1},
        ])

    def test_add_verification_accepts_negative_exit_code(self):
        self.bootstrap()
        run_cli("add-verification", "1", "--command", "killed", "--exit-code", "-9")
        vc = self.read_state()["sub_tasks"][0]["verification_commands"]
        self.assertEqual(vc[0]["exit_code"], -9)

    def test_add_verification_unknown_id_exits(self):
        self.bootstrap()
        with self.assertRaises(SystemExit) as ctx:
            run_cli("add-verification", "99", "--command", "pytest", "--exit-code", "0")
        self.assertEqual(ctx.exception.code, 1)

    def test_add_verification_rejects_blank_command(self):
        self.bootstrap()
        with self.assertRaises(SystemExit) as ctx:
            run_cli("add-verification", "1", "--command", "   ", "--exit-code", "0")
        self.assertEqual(ctx.exception.code, 1)
        # 不落盤
        self.assertEqual(self.read_state()["sub_tasks"][0]["verification_commands"], [])

    def test_add_verification_backward_compat_missing_key(self):
        """本欄位為後加的可選欄位：舊 eval_state.json 的 sub_task 無此鍵時不可 KeyError。"""
        self.bootstrap()
        state = self.read_state()
        del state["sub_tasks"][0]["verification_commands"]
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        self.assertNotIn("verification_commands", self.read_state()["sub_tasks"][0])

        run_cli("add-verification", "1", "--command", "pytest -q", "--exit-code", "0")
        vc = self.read_state()["sub_tasks"][0]["verification_commands"]
        self.assertEqual(vc, [{"command": "pytest -q", "exit_code": 0}])


if __name__ == "__main__":
    unittest.main()
