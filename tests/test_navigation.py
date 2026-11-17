"""Navigation contracts through real CLI, hook payloads and Git commits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPTS = SOURCE / ".agent-flow/scripts"


class NavigationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.a, self.b = self.base / "A", self.base / "B"
        self.a.mkdir()
        self.b.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Navigation test")
        self.git("config", "user.email", "navigation@example.invalid")

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.b,
            capture_output=True,
            text=True,
        )

    def cli(self, name, *args, cwd=None, payload=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            cwd=cwd or self.b,
            input=json.dumps(payload) if payload else None,
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.a)},
        )

    def init(self, cwd=None):
        (cwd or self.b).joinpath("task.md").write_text(
            "## Task 1: navigation\n- [ ] 1.1 behavior\n"
        )
        return self.cli(
            "eval_state.py",
            "init-run",
            "--run-id",
            "nav",
            "--harness",
            "codex",
            "--spec-inline",
            "navigation",
            "--tier-rationale",
            "small",
            "--test-command",
            "true",
            "--task-file",
            "task.md",
            cwd=cwd,
        )

    def manifest(self, root=None, **updates):
        root = root or self.b
        (root / "run").mkdir(exist_ok=True)
        manifest = {
            "run_id": "nav",
            "tier": 1,
            "tier1_policy": "adaptive-v1",
            "phase": "init",
            "status": "in_progress",
            "spec_inline": "navigation",
        }
        manifest.update(updates)
        (root / "run/nav.json").write_text(json.dumps(manifest))

    def hook(self, tool, data):
        return self.cli(
            "eval_gates.py",
            "--hook",
            cwd=self.a,
            payload={"cwd": str(self.a), "tool_name": tool, "tool_input": data},
        )

    def test_lightweight_session_does_not_require_copied_installation(self):
        attach = subprocess.run(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--attach",
                "--target",
                str(self.b),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(attach.returncode, 0, attach.stderr)
        self.manifest()
        session = self.cli(
            "session_start.py", payload={"cwd": str(self.b), "harness": "claude"}
        )
        self.assertEqual(session.returncode, 0, session.stderr)
        self.assertIn("有未收尾的 run：nav", session.stdout)
        self.assertNotIn("settings.json", session.stdout)
        self.assertNotIn("缺核心 skill", session.stdout)
        self.assertNotIn("RETRO.md 不存在", session.stdout)
        self.assertFalse((self.b / ".agents").exists())

    def test_subdirectory_cli_rejects_without_creating_invisible_state(self):
        sub = self.b / "pkg"
        sub.mkdir()
        (sub / "run").mkdir()  # An unrelated run directory is not an installation.
        (sub / "run/unrelated.json").write_text('{"status":"in_progress"}')
        for name, args in (
            (
                "eval_state.py",
                [
                    "init-run",
                    "--run-id",
                    "nav",
                    "--harness",
                    "codex",
                    "--spec-inline",
                    "x",
                    "--tier-rationale",
                    "x",
                    "--test-command",
                    "true",
                ],
            ),
            ("flow.py", ["next"]),
            ("run_verify.py", ["--run-id", "nav", "--cmd", "true"]),
            ("run_commit.py", ["prepare", "nav"]),
        ):
            with self.subTest(name=name):
                result = self.cli(name, *args, cwd=sub)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(self.b), result.stderr)
                self.assertFalse((sub / "run/nav.json").exists())
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.init(cwd=self.a).returncode, 2)

    def test_external_write_edit_patch_and_started_run(self):
        self.assertEqual(self.init().returncode, 0)
        for tool, data in (
            ("Write", {"file_path": str(self.b / "new.py")}),
            ("Edit", {"file_path": str(self.b / "new.py")}),
            (
                "apply_patch",
                {
                    "patch": f"*** Begin Patch\n*** Add File: {self.b}/new.py\n+x\n*** End Patch"
                },
            ),
            (
                "apply_patch",
                {
                    "patch": f"*** Begin Patch\n*** Update File: {self.a}/old.py\n*** Move to: {self.b}/new.py\n@@\n-x\n+y\n*** End Patch"
                },
            ),
        ):
            with self.subTest(tool=tool, data=data):
                result = self.hook(tool, data)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("phase=init", result.stderr)
        self.assertEqual(
            self.hook("Write", {"file_path": str(self.b / "task/plan.md")}).returncode,
            0,
        )
        started = self.cli(
            "eval_state.py",
            "start-run",
            "nav",
            "--authorization",
            "implement navigation",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(
            self.hook("Write", {"file_path": str(self.b / "new.py")}).returncode, 0
        )

    def test_legacy_subdir_run_is_seen_from_repo_root_and_conflicts_block(self):
        sub = self.b / "pkg"
        sub.mkdir()
        self.manifest(sub)
        self.assertEqual(
            self.hook("Write", {"file_path": str(self.b / "source.py")}).returncode, 2
        )
        result = self.cli("flow.py", "next")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(sub), result.stderr)
        self.assertEqual(self.cli("flow.py", "next", cwd=sub).returncode, 0)
        self.manifest()
        result = self.cli("flow.py", "next")
        self.assertNotEqual(result.returncode, 0)
        for root in (sub, self.b):
            self.assertIn(str(root), result.stderr)

    def attach(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--attach",
                "--target",
                str(self.b),
                *extra,
            ],
            capture_output=True,
            text=True,
        )

    def test_attach_excludes_state_and_enforces_commit_from_any_directory(self):
        attached = self.attach()
        self.assertEqual(attached.returncode, 0, attached.stderr)
        self.assertFalse((self.b / ".agent-flow").exists())
        self.assertFalse((self.b / ".codex").exists())
        self.manifest()
        (self.b / "source.py").write_text("x = 1\n")
        self.git("add", ".")
        self.assertEqual(
            self.git("diff", "--cached", "--name-only").stdout.strip(), "source.py"
        )
        for command, cwd in (
            (["git", "commit", "-m", "missing"], self.b),
            (["git", "-C", str(self.b), "commit", "-m", "missing"], self.a),
        ):
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Run-Id", result.stderr)
        # A legacy subdirectory run must remain visible to the Git-root hook.
        (self.b / "run/nav.json").unlink()
        sub = self.b / "pkg"
        sub.mkdir()
        self.manifest(sub)
        result = self.git("commit", "-m", "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run-Id", result.stderr)

    def test_attach_preserves_custom_hook_and_hooks_path(self):
        hook = self.b / ".git/hooks/commit-msg"
        hook.write_text("#!/bin/sh\nexit 0\n")
        self.assertEqual(self.attach().returncode, 2)
        self.assertEqual(hook.read_text(), "#!/bin/sh\nexit 0\n")
        hook.unlink()
        self.git("config", "core.hooksPath", "custom-hooks")
        result = self.attach()
        self.assertEqual(result.returncode, 2)
        self.assertIn("未啟用", result.stdout)
        self.assertEqual(
            self.git("config", "core.hooksPath").stdout.strip(), "custom-hooks"
        )

    def test_shared_toolchain_cannot_change_during_pending_run(self):
        self.assertEqual(self.attach().returncode, 0)
        self.manifest()
        hook = self.b / ".git/hooks/commit-msg"
        other = self.base / "other-scripts"
        original = hook.read_text().replace(
            f"# agent-workspace shared scripts: {SCRIPTS}",
            f"# agent-workspace shared scripts: {other}",
        )
        hook.write_text(original)
        result = self.cli("flow.py", "next")
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(other), result.stderr)
        self.assertNotEqual(self.attach().returncode, 0)
        self.assertEqual(hook.read_text(), original)

    def test_commit_uses_target_hook_instead_of_navigation_state(self):
        self.assertEqual(self.git("init", "-q", cwd=self.a).returncode, 0)
        result = subprocess.run(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--attach",
                "--target",
                str(self.a),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attach().returncode, 0)
        self.manifest(self.a)
        (self.a / "eval_state.json").write_text('{"run_id":"nav","sub_tasks":[]}')
        self.manifest()
        for command in (
            f"cd {self.b} && git commit -m missing",
            f"git -C {self.b} commit -m missing",
        ):
            self.assertEqual(self.hook("Bash", {"command": command}).returncode, 2)
        (self.b / "source.py").write_text("x = 1\n")
        self.git("add", "source.py")
        self.assertNotEqual(self.git("commit", "-m", "missing").returncode, 0)

    def test_dispatch_text_does_not_exempt_a_commit_in_the_same_command(self):
        self.git("init", "-q", cwd=self.a)
        self.manifest(self.a)
        (self.a / "eval_state.json").write_text('{"run_id":"nav","sub_tasks":[]}')
        (self.a / "source.py").write_text("value = 1\n")
        self.git("add", "source.py", cwd=self.a)
        for command in (
            "git commit -m test",
            "echo dispatch.py code-writer; git commit -m test",
            f"python3 {SCRIPTS}/dispatch.py code-writer && git commit -m test",
            "cat <<'EOF'\ndispatch.py code-writer\nEOF\ngit commit -m test",
        ):
            with self.subTest(command=command):
                rejected = self.hook("Bash", {"command": command})
                self.assertEqual(rejected.returncode, 2, rejected.stderr)
                self.assertIn("eval_state.json", rejected.stderr)
        deferred = f"cd {self.b} && python3 {SCRIPTS}/dispatch.py code-writer"
        self.assertEqual(self.hook("Bash", {"command": deferred}).returncode, 0)

    def prepare_commit(self, *, attach=True):
        if attach:
            self.assertEqual(self.attach().returncode, 0)
        self.git("commit", "--allow-empty", "-qm", "initial")
        (self.b / "source.py").write_text("x = 1\n")
        self.git("add", "source.py")
        self.manifest(
            phase="decomposed",
            tier1_policy=None,
            evidence_schema=2,
            local_test_passed=True,
            local_test_evidence="test",
            review_reds=0,
            verify_passed=True,
        )
        verified = self.cli("run_verify.py", "--run-id", "nav", "--cmd", "true")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        prepared = self.cli("run_commit.py", "prepare", "nav")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

    def formal_commit(self, message="finish"):
        return self.cli(
            "run_commit.py",
            "commit",
            "nav",
            "--message",
            message,
            "--files",
            "source.py",
        )

    def test_official_commit_checks_target_while_raw_navigation_is_conservative(self):
        self.git("init", "-q", cwd=self.a)
        attached = subprocess.run(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--attach",
                "--target",
                str(self.a),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(attached.returncode, 0, attached.stderr)
        self.manifest(self.a)
        # Regression: A's managed hook must never prove an unconnected B safe.
        self.prepare_commit(attach=False)
        for command in (
            f"git -C {self.b} commit -m missing",
            f"cd {self.b} && git commit -m missing",
        ):
            self.assertEqual(self.hook("Bash", {"command": command}).returncode, 2)
        before = self.git("rev-parse", "HEAD").stdout
        self.assertNotEqual(self.formal_commit().returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertEqual(self.attach().returncode, 0)
        refreshed = self.cli(
            "run_verify.py",
            "--run-id",
            "nav",
            "--cmd",
            "true",
            "--rerun-reason",
            "evidence_refresh",
        )
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        (self.a / "eval_state.json").write_text('{"run_id":"nav","sub_tasks":[]}')
        entry = f"cd {self.b} && python3 {SCRIPTS}/run_commit.py commit nav --message finish --files source.py"
        self.assertEqual(self.hook("Bash", {"command": entry}).returncode, 0)
        committed = self.formal_commit()
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("Run-Id: nav", self.git("log", "-1", "--format=%B").stdout)
        sha = self.git("rev-parse", "HEAD").stdout
        self.assertEqual(self.formal_commit().returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, sha)

    def test_official_commit_rejects_custom_hook_and_changed_prepare_or_evidence(self):
        self.prepare_commit(attach=False)
        before = self.git("rev-parse", "HEAD").stdout
        hook = self.b / ".git/hooks/commit-msg"
        hook.write_text(f"#!/bin/sh\necho called >> '{self.b}/hook-called'\n")
        hook.chmod(0o755)
        self.assertNotEqual(self.formal_commit().returncode, 0)
        self.assertFalse((self.b / "hook-called").exists())
        hook.unlink()
        self.assertEqual(self.attach().returncode, 0)
        path = self.b / "run/nav.json"
        original = json.loads(path.read_text())
        for update in (
            {"status": "in_progress"},
            {"verification_commands": []},
        ):
            path.write_text(json.dumps({**original, **update}))
            self.assertNotEqual(self.formal_commit().returncode, 0)
            self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        path.write_text(json.dumps(original))
        self.assertNotEqual(self.formal_commit("wrong\n\nRun-Id: other").returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        (self.b / "source.py").write_text("x = 2\n")
        self.git("add", "source.py")
        rejected = self.formal_commit()
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("prepare snapshot", rejected.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)

    def test_official_commit_recovers_existing_prepared_commit_without_duplicate(self):
        self.prepare_commit()
        result = self.git("commit", "-m", "finished\n\nRun-Id: nav")
        self.assertEqual(result.returncode, 0, result.stderr)
        sha = self.git("rev-parse", "HEAD").stdout
        self.assertEqual(self.formal_commit().returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, sha)
        manifest = json.loads((self.b / "run/nav.json").read_text())
        self.assertEqual(manifest["status"], "completed")

    def test_official_commit_reports_git_stderr_without_committing(self):
        self.prepare_commit()
        before = self.git("rev-parse", "HEAD").stdout
        (self.b / ".git/index.lock").write_text("held by another operation\n")
        rejected = self.formal_commit()
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("write-tree", rejected.stderr)
        self.assertIn("index.lock", rejected.stderr)
        self.assertIn("File exists", rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)

    def test_official_commit_runs_integrated_custom_hook_once(self):
        self.prepare_commit(attach=False)
        hooks = self.b / ".git/custom-hooks"
        hooks.mkdir()
        count = self.b / ".git/hook-count"
        hook = hooks / "commit-msg"
        hook.write_text(
            f'#!/bin/sh\n# agent-workspace shared scripts: {SCRIPTS}\necho called >> "{count}"\n'
            f'python3 "{SCRIPTS}/commit_message_gate.py" "$1"\n'
        )
        hook.chmod(0o755)
        self.git("config", "core.hooksPath", str(hooks))
        result = self.formal_commit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(count.read_text().splitlines(), ["called"])
        self.assertEqual(
            self.git("config", "core.hooksPath").stdout.strip(), str(hooks)
        )

    def test_linked_worktree_keeps_state_separate(self):
        self.git("commit", "--allow-empty", "-qm", "initial")
        self.assertEqual(self.attach().returncode, 0)
        worktree = self.base / "wt"
        self.assertEqual(
            self.git("worktree", "add", "-qb", "wt", str(worktree)).returncode, 0
        )
        self.assertEqual(self.init(cwd=worktree).returncode, 0)
        self.assertFalse((self.b / "run/nav.json").exists())
        (worktree / "source.py").write_text("x = 1\n")
        self.git("add", ".", cwd=worktree)
        result = self.git("commit", "-m", "missing", cwd=worktree)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run-Id", result.stderr)

    def test_existing_subdirectory_install_uses_own_tools_and_hook(self):
        sub = self.b / "pkg"
        sub.mkdir()
        installed = subprocess.run(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--harness",
                "both",
                "--target",
                str(sub),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertNotEqual(self.init(cwd=sub).returncode, 0)  # Use installed scripts.
        args = [
            sys.executable,
            str(sub / ".agent-flow/scripts/eval_state.py"),
            "init-run",
            "--run-id",
            "nav",
            "--harness",
            "codex",
            "--spec-inline",
            "navigation",
            "--tier-rationale",
            "small",
            "--test-command",
            "true",
        ]
        result = subprocess.run(args, cwd=sub, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((sub / "run/nav.json").exists())
        self.assertFalse((self.b / "run/nav.json").exists())
        (self.b / "source.py").write_text("x = 1\n")
        self.git("add", "source.py")
        committed = self.git("commit", "-m", "missing")
        self.assertNotEqual(committed.returncode, 0)
        self.assertIn("Run-Id", committed.stderr)


if __name__ == "__main__":
    unittest.main()
