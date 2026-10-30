"""Public helper and real subprocess coverage for confirmed item accounting."""

import copy
import datetime
import shlex
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agent-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import item_accounting as accounting
from flow_rules import RuleViolation

TASK = "## Task 1: demo\n- [ ] 1.1 first\n- [ ] 1.2 second\n"


class ItemAccountingTest(unittest.TestCase):
    def manifest(self):
        return dict(
            tier=2,
            item_accounting_required=True,
            hitl_confirmed_at="confirmed",
            status="in_progress",
        )

    def confirmed(self):
        manifest = self.manifest()
        accounting.confirm_plan(manifest, TASK)
        return manifest

    def test_confirm_identity_and_checkbox_is_not_delivery(self):
        manifest = self.confirmed()
        self.assertEqual(
            manifest["item_plan"]["items"],
            [
                dict(id="1.1", task_id="1", summary="first"),
                dict(id="1.2", task_id="1", summary="second"),
            ],
        )
        accounting.validate_plan(manifest, TASK.replace("[ ]", "[x]"))
        with self.assertRaises(RuleViolation):
            accounting.validate_results(manifest)
        with self.assertRaises(RuleViolation):
            accounting.confirm_plan(manifest, TASK)

    def test_empty_duplicate_renamed_deleted_or_moved_items_refused(self):
        for task in ("", TASK + "- [ ] 1.1 duplicate\n", TASK.replace("1.2", "2.2")):
            with self.subTest(task=task), self.assertRaises(RuleViolation):
                accounting.confirm_plan(self.manifest(), task)
        manifest = self.confirmed()
        for task in (TASK.replace("second", "renamed"), TASK.split("- [ ] 1.2")[0]):
            with self.subTest(task=task), self.assertRaises(RuleViolation):
                accounting.validate_plan(manifest, task)

    def test_no_hitl_or_legacy_plan_cannot_record_delivery(self):
        with self.assertRaises(RuleViolation):
            accounting.confirm_plan({}, TASK)
        legacy = dict(tier=1, hitl_confirmed_at="old", status="in_progress")
        with self.assertRaises(RuleViolation):
            accounting.confirm_plan(legacy, TASK)
        with self.assertRaises(RuleViolation):
            accounting.record_result(legacy, TASK, "1.1", "delivered", files=["a.py"], evidence="existing:tests/test_a.py:test_a")
        self.assertNotIn("item_plan", legacy)

    def test_delivery_pending_and_user_ruling(self):
        manifest = self.confirmed()
        accounting.record_result(manifest, TASK, "1.1", "delivered", files=["a.py"], evidence="existing:tests/test_a.py:test_a")
        accounting.record_result(
            manifest, TASK, "1.2", "pending", reason="等待範圍裁示"
        )
        self.assertEqual(manifest["status"], "paused")
        self.assertEqual(
            accounting.validate_results(manifest, ["a.py"], allow_pending=True), ["1.2"]
        )
        with self.assertRaises(RuleViolation):
            accounting.validate_results(manifest, ["a.py"])
        ruling = dict(
            actor="user",
            text="移除 1.2",
            at="2026-10-19T10:00:00+08:00",
            source="user message 5",
        )
        accounting.record_result(manifest, TASK, "1.2", "removed", ruling=ruling)
        self.assertEqual(manifest["item_results"]["1.2"]["ruling"], ruling)
        self.assertEqual(accounting.validate_results(manifest, ["a.py"]), [])
        self.assertEqual(manifest["status"], "in_progress")
        with self.assertRaises(RuleViolation):
            accounting.validate_results(manifest, ["different.py"])
        with self.assertRaises(RuleViolation):
            accounting.validate_plan(manifest, TASK.split("- [ ] 1.2")[0])

    def test_invalid_results_do_not_mutate_manifest(self):
        cases = [
            ("1.1", "delivered", dict(files=[], evidence="ran:x")),
            ("1.1", "delivered", dict(files=["../outside"], evidence="ran:x")),
            ("1.1", "delivered", dict(files=["a", "a"], evidence="ran:x")),
            ("1.1", "pending", dict(reason=" ")),
            ("9.9", "delivered", dict(files=["a"], evidence="ran:x")),
            ("1.1", "delivered", dict(files=["a"])),
            ("1.1", "delivered", dict(files=["a"], evidence="new:test_x")),
            (
                "1.1",
                "removed",
                dict(ruling=dict(actor="agent", text="x", at="now", source="agent")),
            ),
        ]
        ruling = dict(
            actor="user", text="移除", at="2026-10-19T00:00:00Z", source="user message"
        )
        for replacement in (
            dict(ruling, at="today"),
            dict(ruling, at="2026-10-19T00:00:00"),
            dict(ruling, source="assistant message"),
            dict(ruling, source=" assistant message 5"),
            dict(ruling, source="  AsSiStAnT message 5  "),
            dict(ruling, source="  AGENT recommendation"),
        ):
            cases.append(("1.1", "removed", dict(ruling=replacement)))
        for key in ruling:
            missing = dict(ruling)
            del missing[key]
            cases.append(("1.1", "removed", dict(ruling=missing)))
        for item_id, status, arguments in cases:
            manifest = self.confirmed()
            before = copy.deepcopy(manifest)
            with self.subTest(arguments=arguments), self.assertRaises(RuleViolation):
                accounting.record_result(manifest, TASK, item_id, status, **arguments)
            self.assertEqual(manifest, before)
        manifest = self.confirmed()
        with self.assertRaises(RuleViolation):
            accounting.record_partial(manifest, TASK, ["1.1"], ruling)
        self.assertNotIn("partial_acceptance", manifest)

    def test_cli_diagnostics_formats_and_filtering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run").mkdir()
            (root / "task.md").write_text(TASK)
            path = root / "run/new.json"
            manifest = self.confirmed()
            manifest["task_file"] = "task.md"
            path.write_text(json.dumps(manifest))

            def cli(*arguments):
                return subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "item_accounting.py"),
                        "--run-id",
                        "new",
                        *arguments,
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )

            for output_format in ("text", "json"):
                before = path.read_text()
                result = cli(
                    "--log-format",
                    output_format,
                    "remove",
                    "1.1",
                    "--ruling-file",
                    "missing.json",
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                lines = result.stderr.splitlines()
                self.assertEqual(len(lines), 1)
                fields = (
                    json.loads(lines[0])
                    if output_format == "json"
                    else dict(part.split("=", 1) for part in shlex.split(lines[0]))
                )
                self.assertEqual(fields["event"], "item_accounting.failed")
                self.assertEqual(fields["level"], "ERROR")
                self.assertEqual(fields["outcome"], "failed")
                self.assertEqual(fields["run_id"], "new")
                self.assertEqual(str(fields["exit_code"]), "2")
                self.assertTrue(fields["logger"])
                self.assertTrue(fields["message"])
                self.assertEqual(
                    datetime.datetime.fromisoformat(fields["timestamp"]).utcoffset(),
                    datetime.timedelta(0),
                )
                self.assertEqual(path.read_text(), before)
            result = cli("deliver", "1.1", "--files", "a.py", "--evidence", "ran:pytest", "--log-format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            fields = json.loads(result.stderr)
            self.assertEqual(
                (fields["event"], fields["level"]), ("item_accounting.recorded", "INFO")
            )
            result = cli("--log-level", "ERROR", "deliver", "1.2", "--files", "b.py", "--evidence", "ran:pytest")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                json.loads(path.read_text())["item_results"]["1.2"]["files"], ["b.py"]
            )

    def test_real_cli_tier1_and_tier2_and_failed_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run").mkdir()
            (root / "task.md").write_text(TASK)
            environment = dict(os.environ, CLAUDE_CODE_SESSION_ATTENDED="1")

            def cli(script, *arguments):
                return subprocess.run(
                    [sys.executable, str(SCRIPTS / script), *arguments],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                )

            result = cli(
                "eval_state.py",
                "init-run",
                "--run-id",
                "new",
                "--harness",
                "codex",
                "--spec-inline",
                "spec",
                "--tier-rationale",
                "simple",
                "--test-command",
                "true",
                "--task-file",
                "task.md",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = cli("eval_state.py", "hitl-confirm", "new", "--note", "使用者確認")
            self.assertEqual(result.returncode, 0, result.stderr)
            path = root / "run/new.json"
            manifest = json.loads(path.read_text())
            self.assertEqual(len(manifest["item_plan"]["items"]), 2)
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "deliver",
                "1.1",
                "--files",
                "a.py",
                "--evidence",
                "ran:pytest",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "pending",
                "1.2",
                "--reason",
                "使用者裁示待確認",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            before = path.read_text()
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "remove",
                "1.2",
                "--ruling-file",
                "missing.json",
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_text(), before)
            ruling_path = root / "ruling.json"
            ruling_path.write_text(
                json.dumps(
                    dict(
                        actor="user",
                        text="接受部分交付，1.2 暫不交付",
                        at="2026-10-19T10:00:00+08:00",
                        source="user message 6",
                    )
                )
            )
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "partial",
                "--items",
                "1.2",
                "--ruling-file",
                "ruling.json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(path.read_text())["partial_acceptance"]["item_ids"], ["1.2"]
            )
            self.assertEqual(json.loads(path.read_text())["status"], "in_progress")
            environment["CLAUDE_CODE_SESSION_ATTENDED"] = "0"
            before = path.read_text()
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "remove",
                "1.2",
                "--ruling-file",
                "ruling.json",
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_text(), before)
            environment["CLAUDE_CODE_SESSION_ATTENDED"] = "1"
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "pending",
                "1.2",
                "--reason",
                "移除裁示確認中",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = cli(
                "item_accounting.py",
                "--run-id",
                "new",
                "remove",
                "1.2",
                "--ruling-file",
                "ruling.json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(path.read_text())["item_results"]["1.2"]["status"], "removed"
            )
            self.assertEqual(json.loads(path.read_text())["status"], "in_progress")
            tier2 = dict(
                tier=2,
                item_accounting_required=True,
                task_file="task.md",
                hitl_confirmed_at="user confirmed",
                status="in_progress",
            )
            (root / "run/two.json").write_text(json.dumps(tier2))
            result = cli("item_accounting.py", "--run-id", "two", "confirm-plan")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                len(
                    json.loads((root / "run/two.json").read_text())["item_plan"][
                        "items"
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
