"""Replay documented preparation through real state and hook entry points."""

import json
from itertools import product
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent-flow/scripts"


class FlowTransitionsTest(unittest.TestCase):
    def test_documented_tier2_preparation_keeps_gate_until_helper_confirms(self):
        preparation = (ROOT / "skills/eval-flow/references/tier2-prep.md").read_text()
        phase_line = next(
            line
            for line in preparation.splitlines()
            if "`sub_tasks`" in line and "`phase`" in line
        )
        resume_line = next(
            line
            for line in (ROOT / "skills/eval-flow-resume/references/legacy-cycle.md")
            .read_text()
            .splitlines()
            if line.startswith("| `init` |")
        )
        for entry, instruction in product(
            (SCRIPTS, ROOT / ".claude/hooks"), (phase_line, resume_line)
        ):
            phase = re.search(r'`phase`.*?`"([^"]+)"`', instruction).group(1)
            with self.subTest(
                entry=str(entry), instruction=instruction
            ), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "run").mkdir()
                (root / "task.md").write_text("## Task 1: sample\n- [ ] 1.1 sample\n")
                manifest_path = root / "run/sample.json"
                manifest_path.write_text(
                    json.dumps(
                        dict(
                            run_id="sample",
                            tier=2,
                            status="in_progress",
                            phase=phase,
                            spec_inline="sample",
                            task_file="task.md",
                            evidence_schema=2,
                            item_accounting_required=True,
                        )
                    )
                )
                (root / "eval_state.json").write_text(
                    json.dumps(
                        dict(run_id="sample", sub_tasks=[dict(id=1, status="pending")])
                    )
                )
                env = {**os.environ, "CLAUDE_CODE_SESSION_ATTENDED": "1"}
                payload = json.dumps(
                    dict(
                        cwd=str(root),
                        tool_name="Write",
                        tool_input=dict(file_path="source.py"),
                    )
                )
                before = subprocess.run(
                    [sys.executable, str(entry / "eval_gates.py"), "--hook"],
                    cwd=root,
                    env=env,
                    input=payload,
                    text=True,
                    capture_output=True,
                )
                confirmed = subprocess.run(
                    [
                        sys.executable,
                        str(entry / "eval_state.py"),
                        "hitl-confirm",
                        "sample",
                        "--note",
                        "fixture user confirmed sample plan",
                    ],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    (before.returncode, confirmed.returncode),
                    (2, 0),
                    before.stderr + confirmed.stderr,
                )
                manifest = json.loads(manifest_path.read_text())
                self.assertEqual(manifest["phase"], "decomposed")
                self.assertTrue(manifest["hitl_confirmed_at"])
                self.assertIs(manifest["hitl_attended"], True)
                self.assertEqual(manifest["hitl_rulings"], 0)
                self.assertEqual(
                    manifest["item_plan"]["confirmed_at"], manifest["hitl_confirmed_at"]
                )
                self.assertEqual(manifest["item_plan"]["items"][0]["id"], "1.1")
                events = [
                    json.loads(line)
                    for line in (root / "run/sample.events.jsonl")
                    .read_text()
                    .splitlines()
                ]
                self.assertEqual([event["cmd"] for event in events], ["hitl_confirmed"])
                self.assertEqual(
                    events[0]["args"]["note"], "fixture user confirmed sample plan"
                )
                self.assertEqual(events[0]["args"]["rulings"], 0)
                after = subprocess.run(
                    [sys.executable, str(entry / "eval_gates.py"), "--hook"],
                    cwd=root,
                    env=env,
                    input=payload,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(after.returncode, 0, after.stderr)
                frozen = manifest_path.read_bytes()
                repeated = subprocess.run(
                    [
                        sys.executable,
                        str(entry / "item_accounting.py"),
                        "--run-id",
                        "sample",
                        "confirm-plan",
                    ],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(repeated.returncode, 2, repeated.stderr)
                self.assertEqual(frozen, manifest_path.read_bytes())

    def test_next_keeps_unstarted_legacy_runs_at_plan(self):
        for tier, policy in ((1, None), (2, None), (1, "adaptive-v1")):
            with self.subTest(
                tier=tier, policy=policy
            ), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "run").mkdir()
                (root / "run/sample.json").write_text(
                    json.dumps(
                        dict(
                            run_id="sample",
                            tier=tier,
                            tier1_policy=policy,
                            status="in_progress",
                            phase="init",
                            spec_inline="sample",
                            task_file="task.md",
                            evidence_schema=2,
                            test_command="python3 -c pass",
                        )
                    )
                )
                payload = json.dumps(
                    dict(
                        cwd=str(root),
                        tool_name="Write",
                        tool_input=dict(file_path="source.py"),
                    )
                )
                blocked = subprocess.run(
                    [sys.executable, str(SCRIPTS / "eval_gates.py"), "--hook"],
                    cwd=root,
                    input=payload,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(blocked.returncode, 2, blocked.stderr)
                self.assertIn("start-run" if policy else "hitl-confirm", blocked.stderr)
                if tier == 2:
                    (root / "eval_state.json").write_text(
                        json.dumps(
                            dict(
                                run_id="sample",
                                sub_tasks=[dict(id=1, status="pending")],
                            )
                        )
                    )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "flow.py"),
                        "next",
                        "--run-id",
                        "sample",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value["action"], "plan")
                self.assertIsNone(value["command"])
                # Existing manifests without phase still use the recorded legacy inference.
                manifest_path = root / "run/sample.json"
                manifest = json.loads(manifest_path.read_text())
                manifest.pop("phase")
                manifest_path.write_text(json.dumps(manifest))
                legacy = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "flow.py"),
                        "next",
                        "--run-id",
                        "sample",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(
                    json.loads(legacy.stdout)["action"],
                    "resume_task" if tier == 2 else "verify",
                )

    def test_archive_advises_prepare_and_finalize_without_completing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run").mkdir()
            manifest_path = root / "run/sample.json"
            manifest_path.write_text(
                json.dumps(dict(status="in_progress", phase="decomposed"))
            )
            (root / "eval_state.json").write_text(
                json.dumps(
                    dict(
                        run_id="sample",
                        sub_tasks=[
                            dict(
                                id=1,
                                status="passed",
                                local_test_passed=True,
                                local_test_evidence="fixture verified",
                                review_reds=0,
                                verify_passed=True,
                            )
                        ],
                    )
                )
            )
            state_path = root / "eval_state.json"
            valid_state = state_path.read_bytes()
            for step in ("scoring", "done"):
                with self.subTest(step=step):
                    state = json.loads(valid_state)
                    state["sub_tasks"][0].update(step=step, local_test_passed=False)
                    state_path.write_text(json.dumps(state))
                    incomplete = state_path.read_bytes()
                    rejected = subprocess.run(
                        [sys.executable, str(SCRIPTS / "eval_state.py"), "archive"],
                        cwd=root,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(rejected.returncode, 2, rejected.stderr)
                    self.assertEqual(incomplete, state_path.read_bytes())
            state_path.write_bytes(valid_state)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            blocked = subprocess.run(
                [sys.executable, str(SCRIPTS / "eval_gates.py"), "--hook"],
                cwd=root,
                text=True,
                capture_output=True,
                input=json.dumps(
                    dict(
                        cwd=str(root),
                        tool_name="Bash",
                        tool_input=dict(command="git commit -m fixture"),
                    )
                ),
            )
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("prepare", blocked.stderr)
            self.assertIn("finalize", blocked.stderr)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "eval_state.py"), "archive"],
                cwd=root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("prepare", result.stdout)
            self.assertIn("finalize", result.stdout)
            self.assertEqual(
                json.loads(manifest_path.read_text())["status"], "in_progress"
            )
            self.assertFalse((root / "eval_state.json").exists())
            self.assertTrue((root / "run/sample.eval.json").exists())
