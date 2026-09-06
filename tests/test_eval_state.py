"""eval_state.py helper 的操作與驗證測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（helper 以 cwd 的 eval_state.json 為對象）。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_state  # noqa: E402
import eval_gates  # noqa: E402


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

    def test_set_review_checked_by_writes_value(self):
        self.bootstrap()
        run_cli("set-review", "1", "0", "--checked-by", "checker")
        self.assertEqual(self.read_state()["sub_tasks"][0]["checked_by"], "checker")

    def test_set_review_without_checked_by_keeps_null(self):
        self.bootstrap()
        run_cli("set-review", "1", "0")
        self.assertIsNone(self.read_state()["sub_tasks"][0]["checked_by"])

    def test_set_review_invalid_checked_by_exits_and_leaves_file(self):
        self.bootstrap()
        before = self.read_state()
        captured = io.StringIO()
        with mock.patch("sys.stderr", captured):
            with self.assertRaises(SystemExit) as ctx:
                run_cli("set-review", "1", "0", "--checked-by", "reviewer:⑥")
        self.assertEqual(ctx.exception.code, 2)  # 契約：exit 非 0
        self.assertIn("checker", captured.getvalue())  # 契約：stderr 含合法值清單（寬鬆存在性）
        self.assertEqual(self.read_state(), before)  # 檔案不變

    def test_archive_carries_checked_by(self):
        self.bootstrap()
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        run_cli("set-review", "1", "1", "--checked-by", "reviewer:④")
        run_cli("set-verify", "1")
        run_cli("set-status", "1", "passed")
        run_cli("archive")
        with open("run/2026-07-15-demo.eval.json", encoding="utf-8") as f:
            archived = json.load(f)
        self.assertEqual(archived["sub_tasks"][0]["checked_by"], "reviewer:④")

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


# --- 2a：events.jsonl append（旁路記錄，不得影響主命令 exit code）---

class EventAppendTest(unittest.TestCase):
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

    def read_events(self, run_id):
        with open(os.path.join("run", f"{run_id}.events.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_write_subcommand_appends_event(self):
        run_cli("init", "--run-id", "r1")
        events = self.read_events("r1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cmd"], "init")
        self.assertIn("ts", events[0])
        self.assertEqual(events[0]["args"]["run_id"], "r1")
        self.assertNotIn("func", events[0]["args"])
        self.assertNotIn("command", events[0]["args"])

    def test_multiple_write_subcommands_append_in_order(self):
        run_cli("init", "--run-id", "r2")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        run_cli("set-step", "1", "writing")
        events = self.read_events("r2")
        self.assertEqual([e["cmd"] for e in events], ["init", "add-subtask", "set-step"])

    def test_list_files_does_not_append(self):
        run_cli("init", "--run-id", "r3")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        run_cli("set-files", "1", "a.py")
        before = len(self.read_events("r3"))
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            run_cli("list-files")
        after = len(self.read_events("r3"))
        self.assertEqual(before, after)  # 唯讀命令不 append

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 略過檔案權限測試")
    def test_events_dir_unwritable_main_command_still_succeeds(self):
        """events 目錄不可寫（無法新建檔案）→ 主命令仍成功，僅 stderr warning（風險技術#1）。"""
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump({"run_id": "r4", "sub_tasks": []}, f)
        os.makedirs("run", exist_ok=True)
        os.chmod("run", 0o500)  # 可進入目錄、不可新建檔案
        try:
            stderr_buf = io.StringIO()
            with mock.patch.object(sys, "stderr", stderr_buf):
                run_cli("add-subtask", "--id", "1", "--name", "demo")
        finally:
            os.chmod("run", 0o700)
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["name"], "demo")  # 主命令成功寫入
        self.assertIn("事件記錄寫入失敗", stderr_buf.getvalue())
        self.assertFalse(os.path.exists(os.path.join("run", "r4.events.jsonl")))

    def test_missing_run_id_skips_append_with_warning(self):
        """eval_state.json 缺 run_id（如舊檔）→ 略過事件記錄，僅 warning，不影響主命令（D-err2）。"""
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump({"sub_tasks": []}, f)  # 無 run_id 鍵
        stderr_buf = io.StringIO()
        with mock.patch.object(sys, "stderr", stderr_buf):
            run_cli("add-subtask", "--id", "1", "--name", "demo")
        self.assertIn("run_id 缺失", stderr_buf.getvalue())
        self.assertEqual(self.read_state()["sub_tasks"][0]["name"], "demo")  # 主命令仍成功
        self.assertFalse(os.path.isdir("run"))  # 未產生任何 events 檔

    def test_arg_value_over_200_chars_truncated(self):
        run_cli("init", "--run-id", "r5")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        long_val = "x" * 250
        run_cli("set-test", "1", "--passed", "--evidence", long_val)
        events = self.read_events("r5")
        self.assertEqual(events[-1]["args"]["evidence"], "x" * 200 + "…[truncated]")

    def test_arg_value_exactly_200_chars_not_truncated(self):
        """[邊界] 恰 200 字元（非 >200）不截斷——DoD 的門檻是「>200」，200 本身合法。"""
        run_cli("init", "--run-id", "r7")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        exact_val = "y" * 200
        run_cli("set-test", "1", "--passed", "--evidence", exact_val)
        events = self.read_events("r7")
        self.assertEqual(events[-1]["args"]["evidence"], exact_val)

    def test_arg_value_with_special_characters_not_mangled(self):
        """含特殊字元：中文／引號／emoji 的 arg 值原樣寫入 events.jsonl（json.dumps ensure_ascii=False）。"""
        run_cli("init", "--run-id", "r8")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        special_val = '含「引號」與換行\n特殊字元 🎉'
        run_cli("set-test", "1", "--passed", "--evidence", special_val)
        events = self.read_events("r8")
        self.assertEqual(events[-1]["args"]["evidence"], special_val)

    def test_events_file_name_not_matched_by_manifest_re(self):
        """新衍生檔命名前置檢查（retro 約束）：.events.jsonl 不可被誤判為 run manifest——
        `.jsonl` 副檔名不匹配 `MANIFEST_RE` 的 `\\.json$` 錨定。"""
        run_cli("init", "--run-id", "r6")
        events_path = os.path.join("run", "r6.events.jsonl")
        self.assertTrue(os.path.exists(events_path))
        self.assertIsNone(eval_gates.MANIFEST_RE.match(events_path))


