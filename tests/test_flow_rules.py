"""Shared rules have no hook side effects; adapters preserve the same reason."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
import flow_rules
import run_evidence
import eval_gates


class SharedRulesTest(unittest.TestCase):
    def test_rules_and_hook_preserve_reason_without_core_side_effects(self):
        credentials = dict(
            local_test_passed=True,
            local_test_evidence="command passed",
            review_reds=0,
            verify_passed=True,
        )
        flow_rules.validate_credentials(credentials, "fixture")
        for key, value in (
            ("local_test_passed", False),
            ("local_test_evidence", ""),
            ("review_reds", None),
            ("verify_passed", False),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                previous = os.getcwd()
                os.chdir(tmp)
                try:
                    Path("run").mkdir()
                    out, err = io.StringIO(), io.StringIO()
                    invalid = {**credentials, key: value}
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(
                        err
                    ):
                        with self.assertRaises(flow_rules.RuleViolation) as failure:
                            flow_rules.validate_credentials(invalid, "fixture")
                    self.assertEqual(out.getvalue(), "")
                    self.assertEqual(err.getvalue(), "")
                    self.assertEqual(list(Path("run").iterdir()), [])
                    with contextlib.redirect_stderr(err):
                        with self.assertRaises(SystemExit) as blocked:
                            eval_gates._validate_credentials(invalid, "fixture")
                    self.assertEqual(blocked.exception.code, 2)
                    self.assertEqual(
                        err.getvalue(),
                        "[gate-check] BLOCK: " + str(failure.exception) + "\n",
                    )
                finally:
                    os.chdir(previous)

    def test_phase_and_filename_compatibility(self):
        for name, valid in (
            ("run/demo.json", True),
            ("run/demo-item-1.json", True),
            ("run/demo.context.json", False),
            ("run/demo.context.writer.json", False),
            ("run/demo-context.json", True),
            ("run/demo.contextual.json", True),
            ("run/demo.eval.json", False),
            ("run/demo.test_baseline.json", False),
        ):
            self.assertEqual(bool(flow_rules.MANIFEST_RE.fullmatch(name)), valid)

    def test_state_failure_true_subprocess_core_and_compatibility_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"run_id": "demo", "sub_tasks": [{"id": 1, "status": "failed"}]}
            Path(tmp, "eval_state.json").write_text(json.dumps(state))
            for entry in (
                SCRIPTS / "eval_state.py",
                ROOT / ".claude/hooks/eval_state.py",
            ):
                result = subprocess.run(
                    [sys.executable, str(entry), "archive"],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("status 非 passed", result.stderr)
                self.assertFalse(Path(tmp, "run/demo.events.jsonl").exists())
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(flow_rules.RuleViolation):
                    flow_rules.validate_state(state, "fixture", require_passed=True)
            self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_evidence_service_failure_is_exception_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("run").mkdir()
                Path("run/demo.json").write_text(
                    json.dumps(
                        {
                            "run_id": "demo",
                            "spec_inline": "task",
                            "status": "ready_to_commit",
                            "tier": 1,
                            "evidence_schema": 2,
                        }
                    )
                )
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    with self.assertRaises(flow_rules.RuleViolation) as failure:
                        run_evidence.check_manifest("run/demo.json", set())
                self.assertIn("缺通過的收尾驗證快照", str(failure.exception))
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
                self.assertFalse(Path("run/gate_hits.log").exists())
                Path("run/list.json").write_text("[]")
                with self.assertRaisesRegex(flow_rules.RuleViolation, "不是 JSON 物件"):
                    run_evidence.load_json("run/list.json")
            finally:
                os.chdir(previous)
