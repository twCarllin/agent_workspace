"""eval_state.py helper 的操作與驗證測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（helper 以 cwd 的 eval_state.json 為對象）。
"""
import contextlib
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

    # --- per-task 改構（Q2／Q9／Q10，2026-09-22）---

    def test_add_subtask_skeleton_key_set_is_exact(self):
        """R-004 加嚴：skeleton 是寫出留痕欄位的函式，逐鍵斷言完整鍵集而非只驗存在性。

        Q10 裁示 `eval_state` 不存 item 層資料（item 的 DoD／契約表 single source
        ＝task 檔），故鍵集**不得**含 `items`；Q8 裁示 `risk_analysis` 移除，亦不得出現。
        鍵集寫死是刻意的——新增欄位會使本測試紅，強制改動者回來確認該欄位真的該進 skeleton。
        """
        self.bootstrap()
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(set(st.keys()), {
            "id", "name", "status", "step", "files", "warning",
            "local_test_passed", "local_test_evidence", "verification_commands",
            "review_reds", "review_dimensions", "checked_by", "verify_passed",
        })

    def test_add_subtask_skeleton_has_no_item_layer(self):
        """Q10：確認 skeleton 不含 items（曾於 2026-09-22 短暫加入後依裁示移除）。"""
        self.bootstrap()
        self.assertNotIn("items", self.read_state()["sub_tasks"][0])

    def test_legacy_flat_subtask_with_extra_keys_still_operable(self):
        """向後相容：既有 19 份歸檔與進行中的舊 eval_state 帶 `risk_analysis` 等已移除的鍵，
        子命令仍須能對其操作（本 run 自身即為此形狀，改構期間不得把自己鎖死）。"""
        self.bootstrap()
        # setUp 已 chdir 到 tmpdir，"eval_state.json" 即該 run 的實際狀態檔（同 read_state 慣例）
        state = self.read_state()
        state["sub_tasks"][0]["risk_analysis"] = {"technical": "舊欄位"}
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        run_cli("set-review", "1", "0")
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["review_reds"], 0)
        self.assertEqual(st["risk_analysis"], {"technical": "舊欄位"})

    def test_set_review_writes_task_layer_reds_with_zero(self):
        """Q9 契約 row 2：set-review id=1 reds=0 → sub_tasks[0].review_reds == 0（task 層憑據）。"""
        self.bootstrap()
        run_cli("set-review", "1", "0")
        self.assertEqual(self.read_state()["sub_tasks"][0]["review_reds"], 0)

    def test_set_files_reflects_in_task_layer_union(self):
        """Q9 契約 row 3：set-files 寫入反映在 task 層 files 聯集。"""
        self.bootstrap()
        run_cli("set-files", "1", "src/a.py", "src/b.py")
        self.assertEqual(self.read_state()["sub_tasks"][0]["files"], ["src/a.py", "src/b.py"])

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

    def test_set_review_checked_by_boundary_is_valid(self):
        """邊界直派（2026-09-21）：reviewer:boundary 為合法審定者值。"""
        self.bootstrap()
        run_cli("set-review", "1", "0", "--checked-by", "reviewer:boundary")
        self.assertEqual(self.read_state()["sub_tasks"][0]["checked_by"], "reviewer:boundary")

    def test_add_verification_event_records_command_text(self):
        """事件鍵 verify_command：append_event 過濾 `command` 鍵（子命令 dest），指令原文須以
        verify_command 鍵留痕（2026-09-21 修正；消費端 stats.py 全套次數）。"""
        self.bootstrap()
        run_cli("add-verification", "1", "--command", "pytest -q --strike-key full_suite", "--exit-code", "0")
        with open("run/2026-07-15-demo.events.jsonl", encoding="utf-8") as f:
            ev = [json.loads(line) for line in f if line.strip()][-1]
        self.assertEqual(ev["cmd"], "add-verification")
        self.assertEqual(ev["args"]["verify_command"], "pytest -q --strike-key full_suite")
        self.assertEqual(ev["args"]["exit_code"], 0)
        self.assertEqual(ev["args"]["id"], 1)

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

    # --- record_session：init 事件寫 manifest session_id／config_dir ---

    def write_manifest(self, run_id, **extra):
        os.makedirs("run", exist_ok=True)
        m = {"run_id": run_id, "tier": 1, "status": "in_progress", **extra}
        with open(os.path.join("run", f"{run_id}.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)
        return m

    def read_manifest(self, run_id):
        with open(os.path.join("run", f"{run_id}.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_event_init_records_session_keys_into_manifest(self):
        before = self.write_manifest("t1-run")
        env = {"CLAUDE_CODE_SESSION_ID": "sess-abc", "CLAUDE_CONFIG_DIR": "/cfg/dir"}
        with mock.patch.dict(os.environ, env, clear=False):
            run_cli("event", "t1-run", "init")
        after = self.read_manifest("t1-run")
        self.assertEqual(after["session_id"], "sess-abc")
        self.assertEqual(after["config_dir"], "/cfg/dir")
        for k, v in before.items():
            self.assertEqual(after[k], v)

    def test_event_init_defaults_config_dir_to_home_claude(self):
        self.write_manifest("t1-run")
        env = {"CLAUDE_CODE_SESSION_ID": "sess-abc"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            run_cli("event", "t1-run", "init")
        self.assertEqual(self.read_manifest("t1-run")["config_dir"],
                         os.path.expanduser("~/.claude"))

    def test_event_init_without_session_env_leaves_manifest_untouched(self):
        self.write_manifest("t1-run")
        path = os.path.join("run", "t1-run.json")
        with open(path, "rb") as f:
            raw = f.read()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            run_cli("event", "t1-run", "init")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), raw)
        self.assertEqual(len(self.read_events("t1-run")), 1)

    def test_event_init_does_not_overwrite_existing_session_id(self):
        self.write_manifest("t1-run", session_id="old", config_dir="/old")
        env = {"CLAUDE_CODE_SESSION_ID": "new", "CLAUDE_CONFIG_DIR": "/new"}
        with mock.patch.dict(os.environ, env, clear=False):
            run_cli("event", "t1-run", "init")
        after = self.read_manifest("t1-run")
        self.assertEqual((after["session_id"], after["config_dir"]), ("old", "/old"))

    def test_event_init_without_manifest_still_appends_event(self):
        self.assertFalse(os.path.exists(os.path.join("run", "t1-run.json")))
        env = {"CLAUDE_CODE_SESSION_ID": "sess-abc"}
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("sys.stderr", stderr):
            run_cli("event", "t1-run", "init")
        self.assertEqual([e["cmd"] for e in self.read_events("t1-run")], ["init"])
        self.assertIn("session 對應鍵未寫入", stderr.getvalue())
        self.assertFalse(os.path.exists(os.path.join("run", "t1-run.json")))

    def test_non_init_event_does_not_record_session(self):
        self.write_manifest("t1-run")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "sess-abc"}, clear=False):
            run_cli("event", "t1-run", "hitl_confirmed")
        self.assertNotIn("session_id", self.read_manifest("t1-run"))

    def test_tier2_init_records_session_keys_into_manifest(self):
        self.write_manifest("r2")
        env = {"CLAUDE_CODE_SESSION_ID": "sess-t2", "CLAUDE_CONFIG_DIR": "/cfg"}
        with mock.patch.dict(os.environ, env, clear=False):
            run_cli("init", "--run-id", "r2")
        after = self.read_manifest("r2")
        self.assertEqual((after["session_id"], after["config_dir"]), ("sess-t2", "/cfg"))

    def test_event_appends_in_order(self):
        run_cli("event", "t1-run", "init_done")
        run_cli("event", "t1-run", "item_reviewed")
        self.assertEqual([e["cmd"] for e in self.read_events("t1-run")],
                         ["init_done", "item_reviewed"])

    # --- tier0 自算行數（item 13.3）---
    #
    # 下三條原本綁「收信自報 --lines、留痕恰 4 個鍵」的舊契約（無 git、檔案不必存在）。
    # 有意的行為變更（非改弱測試）：Tier 0 直寫無任何 gate，自報行數從未被核對，13 筆歷史
    # 留痕的 lines 全未經核。新契約自算並機械執行 CLAUDE.md 的檔數／行數上限，故三條改為
    # 在真實 git fixture 上驗新契約。

    def git_repo(self):
        """在 cwd 建一個有 baseline commit 的 git repo（tier0 自算需要 git diff HEAD）。"""
        import subprocess
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                    ["git", "config", "user.name", "T"]):
            subprocess.run(cmd, check=True, capture_output=True)
        with open("seed.txt", "w", encoding="utf-8") as f:
            f.write("seed\n")
        subprocess.run(["git", "add", "seed.txt"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "baseline"], check=True, capture_output=True)

    def tracked_file(self, name, lines):
        """建一個已追蹤檔並改 lines 行（git diff HEAD 可見）。"""
        import subprocess
        with open(name, "w", encoding="utf-8") as f:
            f.write("x\n")
        subprocess.run(["git", "add", name], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"add {name}"], check=True, capture_output=True)
        with open(name, "w", encoding="utf-8") as f:
            f.write("".join(f"line{i}\n" for i in range(lines)))

    def test_tier0_appends_entry_with_verified_lines(self):
        """新契約：留痕的 lines 來自 git diff 實得，並多記 lines_verified／per_file_lines。"""
        self.git_repo()
        self.tracked_file("a.py", 8)   # 1 行刪 + 8 行增 = 9
        with open("b.md", "w", encoding="utf-8") as f:
            f.write("m1\nm2\nm3\n")  # 未追蹤：3 行全新增
        run_cli("tier0", "--summary", "文案微調", "--files", "a.py, b.md", "--lines", "12")
        entries = self.read_tier0()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(set(e), {"ts", "summary", "files", "lines", "lines_verified",
                                  "per_file_lines", "mechanical"})
        self.assertEqual(e["summary"], "文案微調")
        self.assertEqual(e["files"], ["a.py", "b.md"])
        self.assertEqual(e["lines"], 12)
        self.assertTrue(e["lines_verified"])
        self.assertEqual(e["per_file_lines"], {"a.py": 9, "b.md": 3})
        self.assertFalse(e["mechanical"])

    def test_tier0_is_append_only(self):
        self.git_repo()
        with open("a.py", "w", encoding="utf-8") as f:
            f.write("one\n")
        with open("b.py", "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")
        run_cli("tier0", "--summary", "第一筆", "--files", "a.py", "--lines", "1")
        run_cli("tier0", "--summary", "第二筆", "--files", "b.py", "--lines", "2")
        self.assertEqual([e["summary"] for e in self.read_tier0()], ["第一筆", "第二筆"])

    def test_tier0_rejects_blank_summary(self):
        with self.assertRaises(SystemExit):
            run_cli("tier0", "--summary", "  ", "--files", "a.py", "--lines", "1")

    def test_tier0_rejects_self_reported_mismatch(self):
        """核心：自報與實得不符 → 拒絕留痕，並同時印兩個數字。"""
        self.git_repo()
        self.tracked_file("a.py", 8)
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                run_cli("tier0", "--summary", "s", "--files", "a.py", "--lines", "999")
            err = buf.getvalue()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("自報 999", err)
        self.assertIn("實得 9", err)
        self.assertFalse(os.path.exists(os.path.join("run", "tier0.jsonl")))

    def test_tier0_rejects_too_many_files(self):
        """檔數 >3 → 拒絕並提示 --mechanical 或改判 Tier 1。"""
        self.git_repo()
        names = []
        for i in range(4):
            n = f"f{i}.txt"
            with open(n, "w", encoding="utf-8") as f:
                f.write("x\n")
            names.append(n)
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", ",".join(names), "--lines", "4")
            err = buf.getvalue()
        self.assertIn("上限為 3 個檔案", err)
        self.assertIn("--mechanical", err)

    def test_tier0_rejects_over_line_budget(self):
        """合計 >80 行 → 拒絕並說應判 Tier 1。"""
        self.git_repo()
        with open("big.txt", "w", encoding="utf-8") as f:
            f.write("".join(f"l{i}\n" for i in range(81)))
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "big.txt", "--lines", "81")
            err = buf.getvalue()
        self.assertIn("合計 80 行", err)
        self.assertIn("Tier 1", err)

    def test_tier0_mechanical_allows_many_files_within_per_file_cap(self):
        """--mechanical：5 檔各 10 行 → 放行（不限檔數）。"""
        self.git_repo()
        names = []
        for i in range(5):
            n = f"m{i}.txt"
            with open(n, "w", encoding="utf-8") as f:
                f.write("".join(f"l{j}\n" for j in range(10)))
            names.append(n)
        run_cli("tier0", "--summary", "同一句文案換 5 處", "--files", ",".join(names),
                "--lines", "50", "--mechanical")
        e = self.read_tier0()[0]
        self.assertTrue(e["mechanical"])
        self.assertEqual(e["lines"], 50)

    def test_tier0_mechanical_rejects_file_over_fifty_lines(self):
        """--mechanical 的每檔上限 50 行 → 超標印該檔名。"""
        self.git_repo()
        with open("m0.txt", "w", encoding="utf-8") as f:
            f.write("".join(f"l{j}\n" for j in range(51)))
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "m0.txt", "--lines", "51",
                        "--mechanical")
            err = buf.getvalue()
        self.assertIn("每檔 ≤50 行", err)
        self.assertIn("m0.txt", err)

    def test_tier0_rejects_binary_change(self):
        """🟡-2：二進位檔的 numstat 為 `-`，以 0 計會讓任意大小的改動偷渡 → 直接拒絕。"""
        import subprocess
        self.git_repo()
        with open("b.bin", "wb") as f:
            f.write(b"\x00" * 16)
        subprocess.run(["git", "add", "b.bin"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add bin"], check=True, capture_output=True)
        with open("b.bin", "wb") as f:
            f.write(b"\x01" * 5000)
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "b.bin", "--lines", "0")
            err = buf.getvalue()
        self.assertIn("二進位檔", err)
        self.assertIn("b.bin", err)
        self.assertFalse(os.path.exists(os.path.join("run", "tier0.jsonl")))

    def test_tier0_supports_deleted_file(self):
        """🟡-3：合法的 Tier 0 刪檔（工作區已無、git diff 看得到）須能留痕。"""
        import subprocess
        self.git_repo()
        with open("gone.txt", "w", encoding="utf-8") as f:
            f.write("a\nb\nc\n")
        subprocess.run(["git", "add", "gone.txt"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add gone"], check=True, capture_output=True)
        os.remove("gone.txt")
        run_cli("tier0", "--summary", "刪掉過期文案檔", "--files", "gone.txt", "--lines", "3")
        e = self.read_tier0()[0]
        self.assertEqual(e["per_file_lines"], {"gone.txt": 3})

    def test_tier0_rejects_directory_pathspec(self):
        """🟡-B：目錄會讓檔數上限失效（git diff 展開目錄下全部檔案）→ 拒絕，要求逐檔列出。"""
        import subprocess
        self.git_repo()
        os.makedirs("d", exist_ok=True)
        for i in range(5):
            with open(os.path.join("d", f"f{i}.txt"), "w", encoding="utf-8") as f:
                f.write("x\n")
        subprocess.run(["git", "add", "d"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add d"], check=True, capture_output=True)
        for i in range(5):
            with open(os.path.join("d", f"f{i}.txt"), "w", encoding="utf-8") as f:
                f.write("changed\n")
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "d", "--lines", "10")
            err = buf.getvalue()
        self.assertIn("不接受目錄", err)
        self.assertFalse(os.path.exists(os.path.join("run", "tier0.jsonl")))

    def test_tier0_rejects_missing_file(self):
        """[邊界] --files 列出不存在的路徑 → 拒絕並印該路徑。"""
        self.git_repo()
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "nope.py", "--lines", "1")
            err = buf.getvalue()
        self.assertIn("nope.py", err)

    def test_tier0_outside_git_repo_refuses(self):
        """[邊界] 非 git 工作區 → 拒絕記帳（不靜默留痕）。"""
        with open("a.py", "w", encoding="utf-8") as f:
            f.write("x\n")
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                run_cli("tier0", "--summary", "s", "--files", "a.py", "--lines", "1")
            err = buf.getvalue()
        self.assertIn("不在 git 工作區", err)
        self.assertFalse(os.path.exists(os.path.join("run", "tier0.jsonl")))


class HitlConfirmTest(unittest.TestCase):
    """item 13.2 契約：hitl-confirm 寫三欄並推進 phase；前置不過一律 exit 1 不寫檔。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("run", exist_ok=True)
        # 釘住「有人看管」：本框架的派工（dispatch.py）與評測都是 headless（ATTENDED=0），
        # 不釘的話成功路徑會被「無人看管拒絕」擋掉而誤紅——誤紅會打在自己的驗證與收尾 gate 上。
        # 需要驗無人看管行為的測試自行覆寫（見 test_unattended_session_cannot_self_confirm）。
        # 本釘樁是否承重，只能靠在 headless 環境跑整套來驗（實測：拿掉釘樁、ATTENDED=0 → 2 failed）；
        # 測試無法對自己所在套件的環境穩健性下斷言，故不另設假鎖。
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    RID = "2026-10-03-probe"

    def write_manifest(self, **over):
        m = {"run_id": self.RID, "tier": 1, "status": "in_progress", "phase": "init",
             "spec_inline": "一句需求", "task_file": "task/2026-10-03.md",
             "hitl_confirmed_at": None, "hitl_rulings": None}
        m.update(over)
        with open(os.path.join("run", f"{self.RID}.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        return m

    def read_manifest(self):
        with open(os.path.join("run", f"{self.RID}.json"), encoding="utf-8") as f:
            return json.load(f)

    def read_events(self):
        path = os.path.join("run", f"{self.RID}.events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _expect_exit1(self, *argv):
        with io.StringIO() as buf, contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                run_cli(*argv)
            err = buf.getvalue()
        self.assertEqual(cm.exception.code, 1)
        return err

    def test_confirms_and_advances_phase(self):
        self.write_manifest()
        run_cli("hitl-confirm", self.RID, "--note", "確認 2 tasks／4 items", "--rulings", "2")
        m = self.read_manifest()
        self.assertEqual(m["phase"], "decomposed")
        self.assertEqual(m["hitl_rulings"], 2)
        self.assertIn("確認 2 tasks／4 items", m["hitl_confirmed_at"])
        self.assertRegex(m["hitl_confirmed_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — ")
        self.assertEqual([e["cmd"] for e in self.read_events()], ["hitl_confirmed"])

    def test_rulings_defaults_to_zero(self):
        self.write_manifest()
        run_cli("hitl-confirm", self.RID, "--note", "無裁示，照計畫")
        self.assertEqual(self.read_manifest()["hitl_rulings"], 0)

    def test_blank_note_refused_and_manifest_untouched(self):
        self.write_manifest()
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "   ")
        self.assertIn("--note 不可為空", err)
        m = self.read_manifest()
        self.assertEqual(m["phase"], "init")
        self.assertIsNone(m["hitl_confirmed_at"])

    def test_missing_task_file_refused(self):
        self.write_manifest(task_file=None)
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("HITL 掛在分拆之後", err)
        self.assertEqual(self.read_manifest()["phase"], "init")

    def test_intent_gate_refused(self):
        self.write_manifest(spec_inline=None, spec_path=None)
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("intent gate", err)

    def test_non_in_progress_refused(self):
        self.write_manifest(status="completed")
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("非 in_progress", err)

    def test_existing_confirmation_not_overwritten(self):
        self.write_manifest(hitl_confirmed_at="2026-10-01 09:00 — 原確認")
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "新確認")
        self.assertIn("已有 hitl_confirmed_at", err)
        self.assertIn("原確認", err)
        self.assertEqual(self.read_manifest()["hitl_confirmed_at"], "2026-10-01 09:00 — 原確認")

    def test_unattended_session_cannot_self_confirm(self):
        """無人看管（ATTENDED=0）→ exit 1、三欄不變。出生證：headless 評測中模型自行確認後動工。"""
        self.write_manifest()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            err = self._expect_exit1("hitl-confirm", self.RID, "--note", "自己確認")
        self.assertIn("無人看管", err)
        self.assertIn("停在這一步", err)
        m = self.read_manifest()
        self.assertEqual(m["phase"], "init")
        self.assertIsNone(m["hitl_confirmed_at"])

    def test_attended_session_records_attended_flag(self):
        """互動 session（ATTENDED=1）→ 照常確認並留痕 hitl_attended。"""
        self.write_manifest()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            run_cli("hitl-confirm", self.RID, "--note", "確認計畫")
        m = self.read_manifest()
        self.assertEqual(m["phase"], "decomposed")
        self.assertIs(m["hitl_attended"], True)

    def test_missing_attended_env_is_recorded_as_unknown(self):
        """環境未提供該變數（例如直接在終端跑）→ 不擋，但留痕為 None 供稽核。"""
        self.write_manifest()
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ATTENDED"}
        with mock.patch.dict(os.environ, env, clear=True):  # clear 後 setUp 的釘樁不生效
            run_cli("hitl-confirm", self.RID, "--note", "終端手動確認")
        m = self.read_manifest()
        self.assertEqual(m["phase"], "decomposed")
        self.assertIsNone(m["hitl_attended"])

    def test_phase_cannot_be_rolled_back(self):
        """🟡-1：phase 已 ≥ decomposed 時拒絕，不把前進過的 phase 倒退回去。"""
        self.write_manifest(phase="completed")
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("不可把已前進的 phase 倒退", err)
        self.assertEqual(self.read_manifest()["phase"], "completed")

    def test_refusal_message_does_not_leak_env_var_name(self):
        """🟡-4：拒絕訊息不印環境變數名（被擋的一方不需要知道哪個變數決定判定）。"""
        self.write_manifest()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("無人看管", err)
        self.assertNotIn("CLAUDE_CODE_SESSION_ATTENDED", err)

    def test_unknown_run_id_refused(self):
        err = self._expect_exit1("hitl-confirm", "2026-01-01-nope", "--note", "x")
        self.assertIn("不存在", err)

    def test_invalid_json_manifest_refused_without_traceback(self):
        with open(os.path.join("run", f"{self.RID}.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        err = self._expect_exit1("hitl-confirm", self.RID, "--note", "x")
        self.assertIn("非合法 JSON", err)


if __name__ == "__main__":
    unittest.main()