class Tier01TelemetryTest(unittest.TestCase):
    """event（Tier 1 事件留痕）與 tier0（Tier 0 一行留痕）子命令。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def read_events(self, run_id):
        with open(os.path.join("run", f"{run_id}.events.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def read_tier0(self):
        with open(os.path.join("run", "tier0.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_event_without_state_file_succeeds(self):
        """Tier 1 場景：eval_state.json 不存在也能寫事件（不經 load()）。"""
        self.assertFalse(os.path.exists("eval_state.json"))
        run_cli("event", "t1-run", "hitl_confirmed", "--note", "1 task／4 items")
        events = self.read_events("t1-run")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cmd"], "hitl_confirmed")
        self.assertIn("ts", events[0])
        self.assertEqual(events[0]["args"]["note"], "1 task／4 items")

    def test_event_appends_in_order(self):
        run_cli("event", "t1-run", "init_done")
        run_cli("event", "t1-run", "item_reviewed")
        self.assertEqual([e["cmd"] for e in self.read_events("t1-run")],
                         ["init_done", "item_reviewed"])

    def test_tier0_appends_entry_with_four_keys(self):
        run_cli("tier0", "--summary", "文案微調", "--files", "a.py, b.md", "--lines", "12")
        entries = self.read_tier0()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(set(e), {"ts", "summary", "files", "lines"})
        self.assertEqual(e["summary"], "文案微調")
        self.assertEqual(e["files"], ["a.py", "b.md"])
        self.assertEqual(e["lines"], 12)

    def test_tier0_is_append_only(self):
        run_cli("tier0", "--summary", "第一筆", "--files", "a.py", "--lines", "1")
        run_cli("tier0", "--summary", "第二筆", "--files", "b.py", "--lines", "2")
        self.assertEqual([e["summary"] for e in self.read_tier0()], ["第一筆", "第二筆"])

    def test_tier0_rejects_blank_summary(self):
        with self.assertRaises(SystemExit):
            run_cli("tier0", "--summary", "  ", "--files", "a.py", "--lines", "1")


if __name__ == "__main__":
    unittest.main()
