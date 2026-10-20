"""Adaptive Tier 1 public CLI contracts in isolated repositories."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent-flow/scripts"


class AdaptiveTier1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        (self.root / "task.md").write_text("## Task 1: demo\n- [ ] 1.1 behavior\n")
        (self.root / "source.py").write_text("value = 1\n")
        self.cli(
            "init-run",
            "--run-id",
            "demo",
            "--harness",
            "codex",
            "--spec-inline",
            "behavior",
            "--tier-rationale",
            "small",
            "--test-command",
            'python3 -c "pass"',
            "--task-file",
            "task.md",
        )

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def cli(self, *args, ok=True, entry=None):
        result = subprocess.run(
            [sys.executable, str(entry or SCRIPTS / "eval_state.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_CODE_SESSION_ATTENDED": "0"},
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def read(self):
        return json.loads((self.root / "run/demo.json").read_text())

    def write(self, manifest):
        (self.root / "run/demo.json").write_text(json.dumps(manifest))

    def start(self, *extra):
        self.cli(
            "start-run", "demo", "--authorization", "user requested behavior", *extra
        )

    def verify(self, command='python3 -c "pass"', ok=True):
        self.cli(
            "--run-id", "demo", "--cmd", command, ok=ok, entry=SCRIPTS / "run_verify.py"
        )

    def review(self, reviewer="self", ok=True):
        return self.cli(
            "review-run",
            "demo",
            "0",
            "--checked-by",
            reviewer,
            "--evidence",
            "behavior verified",
            "--passed",
            ok=ok,
        )

    def test_start_records_authorization_and_freezes_items_without_hitl(self):
        self.start()
        manifest = self.read()
        self.assertEqual(manifest["tier1_policy"], "adaptive-v1")
        self.assertEqual(manifest["phase"], "decomposed")
        self.assertEqual(manifest["plan_authorization"], "user requested behavior")
        self.assertEqual(
            manifest["item_plan"]["confirmed_at"], manifest["plan_recorded_at"]
        )
        self.assertNotIn("hitl_confirmed_at", manifest)
        self.cli(
            "--run-id",
            "demo",
            "deliver",
            "1.1",
            "--files",
            "source.py",
            entry=SCRIPTS / "item_accounting.py",
        )
        (self.root / "task.md").write_text("## Task 1: demo\n- [ ] 1.1 changed\n")
        self.cli(
            "--run-id",
            "demo",
            "deliver",
            "1.1",
            "--files",
            "source.py",
            ok=False,
            entry=SCRIPTS / "item_accounting.py",
        )
        before = self.read()
        self.cli("start-run", "demo", "--authorization", "again", ok=False)
        self.assertEqual(self.read(), before)

    def test_start_rejects_legacy_and_tier2_without_writes(self):
        for tier, policy in ((1, None), (2, "adaptive-v1")):
            with self.subTest(tier=tier):
                manifest = self.read()
                manifest["tier"] = tier
                manifest["tier1_policy"] = policy
                self.write(manifest)
                self.cli(
                    "start-run", "demo", "--authorization", "user request", ok=False
                )
                self.assertEqual(self.read(), manifest)

    def test_self_requires_current_success_and_reasons_only_accumulate(self):
        self.start()
        self.review(ok=False)
        self.verify()
        self.review()
        manifest = self.read()
        self.assertEqual(manifest["checked_by"], "self")
        self.assertTrue(manifest["verify_passed"])
        self.assertEqual(
            manifest["self_review_snapshot"]["snapshot"],
            manifest["verification_commands"][-1]["snapshot"],
        )
        (self.root / "source.py").write_text("value = 2\n")
        self.review(ok=False)
        self.verify('python3 -c "raise SystemExit(1)"', ok=False)
        self.review(ok=False)
        self.verify()
        self.cli("require-review", "demo", "--reason", "coverage gap")
        self.cli("require-review", "demo", "--reason", "impact unclear")
        manifest = self.read()
        self.assertEqual(manifest["review_reasons"], ["coverage gap", "impact unclear"])
        self.assertFalse(manifest["verify_passed"])
        self.assertNotIn("self_review_snapshot", manifest)
        self.verify()
        self.review(ok=False)
        self.review("checker", ok=False)
        self.review("reviewer:manual")

    def test_self_rejects_legacy_tier2_and_compatibility_entry_matches(  # testlint: allow
        self,
    ):
        self.start("--review-reason", "user requests independent review")
        self.verify()
        self.review(ok=False)
        for tier, policy in ((1, None), (2, "adaptive-v1")):
            manifest = self.read()
            manifest.update(tier=tier, tier1_policy=policy, review_reasons=[])
            self.write(manifest)
            self.review(ok=False)
        self.cli(
            "start-run",
            "demo",
            "--authorization",
            "user request",
            ok=False,
            entry=ROOT / ".claude/hooks/eval_state.py",
        )

    def prepare_integration(self, ignored_contract=False):
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Adaptive Test")
        (self.root / ".gitignore").write_text("run/\ntask/\nspec/\n")
        if ignored_contract:
            (self.root / "task").mkdir()
            (self.root / "spec").mkdir()
            (self.root / "task/demo.md").write_text(
                "## Task 1: demo\n- [ ] 1.1 behavior\n  DoD: original behavior\n"
            )
            (self.root / "spec/demo.md").write_text("original requirement\n")
            manifest = self.read()
            manifest.update(task_file="task/demo.md", spec_path="spec/demo.md")
            self.write(manifest)
        self.git("add", ".gitignore", "source.py", "task.md")
        self.git("commit", "-qm", "initial")
        hook = self.root / ".git/hooks/commit-msg"
        hook.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{SCRIPTS / "commit_message_gate.py"}" "$1"\n'
        )
        hook.chmod(0o755)
        self.start()
        (self.root / "source.py").write_text("value = 2\n")
        self.git("add", "source.py")

    def deliver(self):
        self.cli(
            "--run-id",
            "demo",
            "deliver",
            "1.1",
            "--files",
            "source.py",
            entry=SCRIPTS / "item_accounting.py",
        )

    def prepare(self, ok=True):
        return self.cli("prepare", "demo", entry=SCRIPTS / "run_commit.py", ok=ok)

    def commit(self, ok=True):
        result = subprocess.run(
            ["git", "commit", "-qm", "change\n\nRun-Id: demo"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return result

    def tool_gate(self, entry, ok=True, tool_name="Bash"):
        command = " ".join(["git", "commit", "-m", '"change\n\nRun-Id: demo"'])
        result = subprocess.run(
            [sys.executable, str(entry), "--hook"],
            cwd=self.root,
            input=json.dumps(
                {
                    "cwd": str(self.root),
                    "tool_name": tool_name,
                    "tool_input": {
                        "cmd" if tool_name == "exec_command" else "command": command
                    },
                }
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stderr)

    def test_real_self_prepare_commit_finalize_and_status(self):
        self.prepare_integration()
        self.deliver()
        self.verify()
        self.review()
        self.prepare()
        for entry in (SCRIPTS / "eval_gates.py", ROOT / ".claude/hooks/eval_gates.py"):
            self.tool_gate(entry)
            self.tool_gate(entry, tool_name="exec_command")
        self.commit()
        self.cli("finalize", "demo", entry=SCRIPTS / "run_commit.py")
        self.assertEqual(self.read()["status"], "completed")
        result = self.cli(
            "status", "--run-id", "demo", "--json", entry=SCRIPTS / "flow.py"
        )
        self.assertEqual(
            json.loads(result.stdout)["review_evidence"]["review_kind"], "self"
        )

    def test_completion_paths_reject_stale_self_and_unsettled_items(self):
        self.prepare_integration()
        self.verify()
        self.review()
        self.prepare(ok=False)
        self.deliver()
        self.prepare()
        (self.root / "source.py").write_text("value = 3\n")
        self.git("add", "source.py")
        self.prepare(ok=False)
        self.commit(ok=False)
        self.tool_gate(SCRIPTS / "eval_gates.py", ok=False)
        self.tool_gate(SCRIPTS / "eval_gates.py", ok=False, tool_name="exec_command")
        self.verify()
        self.prepare(ok=False)
        result = self.cli(
            "finish",
            "--run-id",
            "demo",
            "--message",
            "change",
            "--files",
            "source.py",
            entry=SCRIPTS / "flow.py",
            ok=False,
        )
        self.assertIn("自查", result.stderr)
        manifest = self.read()
        manifest["status"] = "in_progress"
        self.write(manifest)
        self.review()
        self.verify('python3 -c "raise SystemExit(1)"', ok=False)
        self.prepare(ok=False)
        self.verify()
        self.prepare(ok=False)
        self.review()
        self.cli("require-review", "demo", "--reason", "coverage gap")
        self.verify()
        self.review(ok=False)
        self.prepare(ok=False)
        self.review("reviewer:manual")
        self.prepare()
        self.commit()
        self.cli("finalize", "demo", entry=SCRIPTS / "run_commit.py")

    def test_flow_finish_accepts_self_only_with_matching_source(self):
        self.prepare_integration()
        self.deliver()
        self.verify()
        self.review()
        self.cli(
            "finish",
            "--run-id",
            "demo",
            "--message",
            "change",
            "--files",
            "source.py",
            entry=SCRIPTS / "flow.py",
        )
        self.assertEqual(self.read()["status"], "completed")

    def test_self_binds_pure_documentation_and_index(self):  # testlint: allow
        self.prepare_integration()
        self.deliver()
        (self.root / "README.md").write_text("before\n")
        self.verify()
        self.review()
        (self.root / "README.md").write_text("after\n")
        self.prepare(ok=False)
        self.commit(ok=False)
        self.verify()
        self.prepare(ok=False)
        self.review()
        self.git("reset", "HEAD", "--", "source.py")
        self.prepare(ok=False)
        self.tool_gate(SCRIPTS / "eval_gates.py", ok=False)
        self.tool_gate(SCRIPTS / "eval_gates.py", ok=False, tool_name="exec_command")
        self.git("add", "source.py")
        self.prepare()

    def test_start_preserves_required_review_and_all_in_cannot_self(self):
        self.cli("require-review", "demo", "--reason", "existing concern")
        self.start("--review-reason", "new concern")
        self.assertEqual(
            self.read()["review_reasons"], ["existing concern", "new concern"]
        )
        self.verify()
        self.review(ok=False)
        manifest = self.read()
        manifest.update(review_reasons=[], all_in=True)
        self.write(manifest)
        self.review(ok=False)
        manifest["phase"] = "init"
        self.write(manifest)
        self.cli("start-run", "demo", "--authorization", "user request", ok=False)

    def test_completion_gates_reject_self_for_legacy_and_tier2(self):  # testlint: allow
        self.prepare_integration()
        self.deliver()
        self.verify()
        self.review()
        original = self.read()
        for tier, policy in ((1, None), (2, "adaptive-v1")):
            manifest = dict(original, tier=tier, tier1_policy=policy)
            self.write(manifest)
            self.prepare(ok=False)
            self.commit(ok=False)
            self.tool_gate(SCRIPTS / "eval_gates.py", ok=False)
        self.tool_gate(SCRIPTS / "eval_gates.py", ok=False, tool_name="exec_command")

    def test_failed_independent_review_cannot_return_to_self(self):
        self.start()
        self.verify()
        self.cli(
            "review-run",
            "demo",
            "1",
            "--checked-by",
            "reviewer:manual",
            "--evidence",
            "uncovered failure behavior",
        )
        reasons = self.read()["review_reasons"]
        self.assertTrue(reasons)
        self.verify()
        self.review(ok=False)
        self.review("reviewer:manual")
        self.assertEqual(self.read()["review_reasons"], reasons)
        self.review(ok=False)

    def test_self_binds_ignored_contract_sources(self):  # testlint: allow
        self.prepare_integration(ignored_contract=True)
        self.deliver()
        self.verify()
        self.review()
        changes = (
            (
                "task DoD",
                "task/demo.md",
                "## Task 1: demo\n- [ ] 1.1 behavior\n  DoD: changed behavior\n",
            ),
            ("spec contents", "spec/demo.md", "changed requirement\n"),
            ("spec_inline", None, "changed inline requirement"),
            ("plan_authorization", None, "changed authorization scope"),
            ("spec_path", None, "spec/other.md"),
        )
        (self.root / "spec/other.md").write_text("changed requirement\n")
        for label, path, value in changes:
            with self.subTest(source=label):
                if path:
                    (self.root / path).write_text(value)
                else:
                    manifest = self.read()
                    manifest[label] = value
                    self.write(manifest)
                self.prepare(ok=False)
                self.commit(ok=False)
                self.tool_gate(SCRIPTS / "eval_gates.py", ok=False)
                self.cli(
                    "finish",
                    "--run-id",
                    "demo",
                    "--message",
                    "change",
                    "--files",
                    "source.py",
                    entry=SCRIPTS / "flow.py",
                    ok=False,
                )
                self.verify()
                self.prepare(ok=False)
                self.review()
                self.prepare()
                manifest = self.read()
                manifest["status"] = "in_progress"
                self.write(manifest)
        self.prepare()
        self.commit()
        self.cli("finalize", "demo", entry=SCRIPTS / "run_commit.py")

    def test_missing_contract_files_block_record_and_completion(  # testlint: allow
        self,
    ):
        self.prepare_integration(ignored_contract=True)
        self.deliver()
        self.verify()
        self.review()
        for path in ("task/demo.md", "spec/demo.md"):
            with self.subTest(source=path):
                source = self.root / path
                contents = source.read_bytes()
                source.unlink()
                self.prepare(ok=False)
                self.review(ok=False)
                source.mkdir()
                self.prepare(ok=False)
                self.review(ok=False)
                source.rmdir()
                source.write_bytes(contents)
        self.prepare()
