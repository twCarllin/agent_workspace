"""Item accounting gates through real Git and CLI entry points."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent-flow/scripts"


class ItemCommitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "code.py").write_text("old\n")
        self.git("add", "code.py")
        self.git("commit", "-qm", "initial")
        (self.repo / "run").mkdir()
        (self.repo / "task.md").write_text(
            "## Task 1：工作\n- [ ] 1.1 交付\n- [ ] 1.2 文件\n"
        )
        self.manifest = dict(
            run_id="sample",
            tier=1,
            status="in_progress",
            spec_inline="work",
            framework_version="2026.10.19.1",
            task_file="task.md",
            hitl_confirmed_at="2026-10-19T00:00:00+00:00",
            local_test_passed=True,
            local_test_evidence="passed",
            review_reds=0,
            verify_passed=True,
            item_plan={
                "confirmed_at": "2026-10-19T00:00:00+00:00",
                "items": [
                    {"id": "1.1", "task_id": "1", "summary": "交付"},
                    {"id": "1.2", "task_id": "1", "summary": "文件"},
                ],
            },
            item_results={
                "1.1": {"status": "delivered", "files": ["code.py"]},
                "1.2": {"status": "delivered", "files": ["code.py"]},
            },
        )
        (self.repo / "code.py").write_text("new\n")
        self.git("add", "code.py")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def save(self):
        (self.repo / "run/sample.json").write_text(json.dumps(self.manifest))

    def cli(self, action):
        self.save()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_commit.py"), action, "sample"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.manifest = json.loads((self.repo / "run/sample.json").read_text())
        return result

    def ruling(self):
        return dict(
            actor="user",
            text="接受部分交付",
            at="2026-10-19T00:00:00+00:00",
            source="user message",
        )

    def test_prepare_and_finalize_confirm_actual_commit(self):
        self.assertEqual(self.cli("prepare").returncode, 0)
        self.git("commit", "-qm", "work\n\nRun-Id: sample")
        self.assertEqual(self.cli("finalize").returncode, 0)
        self.assertEqual(self.manifest["commit_sha"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.manifest["status"], "completed")

    def test_missing_item_and_deleted_task_item_block(self):
        del self.manifest["item_results"]["1.2"]
        self.assertIn("未結清 item", self.cli("prepare").stderr)
        (self.repo / "task.md").write_text("## Task 1：工作\n- [ ] 1.1 交付\n")
        self.assertIn("確認清單不符", self.cli("prepare").stderr)

    def test_removal_requires_ruling_and_paused_cannot_prepare(self):
        self.manifest["item_results"]["1.2"] = {"status": "removed"}
        self.assertIn("使用者裁示", self.cli("prepare").stderr)
        self.manifest["status"] = "paused"
        self.assertIn("not in progress", self.cli("prepare").stderr)

    def test_partial_preserves_unresolved_items(self):
        del self.manifest["item_results"]["1.2"]
        self.manifest["partial_acceptance"] = {
            "item_ids": ["1.2"],
            "ruling": self.ruling(),
        }
        self.assertEqual(self.cli("prepare").returncode, 0)
        self.git("commit", "-qm", "partial\n\nRun-Id: sample")
        self.assertEqual(self.cli("finalize").returncode, 0)
        self.assertEqual(self.manifest["status"], "partial")
        self.assertEqual(self.manifest["partial_acceptance"]["item_ids"], ["1.2"])

    def test_finalize_blocks_commit_without_delivery_file(self):
        self.assertEqual(self.cli("prepare").returncode, 0)
        self.git("reset", "-q", "HEAD", "code.py")
        (self.repo / "other.py").write_text("other\n")
        self.git("add", "other.py")
        self.git("commit", "-qm", "wrong\n\nRun-Id: sample")
        self.assertIn("不在本次提交", self.cli("finalize").stderr)
        self.assertEqual(self.manifest["status"], "ready_to_commit")

    def test_new_run_missing_plan_blocks_old_run_keeps_contract(self):
        del self.manifest["item_plan"]
        del self.manifest["item_results"]
        self.assertIn("缺 item_plan", self.cli("prepare").stderr)
        self.manifest["framework_version"] = "2026.10.03.1"
        self.assertEqual(self.cli("prepare").returncode, 0)

    def test_partial_phase_and_numeric_version_contract(self):
        sys.path.insert(0, str(SCRIPTS))
        import flow_rules

        self.assertEqual(flow_rules.manifest_phase({"phase": "partial"}), "partial")
        self.assertFalse(
            flow_rules.requires_item_accounting(
                {"tier": 2, "framework_version": "2026.9.1.1"}
            )
        )
        self.assertTrue(
            flow_rules.requires_item_accounting(
                {"tier": 2, "framework_version": "2026.10.19.1"}
            )
        )

    def test_partial_status_reports_finished_scope(self):
        self.manifest["status"] = "partial"
        self.manifest["created_at"] = "2026-10-19T00:00:00+00:00"
        self.manifest["completed_at"] = "2026-10-19T00:02:00+00:00"
        self.manifest["partial_acceptance"] = {
            "item_ids": ["1.2"],
            "ruling": self.ruling(),
        }
        self.save()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "flow.py"),
                "status",
                "--run-id",
                "sample",
                "--json",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertIn("1.2", status["next_action"])
        self.assertNotIn("resume", status["next_action"])
        self.assertEqual(status["recorded_elapsed_seconds"], 120)
        self.assertEqual(status["elapsed_seconds"], 120)
        watched = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "flow.py"),
                "watch",
                "--run-id",
                "sample",
                "--json",
                "--timeout",
                "30",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=3,
        )
        self.assertEqual(watched.returncode, 0, watched.stderr)
        watched_status = json.loads(watched.stdout)
        self.assertEqual(watched_status["status"], "partial")
        self.assertEqual(watched_status["elapsed_seconds"], 120)
        self.assertEqual(
            json.loads((self.repo / "run/sample.json").read_text())["completed_at"],
            self.manifest["completed_at"],
        )

    def test_real_commit_hook_checks_staged_delivery_paths(self):
        self.manifest["status"] = "ready_to_commit"
        self.save()
        message = self.repo / "message.txt"
        message.write_text("work\n\nRun-Id: sample\n")
        for entry in (
            SCRIPTS / "commit_message_gate.py",
            ROOT / ".claude/hooks/commit_message_gate.py",
        ):
            if not entry.exists():
                continue
            result = subprocess.run(
                [sys.executable, str(entry), str(message)],
                cwd=self.repo,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.git("reset", "-q", "HEAD", "code.py")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "commit_message_gate.py"), str(message)],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("不在本次提交", result.stderr)

    def test_tier2_writer_gate_requires_frozen_plan_before_implementation(self):
        self.manifest["tier"] = 2
        self.manifest["phase"] = "decomposed"
        plan = self.manifest.pop("item_plan")
        self.save()
        (self.repo / "eval_state.json").write_text(json.dumps({"run_id": "sample"}))
        payload = json.dumps(
            {
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "code-writer"},
                "cwd": str(self.repo),
            }
        )
        entries = (SCRIPTS / "eval_gates.py", ROOT / ".claude/hooks/eval_gates.py")

        def gate(entry):
            return subprocess.run(
                [sys.executable, str(entry), "--hook"],
                input=payload,
                cwd=self.repo,
                capture_output=True,
                text=True,
            )

        for entry in entries:
            with self.subTest(entry=entry):
                blocked = gate(entry)
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("缺 item_plan", blocked.stderr)
        confirmed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "item_accounting.py"),
                "--run-id",
                "sample",
                "confirm-plan",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.manifest = json.loads((self.repo / "run/sample.json").read_text())
        self.assertEqual(self.manifest["item_plan"], plan)
        for entry in entries:
            self.assertEqual(gate(entry).returncode, 0)
        (self.repo / "task.md").write_text("## Task 1：工作\n- [ ] 1.1 交付\n")
        for entry in entries:
            blocked = gate(entry)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("確認清單不符", blocked.stderr)
        self.manifest.pop("item_plan")
        self.manifest["framework_version"] = "2026.10.03.1"
        self.save()
        for entry in entries:
            self.assertEqual(gate(entry).returncode, 0)
