"""Exercise the installed Codex flow through real Git commits in an isolated repo."""
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


class CodexFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        for args in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                     ("git", "config", "user.name", "Flow Test")):
            self.assertEqual(run(self.project, *args).returncode, 0)
        self.assertEqual(run(self.project, sys.executable, str(ROOT / "install_codex.py"), "--target", str(self.project)).returncode, 0)
        (self.project / ".gitignore").write_text("run/\n", encoding="utf-8")
        (self.project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.assertEqual(run(self.project, "git", "add", ".").returncode, 0)
        self.assertEqual(run(self.project, "git", "commit", "-qm", "initial").returncode, 0)
        self.run_id = "2026-09-23-codex-flow"
        (self.project / "run").mkdir()
        self.manifest_path = self.project / "run" / f"{self.run_id}.json"
        self.manifest = {
            "run_id": self.run_id, "tier": 1, "status": "in_progress", "phase": "decomposed",
            "spec_inline": "Change the value", "local_test_passed": True,
            "local_test_evidence": "verified locally", "review_reds": 0, "verify_passed": True,
            "evidence_schema": 2,
        }
        self.save_manifest()
        (self.project / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertEqual(run(self.project, "git", "add", "app.py").returncode, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def helper(self, name, *args):
        return run(self.project, sys.executable, str(self.project / ".claude" / "hooks" / name), *args)

    def verify(self):
        return self.helper("run_verify.py", "--run-id", self.run_id, "--cmd", "python3 -c 'print(\"ok\")'")

    def test_code_change_after_verification_blocks_prepare(self):
        self.assertEqual(self.verify().returncode, 0)
        (self.project / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        self.assertEqual(run(self.project, "git", "add", "app.py").returncode, 0)
        prepare = self.helper("run_commit.py", "prepare", self.run_id)
        self.assertEqual(prepare.returncode, 2)
        self.assertIn("驗證後程式樹已變更", prepare.stderr)
        self.assertEqual(json.loads(self.manifest_path.read_text())["status"], "in_progress")

    def test_actual_message_and_finalize(self):
        self.assertEqual(self.verify().returncode, 0)
        self.assertEqual(self.helper("run_commit.py", "prepare", self.run_id).returncode, 0)
        message_file = self.project / ".git" / "flow-message.txt"
        message_file.write_text("change value\n", encoding="utf-8")
        rejected = run(self.project, "git", "commit", "-F", str(message_file))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("Run-Id", rejected.stderr)
        self.assertEqual(json.loads(self.manifest_path.read_text())["status"], "ready_to_commit")
        message_file.write_text(f"change value\n\nRun-Id: {self.run_id}\n", encoding="utf-8")
        self.assertEqual(run(self.project, "git", "commit", "-F", str(message_file)).returncode, 0)
        self.assertEqual(json.loads(self.manifest_path.read_text())["status"], "ready_to_commit")
        session = subprocess.run(
            [sys.executable, str(self.project / ".claude" / "hooks" / "session_start.py")],
            cwd=self.project, input=json.dumps({"cwd": str(self.project), "model": "gpt-6-sol"}),
            capture_output=True, text=True,
        )
        self.assertEqual(session.returncode, 0)
        self.assertIn(self.run_id, session.stdout)
        self.assertEqual(self.helper("run_commit.py", "finalize", self.run_id).returncode, 0)
        finished = json.loads(self.manifest_path.read_text())
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["commit_sha"], run(self.project, "git", "rev-parse", "HEAD").stdout.strip())

    def test_install_is_idempotent_and_preserves_project_instructions(self):
        instructions = self.project / "AGENTS.md"
        instructions.write_text("Project rule\n\n" + instructions.read_text(encoding="utf-8"), encoding="utf-8")
        again = run(self.project, "bash", str(ROOT / "init.sh"), "--platform", "codex", "--target", str(self.project))
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(instructions.read_text(encoding="utf-8").count("<!-- agent-workspace codex instructions -->"), 1)
        self.assertIn("Project rule", instructions.read_text(encoding="utf-8"))
        config = json.loads((self.project / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(len(config["hooks"]["PreToolUse"]), 1)
        writer = tomllib.loads((self.project / ".codex" / "agents" / "code-writer.toml").read_text(encoding="utf-8"))
        reviewer = tomllib.loads((self.project / ".codex" / "agents" / "code-reviewer.toml").read_text(encoding="utf-8"))
        self.assertNotEqual(writer["model"], reviewer["model"])


if __name__ == "__main__":
    unittest.main()
