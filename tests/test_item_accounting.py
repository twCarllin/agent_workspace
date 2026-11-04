"""Public helper and real subprocess coverage for confirmed item accounting."""

import copy
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
                "--observed",
                "使用者看到結果",
                "--observed-evidence",
                "ran:real entry ok",
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


class ObservedEvidenceGateTest(unittest.TestCase):
    """2026.11.05.1 起交付必附使用者可觀察結果與真實入口證據；舊版 manifest 不受影響。"""

    def test_real_cli_requires_observed_and_existing_file(self):
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

            init = cli(
                "eval_state.py", "init-run", "--run-id", "obs", "--harness", "codex",
                "--spec-inline", "spec", "--tier-rationale", "simple",
                "--test-command", "true", "--task-file", "task.md",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertEqual(
                cli("eval_state.py", "hitl-confirm", "obs", "--note", "ok").returncode, 0
            )
            base = ("item_accounting.py", "--run-id", "obs", "deliver", "1.1",
                    "--files", "a.py", "--evidence", "ran:pytest")
            missing = cli(*base)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("--observed", missing.stderr)
            no_file = cli(*base, "--observed", "看到表格", "--observed-evidence", "file:run/none.png")
            self.assertEqual(no_file.returncode, 2)
            self.assertIn("證據檔不存在", no_file.stderr)
            bad = cli(*base, "--observed", "看到表格", "--observed-evidence", "guess:x")
            self.assertEqual(bad.returncode, 2)
            manifest = json.loads((root / "run/obs.json").read_text())
            self.assertEqual(manifest["item_results"], {})
            (root / "run/shot.png").write_bytes(b"png")
            for evidence in ("file:run/shot.png", "pending-manual:開列表頁看欄位"):
                ok = cli(*base, "--observed", "看到表格", "--observed-evidence", evidence)
                self.assertEqual(ok.returncode, 0, ok.stderr)
                result = json.loads((root / "run/obs.json").read_text())["item_results"]["1.1"]
                self.assertEqual(result["observed"], "看到表格")
                self.assertEqual(result["observed_evidence"], evidence)

    def test_validate_results_enforces_observed_only_for_new_versions(self):
        old = dict(tier=1, item_accounting_required=True, hitl_confirmed_at="t",
                   status="in_progress", framework_version="2026.10.19.1")
        accounting.confirm_plan(old, TASK)
        accounting.record_result(old, TASK, "1.1", "delivered", files=["a.py"], evidence="ran:x")
        accounting.record_result(old, TASK, "1.2", "delivered", files=["b.py"], evidence="ran:x")
        self.assertEqual(accounting.validate_results(old), [])
        new = dict(old, framework_version="2026.11.05.1", item_results=copy.deepcopy(old["item_results"]))
        with self.assertRaises(RuleViolation):
            accounting.validate_results(new)
        with self.assertRaises(RuleViolation):
            accounting.record_result(new, TASK, "1.1", "delivered", files=["a.py"], evidence="ran:x")
        accounting.record_result(new, TASK, "1.1", "delivered", files=["a.py"], evidence="ran:x",
                                 observed="看到結果", observed_evidence="ran:curl /list -> 200 含新欄位")
        accounting.record_result(new, TASK, "1.2", "delivered", files=["b.py"], evidence="ran:x",
                                 observed="看到頁面", observed_evidence="pending-manual:開頁面捲到底")
        self.assertEqual(accounting.validate_results(new), [])
