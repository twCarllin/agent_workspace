"""eval_state.py helper 的操作與驗證測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（helper 以 cwd 的 eval_state.json 為對象）。
"""

import contextlib
import io
import json
import os
import subprocess
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

    def test_legacy_review_does_not_become_first_round(self):
        for legacy_reds in (0, 1):
            with self.subTest(legacy_reds=legacy_reds):
                if not Path("eval_state.json").exists():
                    self.bootstrap()
                state = self.read_state()
                task = state["sub_tasks"][0]
                task.pop("review_rounds", None)
                task.pop("first_review_reds", None)
                task["review_reds"] = legacy_reds
                Path("eval_state.json").write_text(json.dumps(state))
                run_cli("set-review", "1", "0", "--checked-by", "checker")
                task = self.read_state()["sub_tasks"][0]
                self.assertNotIn("first_review_reds", task)
                self.assertEqual(
                    [row["review_reds"] for row in task["review_rounds"]], [None, 0]
                )
                self.assertIsNone(task["review_rounds"][0]["checked_by"])
                self.assertIsNone(task["review_rounds"][0]["passed"])

    def test_explicit_first_review_survives_round_migration(self):
        self.bootstrap()
        state = self.read_state()
        state["sub_tasks"][0].update(review_reds=0, first_review_reds=2)
        Path("eval_state.json").write_text(json.dumps(state))
        run_cli("set-review", "1", "0", "--checked-by", "checker")
        task = self.read_state()["sub_tasks"][0]
        self.assertEqual(task["first_review_reds"], 2)
        self.assertEqual([row["review_reds"] for row in task["review_rounds"]], [2, 0])

    def test_tier2_review_rounds_real_cli(self):
        import subprocess

        entry = (
            Path(__file__).resolve().parents[1] / ".agent-flow/scripts/eval_state.py"
        )
        self.bootstrap()
        for reds, reviewer in ((2, "checker"), (0, "reviewer:manual")):
            result = subprocess.run(
                [
                    sys.executable,
                    str(entry),
                    "set-review",
                    "1",
                    str(reds),
                    "--checked-by",
                    reviewer,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        task = self.read_state()["sub_tasks"][0]
        self.assertEqual(task["review_reds"], 2)
        self.assertEqual(
            [
                (row["review_reds"], row["checked_by"], row["passed"])
                for row in task["review_rounds"]
            ],
            [(2, "checker", False), (0, "reviewer:manual", True)],
        )

    def test_tier1_operations_real_compatibility_entries(self):
        import subprocess

        root = Path(__file__).resolve().parents[1]
        for entry in (
            root / ".agent-flow/scripts/eval_state.py",
            root / ".claude/hooks/eval_state.py",
        ):
            run_id = (
                "flow" + str(len(list(Path("run").glob("*.json"))))
                if Path("run").exists()
                else "flow0"
            )
            argv = [
                sys.executable,
                str(entry),
                "init-run",
                "--run-id",
                run_id,
                "--harness",
                "codex",
                "--spec-inline",
                "page change",
                "--tier-rationale",
                "bounded change",
                "--test-command",
                "python3 -m unittest",
                "--task-file",
                "task/flow.md",
            ]
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            path = Path(f"run/{run_id}.json")
            manifest = json.loads(path.read_text())
            expected = {
                "run_id": run_id,
                "framework_version": (root / ".agent-flow/scripts/VERSION")
                .read_text()
                .strip(),
                "harness": "codex",
                "evidence_schema": 2,
                "tier": 1,
                "spec_inline": "page change",
                "tier_rationale": "bounded change",
                "test_command": "python3 -m unittest",
                "task_file": "task/flow.md",
                "status": "in_progress",
                "phase": "init",
                "verification_commands": [],
            }
            for key, value in expected.items():
                self.assertEqual(manifest[key], value, key)
            for key in (
                "risk_report_path",
                "usage_report_path",
                "impact_report_path",
                "local_test_passed",
                "local_test_evidence",
                "review_reds",
                "verify_passed",
                "checked_by",
                "review_evidence",
            ):
                self.assertIsNone(manifest[key], key)
            self.assertTrue(manifest["created_at"])
            self.assertFalse(Path("eval_state.json").exists())
            events_path = Path(f"run/{run_id}.events.jsonl")
            event = json.loads(events_path.read_text())
            self.assertEqual(event["cmd"], "init")
            self.assertEqual(
                event["args"],
                {
                    "run_id": run_id,
                    "harness": "codex",
                    "spec_inline": "page change",
                    "tier_rationale": "bounded change",
                    "test_command": "python3 -m unittest",
                    "task_file": "task/flow.md",
                },
            )
            before = events_path.read_text()
            self.assertNotEqual(subprocess.run(argv, capture_output=True).returncode, 0)
            self.assertEqual(events_path.read_text(), before)
            review = [
                sys.executable,
                str(entry),
                "review-run",
                run_id,
                "2",
                "--checked-by",
                "reviewer:manual",
                "--evidence",
                "two issues",
            ]
            self.assertNotEqual(
                subprocess.run(review, capture_output=True).returncode, 0
            )
            self.assertEqual(events_path.read_text(), before)
            manifest["phase"] = "decomposed"
            path.write_text(json.dumps(manifest))
            self.assertEqual(subprocess.run(review, capture_output=True).returncode, 0)
            manifest = json.loads(path.read_text())
            self.assertEqual(manifest["review_reds"], 2)
            self.assertFalse(manifest["verify_passed"])
            self.assertEqual(manifest["checked_by"], "reviewer:manual")
            self.assertEqual(manifest["review_evidence"], "two issues")
            event = json.loads(events_path.read_text().splitlines()[-1])
            self.assertEqual(event["cmd"], "reviewed")
            self.assertEqual(
                event["args"],
                {
                    "run_id": run_id,
                    "reds": 2,
                    "checked_by": "reviewer:manual",
                    "evidence": "two issues",
                    "passed": False,
                },
            )
            before = events_path.read_text()
            self.assertNotEqual(
                subprocess.run(review + ["--passed"], capture_output=True).returncode, 0
            )
            self.assertEqual(events_path.read_text(), before)
            review[4] = "0"
            review[-1] = "fixed and checked"
            self.assertEqual(
                subprocess.run(review + ["--passed"], capture_output=True).returncode, 0
            )
            manifest = json.loads(path.read_text())
            self.assertEqual(manifest["review_reds"], 2)
            self.assertTrue(manifest["verify_passed"])
            self.assertEqual(manifest["review_evidence"], "fixed and checked")
            self.assertEqual(
                [row["review_reds"] for row in manifest["review_rounds"]], [2, 0]
            )
            self.assertEqual(
                [row["passed"] for row in manifest["review_rounds"]], [False, True]
            )
            self.assertTrue(
                all(
                    row["checked_by"] == "reviewer:manual"
                    for row in manifest["review_rounds"]
                )
            )
            manifest["status"] = "completed"
            path.write_text(json.dumps(manifest))
            before = events_path.read_text()
            self.assertNotEqual(
                subprocess.run(review, capture_output=True).returncode, 0
            )
            self.assertEqual(events_path.read_text(), before)
            invalid = argv.copy()
            invalid[4] = "../escape"
            self.assertNotEqual(
                subprocess.run(invalid, capture_output=True).returncode, 0
            )
            invalid[4] = "empty"
            invalid[8] = " "
            self.assertNotEqual(
                subprocess.run(invalid, capture_output=True).returncode, 0
            )
            self.assertFalse(Path("run/empty.json").exists())
            self.assertFalse(Path("run/empty.events.jsonl").exists())

    def fresh(self):
        if os.path.exists("eval_state.json"):
            os.remove("eval_state.json")
        self.bootstrap()

    def exit_of(self, *argv):
        """回傳 (exit code, stderr)；命令必須以 SystemExit 結束。"""
        err = io.StringIO()
        with mock.patch("sys.stderr", err), self.assertRaises(SystemExit) as ctx:
            run_cli(*argv)
        return ctx.exception.code, err.getvalue()

    def test_init_creates_state_and_refuses_overwrite(self):
        run_cli("init", "--run-id", "r1")
        state = self.read_state()
        self.assertEqual(state["run_id"], "r1")
        self.assertEqual(state["sub_tasks"], [])
        self.assertNotIn("threshold", state)
        self.assertTrue(self.exit_of("init", "--run-id", "r2")[0])
        self.assertEqual(self.read_state()["run_id"], "r1")

    def test_set_step_and_files(self):
        self.bootstrap()
        run_cli("set-step", "1", "writing")
        run_cli("set-files", "1", "src/a.py", "src/b.py", "src/a.py")
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["step"], "writing")
        # Q9 契約 row 3：set-files 寫入反映在 task 層 files 聯集（去重保序）
        self.assertEqual(st["files"], ["src/a.py", "src/b.py"])
        self.assertTrue(self.exit_of("set-step", "99", "writing")[0])  # 未知 id

    def test_set_test_passed_requires_evidence(self):
        self.bootstrap()
        self.assertTrue(self.exit_of("set-test", "1", "--passed")[0])
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        self.assertTrue(self.read_state()["sub_tasks"][0]["local_test_passed"])

    def test_list_files_unions_across_subtasks(self):
        self.bootstrap()
        run_cli("add-subtask", "--id", "2", "--name", "demo2")
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-files", "2", "src/b.py", "src/a.py")
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            run_cli("list-files")
        self.assertEqual(buf.getvalue().split(), ["src/a.py", "src/b.py"])

    def test_archive_blocks_incomplete_subtask(self):
        def passed_without_review_verify():
            run_cli("set-files", "1", "src/a.py")
            run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
            run_cli("set-status", "1", "passed")

        cases = (
            ("unpassed_subtask", lambda: None),
            ("passed_but_review_verify_unset", passed_without_review_verify),
        )
        for name, prepare in cases:
            with self.subTest(name):
                self.fresh()
                prepare()
                self.assertEqual(self.exit_of("archive")[0], 2)
                self.assertTrue(os.path.exists("eval_state.json"))  # 不落盤、不清除

    def test_archive_writes_clears_and_carries_checked_by(self):
        self.bootstrap()
        run_cli("set-files", "1", "src/a.py")
        run_cli("set-test", "1", "--passed", "--evidence", "pytest -q -> 3 passed")
        run_cli("set-review", "1", "1", "--checked-by", "reviewer:④")
        run_cli("set-verify", "1")
        self.assertTrue(self.read_state()["sub_tasks"][0]["verify_passed"])
        run_cli("set-status", "1", "passed")
        run_cli("archive")
        self.assertFalse(os.path.exists("eval_state.json"))
        with open("run/2026-07-15-demo.eval.json", encoding="utf-8") as f:
            archived = json.load(f)
        self.assertEqual(archived["run_id"], "2026-07-15-demo")
        self.assertEqual(archived["sub_tasks"][0]["checked_by"], "reviewer:④")

    def test_add_subtask_skeleton_key_set_and_defaults(self):
        """R-004 加嚴：逐鍵斷言完整鍵集。Q10：不存 item 層資料（不得含 `items`）；
        Q8：`risk_analysis` 已移除。鍵集寫死是刻意的——新增欄位須回來確認該進 skeleton。"""
        self.bootstrap()
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(
            set(st.keys()),
            {
                "id",
                "name",
                "status",
                "step",
                "files",
                "warning",
                "local_test_passed",
                "local_test_evidence",
                "verification_commands",
                "review_reds",
                "review_dimensions",
                "checked_by",
                "verify_passed",
            },
        )
        self.assertIsNone(st["review_reds"])
        self.assertFalse(st["verify_passed"])
        self.assertEqual(st["verification_commands"], [])

    def test_legacy_flat_subtask_with_extra_keys_still_operable(self):
        """向後相容：舊 eval_state 帶 `risk_analysis` 等已移除的鍵，子命令仍須能對其操作。"""
        self.bootstrap()
        state = self.read_state()
        state["sub_tasks"][0]["risk_analysis"] = {"technical": "舊欄位"}
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        run_cli("set-review", "1", "0")
        st = self.read_state()["sub_tasks"][0]
        self.assertEqual(st["review_reds"], 0)
        self.assertEqual(st["risk_analysis"], {"technical": "舊欄位"})

    def test_set_review_writes_fields(self):
        dims = '{"Clarity":1,"Completeness":1}'
        cases = (
            # Q9 契約 row 2：reds=0 寫入 task 層 review_reds == 0；未帶 --checked-by 維持 null
            ("zero_reds_keeps_checked_by_null", ("1", "0"), {"review_reds": 0, "checked_by": None}),
            ("reds_written", ("1", "3"), {"review_reds": 3}),
            (
                "checked_by_written",
                ("1", "0", "--checked-by", "checker"),
                {"checked_by": "checker"},
            ),
            (
                # 邊界直派（2026-09-21）：reviewer:boundary 為合法審定者值
                "checked_by_boundary_is_valid",
                ("1", "0", "--checked-by", "reviewer:boundary"),
                {"checked_by": "reviewer:boundary"},
            ),
            (
                "valid_dimensions",
                ("1", "2", "--dimensions", dims),
                {"review_reds": 2, "review_dimensions": {"Clarity": 1, "Completeness": 1}},
            ),
        )
        for name, argv, expected in cases:
            with self.subTest(name):
                self.fresh()
                run_cli("set-review", *argv)
                st = self.read_state()["sub_tasks"][0]
                for key, value in expected.items():
                    self.assertEqual(st[key], value, key)

    def test_set_review_invalid_input_exits_and_leaves_file(self):
        cases = (
            ("negative_reds", ("1", "-1"), None, ""),
            # 契約：exit 2、stderr 含合法值清單（寬鬆存在性）
            ("invalid_checked_by", ("1", "0", "--checked-by", "reviewer:⑥"), 2, "checker"),
            ("invalid_dimension_key", ("1", "1", "--dimensions", '{"InvalidKey":1}'), 2, ""),
            ("negative_dimension_value", ("1", "1", "--dimensions", '{"Clarity":-1}'), 2, ""),
            ("bad_json_dimensions", ("1", "1", "--dimensions", "{not valid json}"), 2, ""),
        )
        for name, argv, code, stderr_has in cases:
            with self.subTest(name):
                self.fresh()
                before = self.read_state()
                got, err = self.exit_of("set-review", *argv)
                if code is None:
                    self.assertTrue(got)
                else:
                    self.assertEqual(got, code)
                self.assertIn(stderr_has, err)
                self.assertEqual(self.read_state(), before)  # 不落盤

    def test_add_verification_event_records_command_text(self):
        """事件鍵 verify_command：append_event 過濾 `command` 鍵（子命令 dest），
        指令原文須以 verify_command 留痕（消費端 stats.py 全套次數）。"""
        self.bootstrap()
        run_cli(
            "add-verification", "1", "--command", "pytest -q --strike-key full_suite", "--exit-code", "0"
        )
        with open("run/2026-07-15-demo.events.jsonl", encoding="utf-8") as f:
            ev = [json.loads(line) for line in f if line.strip()][-1]
        self.assertEqual(ev["cmd"], "add-verification")
        self.assertEqual(ev["args"]["verify_command"], "pytest -q --strike-key full_suite")
        self.assertEqual(ev["args"]["exit_code"], 0)
        self.assertEqual(ev["args"]["id"], 1)

    def test_add_verification_records_or_refuses(self):
        """add-verification 為純記錄欄位，不被任何 gate 消費。"""

        def add(cmd, code, tid="1"):
            return ("add-verification", tid, "--command", cmd, "--exit-code", str(code))

        def drop_key():  # 後加的可選欄位：舊 sub_task 無此鍵時不可 KeyError
            state = self.read_state()
            del state["sub_tasks"][0]["verification_commands"]
            with open("eval_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            self.assertNotIn("verification_commands", self.read_state()["sub_tasks"][0])

        def row(cmd, code):
            return {"command": cmd, "exit_code": code}

        recorded = (
            ("appends_in_order", None, [add("pytest -q", 0), add("ruff check .", 1)],
             [row("pytest -q", 0), row("ruff check .", 1)]),
            ("negative_exit_code", None, [add("killed", -9)], [row("killed", -9)]),
            ("backward_compat_missing_key", drop_key, [add("pytest -q", 0)], [row("pytest -q", 0)]),
        )
        for name, prepare, calls, expected in recorded:
            with self.subTest(name):
                self.fresh()
                if prepare:
                    prepare()
                for argv in calls:
                    run_cli(*argv)
                self.assertEqual(self.read_state()["sub_tasks"][0]["verification_commands"], expected)
        refused = (("unknown_id", add("pytest", 0, tid="99")), ("blank_command", add("   ", 0)))
        for name, argv in refused:
            with self.subTest(name):
                self.fresh()
                self.assertEqual(self.exit_of(*argv)[0], 1)
                self.assertEqual(self.read_state()["sub_tasks"][0]["verification_commands"], [])


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

    def test_write_subcommands_append_events_in_order(self):
        run_cli("init", "--run-id", "r1")
        events = self.read_events("r1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cmd"], "init")
        self.assertIn("ts", events[0])
        self.assertEqual(events[0]["args"]["run_id"], "r1")
        self.assertNotIn("func", events[0]["args"])
        self.assertNotIn("command", events[0]["args"])
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        run_cli("set-step", "1", "writing")
        self.assertEqual(
            [e["cmd"] for e in self.read_events("r1")], ["init", "add-subtask", "set-step"]
        )

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 略過檔案權限測試")
    def test_events_dir_unwritable_main_command_still_succeeds(self):
        """events 目錄不可寫 → 主命令仍成功，僅 stderr warning（風險技術#1）。"""
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
        self.assertEqual(self.read_state()["sub_tasks"][0]["name"], "demo")
        self.assertTrue(stderr_buf.getvalue())  # 有 warning
        self.assertFalse(os.path.exists(os.path.join("run", "r4.events.jsonl")))

    def test_missing_run_id_skips_append_with_warning(self):
        """eval_state.json 缺 run_id（如舊檔）→ 略過事件記錄，僅 warning，不影響主命令（D-err2）。"""
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump({"sub_tasks": []}, f)
        stderr_buf = io.StringIO()
        with mock.patch.object(sys, "stderr", stderr_buf):
            run_cli("add-subtask", "--id", "1", "--name", "demo")
        self.assertTrue(stderr_buf.getvalue())
        self.assertEqual(self.read_state()["sub_tasks"][0]["name"], "demo")
        self.assertFalse(os.path.isdir("run"))  # 未產生任何 events 檔

    def test_arg_value_truncation_and_special_characters(self):
        run_cli("init", "--run-id", "r5")
        run_cli("add-subtask", "--id", "1", "--name", "demo")
        cases = (
            ("over_200_truncated", "x" * 250, "x" * 200 + "…[truncated]"),
            # 恰 200 字元（門檻是「>200」）不截斷
            ("exactly_200_not_truncated", "y" * 200, "y" * 200),
            # 含中文／引號／換行／emoji 的值原樣寫入（ensure_ascii=False）
            ("special_characters_preserved", "含「引號」與換行\n特殊字元 🎉", "含「引號」與換行\n特殊字元 🎉"),
        )
        for name, value, expected in cases:
            with self.subTest(name):
                run_cli("set-test", "1", "--passed", "--evidence", value)
                self.assertEqual(self.read_events("r5")[-1]["args"]["evidence"], expected)


class Tier01TelemetryTest(unittest.TestCase):
    """event（Tier 1 事件留痕）與 tier0（Tier 0 一行留痕）子命令。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    @contextlib.contextmanager
    def sandbox(self, name):
        """每個 subTest 獨立目錄（git repo／run 目錄互不污染）。"""
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(self.tmp.name)

    def read_events(self, run_id):
        with open(os.path.join("run", f"{run_id}.events.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def read_tier0(self):
        with open(os.path.join("run", "tier0.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_event_without_state_file_appends_in_order(self):
        """Tier 1 場景：eval_state.json 不存在也能寫事件（不經 load()）。"""
        self.assertFalse(os.path.exists("eval_state.json"))
        run_cli("event", "t1-run", "hitl_confirmed", "--note", "1 task／4 items")
        run_cli("event", "t1-run", "item_reviewed")
        events = self.read_events("t1-run")
        self.assertEqual([e["cmd"] for e in events], ["hitl_confirmed", "item_reviewed"])
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

    def test_session_keys_recorded_into_manifest(self):
        sess = "CLAUDE_CODE_SESSION_ID"
        cfg = "CLAUDE_CONFIG_DIR"
        init_ev = ("event", "t1-run", "init")
        absent = {"session_id": None, "config_dir": None}  # None＝鍵必須不存在
        cases = (
            ("event_init_records_keys", {}, {sess: "sess-abc", cfg: "/cfg/dir"}, (), init_ev,
             {"session_id": "sess-abc", "config_dir": "/cfg/dir"}),
            ("event_init_defaults_config_dir_to_home_claude", {}, {sess: "sess-abc"}, (cfg,), init_ev,
             {"session_id": "sess-abc", "config_dir": os.path.expanduser("~/.claude")}),
            ("event_init_without_session_env_leaves_manifest_untouched", {}, {}, (sess,), init_ev, absent),
            ("event_init_does_not_overwrite_existing", {"session_id": "old", "config_dir": "/old"},
             {sess: "new", cfg: "/new"}, (), init_ev, {"session_id": "old", "config_dir": "/old"}),
            ("non_init_event_does_not_record", {}, {sess: "sess-abc"}, (),
             ("event", "t1-run", "hitl_confirmed"), absent),
            ("tier2_init_records_keys", {}, {sess: "sess-t2", cfg: "/cfg"}, (),
             ("init", "--run-id", "t1-run"), {"session_id": "sess-t2", "config_dir": "/cfg"}),
        )
        for name, extra, env, drop, argv, expected in cases:
            with self.subTest(name), self.sandbox(name):
                before = self.write_manifest("t1-run", **extra)
                with mock.patch.dict(os.environ, env, clear=False):
                    for key in drop:
                        os.environ.pop(key, None)
                    run_cli(*argv)
                after = self.read_manifest("t1-run")
                for key, value in expected.items():
                    if value is None:
                        self.assertNotIn(key, after)
                    else:
                        self.assertEqual(after[key], value, key)
                kept = before if argv[0] == "event" else {}
                for key, value in kept.items():
                    self.assertEqual(after[key], value, key)
                self.assertEqual(len(self.read_events("t1-run")), 1)

    def test_event_init_without_manifest_still_appends_event(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "sess-abc"}, clear=False):
            with mock.patch("sys.stderr", stderr):
                run_cli("event", "t1-run", "init")
        self.assertEqual([e["cmd"] for e in self.read_events("t1-run")], ["init"])
        self.assertTrue(stderr.getvalue())  # 有 warning
        self.assertFalse(os.path.exists(os.path.join("run", "t1-run.json")))

    # --- tier0 自算行數（item 13.3）---
    # 有意的行為變更（非改弱測試）：Tier 0 直寫無 gate，自報行數從未被核對。新契約自算並
    # 機械執行 CLAUDE.md 的檔數／行數上限，故在真實 git fixture 上驗新契約。

    def git(self, *args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    def git_repo(self):
        """在 cwd 建一個有 baseline commit 的 git repo（tier0 自算需要 git diff HEAD）。"""
        self.git("init", "-q")
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        self.write_lines("seed.txt", 1)
        self.git("add", "seed.txt")
        self.git("commit", "-q", "-m", "baseline")

    def write_lines(self, name, lines, prefix="l"):
        os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
        with open(name, "w", encoding="utf-8") as f:
            f.write("".join(f"{prefix}{i}\n" for i in range(lines)))

    def committed(self, *names):
        for name in names:
            if not os.path.exists(name):
                self.write_lines(name, 1, "x")
            self.git("add", name)
        self.git("commit", "-q", "-m", "add " + ",".join(names))

    def test_tier0_appends_entries_with_verified_lines(self):
        """新契約：lines 來自 git diff 實得，並多記 lines_verified／per_file_lines；留痕僅追加。"""
        self.git_repo()
        self.write_lines("a.py", 1, "x")
        self.committed("a.py")
        self.write_lines("a.py", 8, "line")  # 1 行刪 + 8 行增 = 9
        self.write_lines("b.md", 3, "m")  # 未追蹤：3 行全新增
        run_cli("tier0", "--summary", "文案微調", "--files", "a.py, b.md", "--lines", "12")
        entries = self.read_tier0()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(
            set(e), {"ts", "summary", "files", "lines", "lines_verified", "per_file_lines"}
        )
        self.assertEqual(e["summary"], "文案微調")
        self.assertEqual(e["files"], ["a.py", "b.md"])
        self.assertEqual(e["lines"], 12)
        self.assertTrue(e["lines_verified"])
        self.assertEqual(e["per_file_lines"], {"a.py": 9, "b.md": 3})
        run_cli("tier0", "--summary", "第二筆", "--files", "b.md", "--lines", "3")
        self.assertEqual([x["summary"] for x in self.read_tier0()], ["文案微調", "第二筆"])

    def test_tier0_accepts_boundary_and_deleted_file(self):
        def three_files_at_eighty():
            names = [f"m{i}.txt" for i in range(3)]
            for name, n in zip(names, (30, 30, 20)):
                self.write_lines(name, n)
            return names, 80, dict(zip(names, (30, 30, 20)))

        def deleted_file():  # 🟡-3：合法刪檔（工作區已無、git diff 看得到）須能留痕
            self.write_lines("gone.txt", 3)
            self.committed("gone.txt")
            os.remove("gone.txt")
            return ["gone.txt"], 3, {"gone.txt": 3}

        for name, build in (
            ("three_files_at_eighty_lines", three_files_at_eighty),
            ("deleted_file", deleted_file),
        ):
            with self.subTest(name), self.sandbox(name):
                self.git_repo()
                names, lines, per_file = build()
                run_cli("tier0", "--summary", "s", "--files", ",".join(names), "--lines", str(lines))
                e = self.read_tier0()[0]
                self.assertEqual(e["files"], names)
                self.assertEqual(e["lines"], lines)
                self.assertEqual(e["per_file_lines"], per_file)

    def test_tier0_rejections_leave_no_entry(self):
        def mismatch():
            self.git_repo()
            self.write_lines("a.py", 1, "x")
            self.committed("a.py")
            self.write_lines("a.py", 8, "line")

        def over_budget():
            self.git_repo()
            self.write_lines("big.txt", 81)

        def binary():  # 🟡-2：二進位 numstat 為 `-`，以 0 計會讓任意大小改動偷渡 → 直接拒絕
            self.git_repo()
            with open("b.bin", "wb") as f:
                f.write(b"\x00" * 16)
            self.committed("b.bin")
            with open("b.bin", "wb") as f:
                f.write(b"\x01" * 5000)

        def directory():  # 🟡-B：目錄會讓檔數上限失效 → 拒絕，要求逐檔列出
            self.git_repo()
            for i in range(5):
                self.write_lines(f"d/f{i}.txt", 1, "x")
            self.committed("d")
            for i in range(5):
                self.write_lines(f"d/f{i}.txt", 1, "changed")

        def outside_git():  # 非 git 工作區 → 拒絕記帳（不靜默留痕）
            self.write_lines("a.py", 1, "x")

        # (名稱, 準備, summary, files, 自報行數, 預期 exit code, stderr 關鍵字)
        cases = (
            ("blank_summary", lambda: None, "  ", "a.py", "1", None, ()),
            # 核心：自報與實得不符 → 拒絕，並同時印兩個數字
            ("self_reported_mismatch", mismatch, "s", "a.py", "999", 1, ("自報 999", "實得 9")),
            ("over_line_budget", over_budget, "s", "big.txt", "81", None, ("合計 80 行",)),
            ("binary_change", binary, "s", "b.bin", "0", None, ("b.bin",)),
            ("directory_pathspec", directory, "s", "d", "10", None, ("不接受目錄",)),
            ("missing_file", self.git_repo, "s", "nope.py", "1", None, ("nope.py",)),
            ("outside_git_repo", outside_git, "s", "a.py", "1", None, ("不在 git 工作區",)),
        )
        for name, prepare, summary, files, lines, code, fragments in cases:
            with self.subTest(name), self.sandbox(name):
                prepare()
                with contextlib.redirect_stderr(io.StringIO()) as buf:
                    with self.assertRaises(SystemExit) as cm:
                        run_cli("tier0", "--summary", summary, "--files", files, "--lines", lines)
                if code is None:
                    self.assertTrue(cm.exception.code)
                else:
                    self.assertEqual(cm.exception.code, code)
                for fragment in fragments:
                    self.assertIn(fragment, buf.getvalue())
                self.assertFalse(os.path.exists(os.path.join("run", "tier0.jsonl")))

    def test_tier0_real_cli_rejects_cross_file_bypass(self):
        """共用入口與相容入口均拒絕 6 檔（>3，含不提供豁免旗標）及已移除旗標，不改歷史留痕。"""
        self.git_repo()
        names = [f"m{i}.txt" for i in range(6)]
        for name in names:
            self.write_lines(name, 1, "x")
        Path("run").mkdir()
        log = Path("run/tier0.jsonl")
        history = '{"summary":"舊記錄","mechanical":true}\n'
        log.write_text(history, encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        for entry in (".agent-flow/scripts/eval_state.py", ".claude/hooks/eval_state.py"):
            for extra, expected in (([], "重新分級"), (["--mechanical"], "unrecognized arguments")):
                with self.subTest(entry=entry, extra=extra):
                    result = subprocess.run(
                        [sys.executable, str(root / entry), "tier0", "--summary", "混合修改",
                         "--files", ",".join(names), "--lines", "6", *extra],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)
                    self.assertEqual(log.read_text(encoding="utf-8"), history)


class HitlConfirmTest(unittest.TestCase):
    """item 13.2 契約：hitl-confirm 寫三欄並推進 phase；前置不過一律 exit 1 不寫檔。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("run", exist_ok=True)
        # 釘住「有人看管」：dispatch.py 與評測都是 headless（ATTENDED=0），不釘的話成功路徑會被
        # 「無人看管拒絕」擋掉而誤紅。需要驗無人看管行為的案例自行覆寫。
        # 本釘樁是否承重只能靠在 headless 環境跑整套來驗（拿掉釘樁、ATTENDED=0 → 2 failed）。
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    RID = "2026-10-03-probe"

    def manifest_path(self):
        return os.path.join("run", f"{self.RID}.json")

    def write_manifest(self, **over):
        m = {
            "run_id": self.RID,
            "tier": 1,
            "status": "in_progress",
            "phase": "init",
            "spec_inline": "一句需求",
            "task_file": "task/2026-10-03.md",
            "hitl_confirmed_at": None,
            "hitl_rulings": None,
        }
        m.update(over)
        with open(self.manifest_path(), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        return m

    def read_manifest(self):
        with open(self.manifest_path(), encoding="utf-8") as f:
            return json.load(f)

    def read_events(self):
        path = os.path.join("run", f"{self.RID}.events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_confirms_and_advances_phase(self):
        self.write_manifest()
        run_cli("hitl-confirm", self.RID, "--note", "確認 2 tasks／4 items", "--rulings", "2")
        m = self.read_manifest()
        self.assertEqual(m["phase"], "decomposed")
        self.assertEqual(m["hitl_rulings"], 2)
        self.assertIn("確認 2 tasks／4 items", m["hitl_confirmed_at"])
        self.assertRegex(m["hitl_confirmed_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — ")
        self.assertEqual([e["cmd"] for e in self.read_events()], ["hitl_confirmed"])

    def test_confirm_defaults_and_attended_flag(self):
        env_without_flag = {
            k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ATTENDED"
        }
        cases = (
            # 未給 --rulings 預設 0；互動 session（ATTENDED=1）留痕 hitl_attended
            ("attended", {"CLAUDE_CODE_SESSION_ATTENDED": "1"}, False, True),
            # 環境未提供該變數（如直接在終端跑）→ 不擋，但留痕為 None 供稽核
            ("missing_env_recorded_as_unknown", env_without_flag, True, None),
        )
        for name, env, clear, attended in cases:
            with self.subTest(name):
                self.write_manifest()
                with mock.patch.dict(os.environ, env, clear=clear):
                    run_cli("hitl-confirm", self.RID, "--note", "確認計畫")
                m = self.read_manifest()
                self.assertEqual(m["phase"], "decomposed")
                self.assertEqual(m["hitl_rulings"], 0)
                self.assertIs(m["hitl_attended"], attended)

    def test_refusals_exit_1_and_leave_manifest_untouched(self):
        # (名稱, manifest 覆寫, run id, 環境覆寫, --note, stderr 關鍵字)
        cases = (
            ("blank_note", {}, None, {}, "   ", ["--note 不可為空"]),
            ("missing_task_file", {"task_file": None}, None, {}, "x", ["HITL 掛在分拆之後"]),
            ("intent_gate", {"spec_inline": None, "spec_path": None}, None, {}, "x", ["intent gate"]),
            ("non_in_progress", {"status": "completed"}, None, {}, "x", ["非 in_progress"]),
            (
                "existing_confirmation_not_overwritten",
                {"hitl_confirmed_at": "2026-10-01 09:00 — 原確認"},
                None,
                {},
                "新確認",
                ["已有 hitl_confirmed_at", "原確認"],
            ),
            (
                # 出生證：headless 評測中模型自行確認後動工
                "unattended_session_cannot_self_confirm",
                {},
                None,
                {"CLAUDE_CODE_SESSION_ATTENDED": "0"},
                "自己確認",
                ["無人看管", "停在這一步"],
            ),
            # 🟡-1：phase 已 ≥ decomposed 時拒絕，不倒退
            ("phase_cannot_be_rolled_back", {"phase": "completed"}, None, {}, "x", ["不可把已前進的 phase 倒退"]),
            ("unknown_run_id", None, "2026-01-01-nope", {}, "x", ["不存在"]),
            ("invalid_json_manifest", "{not json", None, {}, "x", ["非合法 JSON"]),
        )
        for name, over, rid, env, note, fragments in cases:
            with self.subTest(name):
                if isinstance(over, str):
                    with open(self.manifest_path(), "w", encoding="utf-8") as f:
                        f.write(over)
                elif over is not None:
                    self.write_manifest(**over)
                path = self.manifest_path()
                before = open(path, encoding="utf-8").read() if os.path.exists(path) else None
                with mock.patch.dict(os.environ, env):
                    with io.StringIO() as buf, contextlib.redirect_stderr(buf):
                        with self.assertRaises(SystemExit) as cm:
                            run_cli("hitl-confirm", rid or self.RID, "--note", note)
                        err = buf.getvalue()
                self.assertEqual(cm.exception.code, 1)
                for fragment in fragments:
                    self.assertIn(fragment, err)
                # 🟡-4：拒絕訊息不印環境變數名
                self.assertNotIn("CLAUDE_CODE_SESSION_ATTENDED", err)
                after = open(path, encoding="utf-8").read() if os.path.exists(path) else None
                self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
