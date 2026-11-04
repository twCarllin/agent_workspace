"""Exercise Flow CLI in isolated Git repositories using real verification and commits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / ".agent-flow/scripts/flow.py"


class FlowCliTest(unittest.TestCase):
    def test_activation_separates_configured_entry_from_client_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "<!-- agent-workspace codex instructions -->\n"
            )
            (root / ".codex").mkdir()
            (root / ".codex/hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {"command": "python3 eval_gates.py --hook"}
                                    ],
                                }
                            ]
                        }
                    }
                )
            )
            (root / "run").mkdir()
            (root / "run/r1.json").write_text(
                json.dumps(
                    {
                        "run_id": "r1",
                        "tier": 1,
                        "tier_rationale": "empty reasons",
                        "status": "in_progress",
                    }
                )
            )
            process = subprocess.run(
                [sys.executable, str(CLI), "activation", "--run-id", "r1", "--json"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["entry"]["status"], "configured")
            self.assertEqual(result["entry"]["loaded_by_client"], "unknown")
            self.assertEqual(result["route"], {"status": "recorded", "tier": 1})
            self.assertEqual(result["run"]["status"], "in_progress")
            self.assertEqual(
                result["hook"], {"status": "configured", "execution": "unknown"}
            )
            (root / "run/r2.json").write_text(
                json.dumps({"run_id": "r2", "status": "in_progress"})
            )
            ambiguous = subprocess.run(
                [sys.executable, str(CLI), "activation", "--json"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ambiguous.returncode, 0, ambiguous.stderr)
            self.assertEqual(json.loads(ambiguous.stdout)["run"]["status"], "ambiguous")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Flow Test")
        (self.repo / ".gitignore").write_text("run/\neval_state.json\n")
        (self.repo / "code.py").write_text("value = 1\n")
        self.git("add", ".gitignore", "code.py")
        self.git("commit", "-qm", "initial")
        (self.repo / "run").mkdir()
        self.manifest = dict(
            run_id="r1",
            tier=1,
            harness="codex",
            evidence_schema=2,
            status="in_progress",
            phase="reviewing",
            spec_inline="task",
            test_command="python3 -c pass",
            local_test_passed=True,
            local_test_evidence="test command passed",
            review_reds=0,
            verify_passed=True,
        )
        self.save()
        (self.repo / "code.py").write_text("value = 2\n")
        self.git("add", "code.py")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def save(self, manifest=None):
        data = manifest or self.manifest
        (self.repo / "run" / (data["run_id"] + ".json")).write_text(json.dumps(data))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=self.repo,
            text=True,
            capture_output=True,
        )

    def finish(self, *extra):
        return self.cli(
            "finish",
            "--run-id",
            "r1",
            "--message",
            "Complete work",
            "--files",
            "code.py",
            *extra,
        )

    def read_manifest(self):
        return json.loads((self.repo / "run/r1.json").read_text())

    def test_next_task_terminal_selection_and_read_only(self):
        self.manifest.update(tier=2, phase="decomposed")
        self.save()
        state = {
            "run_id": "r1",
            "sub_tasks": [{"id": 1, "status": "in_progress", "step": "writing"}],
        }
        (self.repo / "eval_state.json").write_text(json.dumps(state))
        before = {
            p: p.read_bytes()
            for p in [
                self.repo / "run/r1.json",
                self.repo / "eval_state.json",
                self.repo / ".git/index",
            ]
        }
        result = self.cli("next")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(
            set(value), {"run_id", "state", "action", "command", "reason", "blockers"}
        )
        self.assertEqual(value["action"], "resume_task")
        self.assertIn("writing", value["reason"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.manifest.update(status="partial", partial_acceptance={"item_ids": ["1.1"]})
        self.save()
        value = json.loads(self.cli("next", "--run-id", "r1", "--json").stdout)
        self.assertEqual(value["action"], "done")
        self.assertIn("1.1", value["blockers"][0])
        self.assertEqual(self.cli("next", "--run-id", "missing").returncode, 2)
        self.manifest["status"] = "in_progress"
        self.save()
        self.save({"run_id": "r2", "status": "in_progress"})
        self.assertEqual(self.cli("next").returncode, 2)

    def test_next_verify_review_and_ready_to_commit(self):
        result = self.cli("next", "--run-id", "r1")
        value = json.loads(result.stdout)
        self.assertEqual(value["action"], "verify")
        self.assertIn("--reuse", value["command"])
        verify = self.cli(
            "finish", "--run-id", "r1", "--message", "x", "--files", "code.py"
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.manifest = self.read_manifest()
        self.manifest.update(
            status="in_progress", checked_by="self", tier1_policy="adaptive-v1"
        )
        self.save()
        value = json.loads(self.cli("next", "--run-id", "r1").stdout)
        self.assertEqual(value["action"], "review")
        self.assertIsNone(value["command"])
        self.manifest.update(
            status="ready_to_commit", pre_commit_head=self.git("rev-parse", "HEAD^")
        )
        self.save()
        value = json.loads(self.cli("next", "--run-id", "r1").stdout)
        self.assertEqual(value["action"], "finalize")
        self.assertEqual(value["command"][-2:], ["finalize", "r1"])
        self.manifest["pre_commit_head"] = "wrong"
        self.save()
        self.assertEqual(
            json.loads(self.cli("next", "--run-id", "r1").stdout)["action"], "blocked"
        )

    def test_next_stale_verification_and_other_run_state(self):
        verify = subprocess.run(
            [
                sys.executable,
                str(CLI.parent / "run_verify.py"),
                "--run-id",
                "r1",
                "--cmd",
                "python3 -c pass",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        (self.repo / "code.py").write_text("value = 3\n")
        value = json.loads(self.cli("next", "--run-id", "r1").stdout)
        self.assertEqual(value["action"], "verify")
        self.assertTrue(value["blockers"])
        (self.repo / "eval_state.json").write_text(
            json.dumps({"run_id": "r2", "sub_tasks": []})
        )
        value = json.loads(self.cli("next", "--run-id", "r1").stdout)
        self.assertEqual(value["action"], "blocked")

    def test_next_self_review_is_read_only_and_verify_command_advances(self):
        (self.repo / "run/r1.json").unlink()
        (self.repo / "task.md").write_text("## Task 1: demo\n- [ ] 1.1 behavior\n")
        self.git("add", "task.md")
        state_cli = CLI.parent / "eval_state.py"

        def state(*args):
            result = subprocess.run(
                [sys.executable, str(state_cli), *args],
                cwd=self.repo,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        state(
            "init-run",
            "--run-id",
            "r1",
            "--harness",
            "codex",
            "--spec-inline",
            "behavior",
            "--tier-rationale",
            "small",
            "--test-command",
            "python3 -c pass",
            "--task-file",
            "task.md",
        )
        state("start-run", "r1", "--authorization", "requested behavior")
        value = json.loads(self.cli("next", "--run-id", "r1").stdout)
        self.assertEqual(value["action"], "verify")
        verify = subprocess.run(
            value["command"], cwd=self.repo, capture_output=True, text=True
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertEqual(
            json.loads(self.cli("next", "--run-id", "r1").stdout)["action"], "review"
        )
        state(
            "review-run",
            "r1",
            "0",
            "--checked-by",
            "self",
            "--evidence",
            "behavior verified",
            "--passed",
        )
        self.assertEqual(
            json.loads(self.cli("next", "--run-id", "r1").stdout)["action"], "items"
        )
        deliver = subprocess.run(
            [
                sys.executable,
                str(CLI.parent / "item_accounting.py"),
                "--run-id",
                "r1",
                "deliver",
                "1.1",
                "--files",
                "code.py",
                "--evidence",
                "ran:python3 -c pass",
                "--observed",
                "使用者看到結果",
                "--observed-evidence",
                "ran:real entry ok",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(deliver.returncode, 0, deliver.stderr)
        manifest = self.read_manifest()
        hot_state = self.repo / "eval_state.json"
        hot_state.write_text(
            json.dumps(
                {
                    "run_id": "r1",
                    "sub_tasks": [
                        {
                            "id": 1,
                            "status": "passed",
                            "checked_by": "self",
                            "tier": 1,
                            "tier1_policy": "adaptive-v1",
                            "local_test_passed": True,
                            "local_test_evidence": "verified",
                            "review_reds": 0,
                            "verify_passed": True,
                        }
                    ],
                }
            )
        )
        tree = manifest["self_review_snapshot"]["index_tree"]
        object_path = self.repo / ".git/objects" / tree[:2] / tree[2:]
        self.assertTrue(object_path.exists())
        object_path.unlink()
        blob = self.git("rev-parse", ":code.py")
        self.git("update-index", "--cacheinfo", f"100644,{blob},code.py")
        paths = [
            self.repo / "run/r1.json",
            hot_state,
            self.repo / ".git/index",
            self.repo / "code.py",
            self.repo / "task.md",
        ]
        before = {path: path.read_bytes() for path in paths}
        objects_before = {
            path.relative_to(self.repo / ".git/objects"): path.read_bytes()
            for path in (self.repo / ".git/objects").rglob("*")
            if path.is_file()
        }
        result = self.cli("next", "--run-id", "r1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["action"], "finish")
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        self.assertEqual(
            objects_before,
            {
                path.relative_to(self.repo / ".git/objects"): path.read_bytes()
                for path in (self.repo / ".git/objects").rglob("*")
                if path.is_file()
            },
        )
        self.assertFalse(object_path.exists())

        primary = self.repo / "run/primary-objects"
        alternate = self.repo / "run/alternate-objects"
        primary.mkdir()
        (alternate / blob[:2]).mkdir(parents=True)
        blob_path = self.repo / ".git/objects" / blob[:2] / blob[2:]
        blob_path.rename(alternate / blob[:2] / blob[2:])
        task_blob = self.git("rev-parse", ":task.md")
        (primary / task_blob[:2]).mkdir(exist_ok=True)
        (self.repo / ".git/objects" / task_blob[:2] / task_blob[2:]).rename(
            primary / task_blob[:2] / task_blob[2:]
        )
        self.git("update-index", "--cacheinfo", f"100644,{blob},code.py")
        paths.append(alternate / blob[:2] / blob[2:])
        before = {path: path.read_bytes() for path in paths}
        object_dirs = [self.repo / ".git/objects", primary, alternate]
        objects_before = {
            path: path.read_bytes()
            for directory in object_dirs
            for path in directory.rglob("*")
            if path.is_file()
        }
        env = {
            **os.environ,
            "GIT_OBJECT_DIRECTORY": str(primary),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.pathsep.join(
                [str(self.repo / ".git/objects"), str(alternate)]
            ),
        }
        result = subprocess.run(
            [sys.executable, str(CLI), "next", "--run-id", "r1"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["action"], "finish")
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        self.assertEqual(
            objects_before,
            {
                path: path.read_bytes()
                for directory in object_dirs
                for path in directory.rglob("*")
                if path.is_file()
            },
        )

    def test_worktree_link_creates_links_then_reports_nothing(self):
        (self.repo / ".agent-flow").mkdir()
        worktree = Path(self.tmp.name) / "wt"
        self.git("worktree", "add", "--detach", "-q", str(worktree))
        run = lambda: subprocess.run(
            [sys.executable, str(CLI), "worktree-link"],
            cwd=worktree,
            text=True,
            capture_output=True,
        )
        first = run()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(".agent-flow", first.stdout)
        self.assertTrue((worktree / ".agent-flow").is_symlink())
        second = run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "無需建立連結")

    def test_finish_real_verify_prepare_commit_finalize(self):
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["commit_sha"], self.git("rev-parse", "HEAD"))
        self.assertEqual(manifest["verification_commands"][-1]["exit_code"], 0)
        self.assertIn("Run-Id: r1", self.git("log", "-1", "--format=%B"))
        sha = self.git("rev-parse", "HEAD")
        self.assertEqual(self.finish().returncode, 0)
        self.assertEqual(sha, self.git("rev-parse", "HEAD"))

    def test_finish_reuses_matching_local_result_when_requested(self):
        command = (
            "python3 -c \"from pathlib import Path; p=Path('run/counter'); "
            "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\""
        )
        self.manifest["test_command"] = command
        self.save()
        verify = ROOT / ".agent-flow/scripts/run_verify.py"
        first = subprocess.run(
            [
                sys.executable,
                str(verify),
                "--run-id",
                "r1",
                "--cmd",
                command,
                "--quiet-success",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        result = self.finish("--reuse")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.repo / "run/counter").read_text(), "1")
        self.assertTrue(self.read_manifest()["verification_commands"][-1]["reused"])

    def test_finish_requires_reason_for_matching_success(self):
        command = (
            "python3 -c \"from pathlib import Path; p=Path('run/counter'); "
            "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\""
        )
        self.manifest["test_command"] = command
        self.save()
        verify = ROOT / ".agent-flow/scripts/run_verify.py"
        first = subprocess.run(
            [sys.executable, str(verify), "--run-id", "r1", "--cmd", command],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        blocked = self.finish()
        self.assertEqual(blocked.returncode, 2, blocked.stderr + blocked.stdout)
        self.assertIn("rerun_reason_required", blocked.stderr)
        self.assertEqual((self.repo / "run/counter").read_text(), "1")
        result = self.finish("--rerun-reason", "evidence_refresh")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.repo / "run/counter").read_text(), "2")
        self.assertTrue(self.read_manifest()["verification_commands"][-1]["executed"])

    def test_finish_observes_external_state_failure_without_reuse(self):
        command = (
            'python3 -c "from pathlib import Path; '
            "raise SystemExit(int(Path('run/external_exit').read_text()))\""
        )
        self.manifest["test_command"] = command
        self.save()
        (self.repo / "run/external_exit").write_text("0")
        verify = ROOT / ".agent-flow/scripts/run_verify.py"
        first = subprocess.run(
            [
                sys.executable,
                str(verify),
                "--run-id",
                "r1",
                "--cmd",
                command,
                "--quiet-success",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.git("rev-parse", "HEAD")
        (self.repo / "run/external_exit").write_text("7")
        result = self.finish("--rerun-reason", "environment_changed")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.read_manifest()["verification_commands"][-1]["exit_code"], 7
        )
        self.assertEqual(before, self.git("rev-parse", "HEAD"))

    def test_missing_review_rejects_before_verify(self):
        self.manifest["verify_passed"] = False
        self.save()
        before = self.git("rev-parse", "HEAD")
        result = self.finish()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertNotIn("verification_commands", self.read_manifest())

    def test_verification_failure_keeps_original_output(self):
        before = self.git("rev-parse", "HEAD")
        result = self.finish(
            "--verify-command",
            "python3 -c 'print(\"specific-failure\"); raise SystemExit(7)'",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("specific-failure", result.stdout + result.stderr)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertNotEqual(self.read_manifest()["status"], "completed")

    def test_extra_staged_paths_rejected(self):
        (self.repo / "other.py").write_text("other = 1\n")
        self.git("add", "other.py")
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn("extra=", result.stderr)

    def test_unstaged_scope_change_rejected(self):
        (self.repo / "code.py").write_text("value = 3\n")
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn("working files differ", result.stderr)

    def test_other_hot_run_rejected_without_archive(self):
        hot = self.repo / "eval_state.json"
        hot.write_text(json.dumps(dict(run_id="other", sub_tasks=[])))
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn("run_id mismatch", result.stderr)
        self.assertTrue(hot.exists())
        self.assertNotIn("verification_commands", self.read_manifest())

    def test_tier2_archives_only_matching_passed_state(self):
        self.manifest["tier"] = 2
        self.save()
        task = dict(
            id=1,
            name="task",
            status="passed",
            step="done",
            local_test_passed=True,
            local_test_evidence="tests passed",
            review_reds=0,
            verify_passed=True,
        )
        hot = self.repo / "eval_state.json"
        hot.write_text(json.dumps(dict(run_id="r1", sub_tasks=[task])))
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(hot.exists())
        archive = json.loads((self.repo / "run/r1.eval.json").read_text())
        self.assertEqual(archive["run_id"], "r1")
        self.assertEqual(self.read_manifest()["status"], "completed")

    def test_tier2_failed_task_stops_before_verification(self):
        self.manifest["tier"] = 2
        self.save()
        (self.repo / "eval_state.json").write_text(
            json.dumps(dict(run_id="r1", sub_tasks=[dict(id=1, status="failed")]))
        )
        result = self.finish()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("verification_commands", self.read_manifest())
        self.assertTrue((self.repo / "eval_state.json").exists())

    def test_invalid_tier2_task_shapes_refuse_before_verification(self):
        self.manifest["tier"] = 2
        self.save()
        before = self.git("rev-parse", "HEAD")
        malformed = [
            dict(run_id="r1"),
            dict(run_id="r1", sub_tasks=[]),
            dict(run_id="r1", sub_tasks=None),
            dict(run_id="r1", sub_tasks={}),
            dict(run_id="r1", sub_tasks="bad"),
            dict(run_id="r1", sub_tasks=[None]),
            dict(run_id="r1", sub_tasks=[1]),
        ]
        for location in ("eval_state.json", "run/r1.eval.json"):
            for state in malformed:
                with self.subTest(location=location, state=state):
                    record = self.repo / location
                    original = json.dumps(state)
                    record.write_text(original)
                    result = self.finish()
                    self.assertEqual(
                        result.returncode, 2, result.stdout + result.stderr
                    )
                    self.assertIn("sub_tasks must be a nonempty list", result.stderr)
                    self.assertNotIn("verification_commands", self.read_manifest())
                    self.assertEqual(before, self.git("rev-parse", "HEAD"))
                    self.assertEqual(record.read_text(), original)
                    self.assertNotEqual(self.read_manifest()["status"], "completed")
                    record.unlink()

    def test_atomic_lock_rejected(self):
        lock = self.repo / ".git/flow-finish.lock"
        lock.write_text("another process")
        self.assertEqual(self.finish().returncode, 2)
        self.assertEqual(lock.read_text(), "another process")

    def test_resume_finalize_does_not_commit_again(self):
        self.assertEqual(self.finish().returncode, 0)
        manifest = self.read_manifest()
        manifest["status"] = "ready_to_commit"
        manifest.pop("commit_sha")
        self.save(manifest)
        before = self.git("rev-parse", "HEAD")
        result = self.finish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertEqual(self.read_manifest()["status"], "completed")

    def test_initial_commit_finish(self):
        # New repository with staged code and no HEAD exercises prepare's null parent.
        subprocess.run(["git", "update-ref", "-d", "HEAD"], cwd=self.repo, check=True)
        result = self.finish("--files", ".gitignore", "code.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self.read_manifest()["pre_commit_head"])

    def test_status_excludes_other_run_state(self):
        (self.repo / "eval_state.json").write_text(
            json.dumps(dict(run_id="other", sub_tasks=[dict(id=99)]))
        )
        result = self.cli("status", "--run-id", "r1", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["tasks"], [])

    def test_ambiguous_auto_selection_rejected(self):
        self.save(dict(self.manifest, run_id="r2"))
        self.assertEqual(self.cli("status").returncode, 2)
        self.assertEqual(self.cli("status", "--run-id", "r1").returncode, 0)

    def test_watch_is_bounded_emits_only_changes(self):
        result = self.cli(
            "watch",
            "--run-id",
            "r1",
            "--json",
            "--timeout",
            "0.12",
            "--interval",
            "0.05",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(self.cli("watch", "--timeout", "999999").returncode, 2)

    def test_completed_watch_exits_immediately(self):
        self.manifest["status"] = "completed"
        self.save()
        result = self.cli("watch", "--run-id", "r1", "--json", "--timeout", "10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_real_commit_msg_hook_failure_keeps_run_unfinished(self):
        hook = self.repo / ".git/hooks/commit-msg"
        hook.write_text("#!/bin/sh\necho hook-rejected >&2\nexit 1\n")
        hook.chmod(0o755)
        before = self.git("rev-parse", "HEAD")
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertIn("hook-rejected", result.stderr)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertEqual(self.read_manifest()["status"], "ready_to_commit")
        hook.unlink()
        self.assertEqual(self.finish("--reuse").returncode, 0)
        self.assertNotIn("finish_error", self.read_manifest())

    def test_status_reports_existing_failed_reason_and_dispatch(self):
        self.manifest["failed_reason"] = "known failure"
        self.save()
        (self.repo / "run/r1.dispatch.jsonl").write_text(
            json.dumps(dict(role="writer", exit_code=9)) + "\n"
        )
        value = json.loads(self.cli("status", "--run-id", "r1", "--json").stdout)
        self.assertEqual(value["error_reason"], "known failure")
        self.assertEqual(value["last_dispatch"]["exit_code"], 9)

    def test_untracked_scope_files_cannot_be_committed(self):
        (self.repo / "new.py").write_text("new = 1\n")
        result = self.finish("--files", "code.py", "new.py")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing=", result.stderr)

    def test_crash_recovery_rejects_wrong_commit_parent(self):
        self.assertEqual(self.finish().returncode, 0)
        manifest = self.read_manifest()
        manifest.update(status="ready_to_commit", pre_commit_head="bad-parent")
        self.save(manifest)
        before = self.git("rev-parse", "HEAD")
        result = self.finish()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))


    def test_status_separates_full_suite_and_pending_manual(self):
        self.manifest.update(
            verification_commands=[
                {"command": "python3 -c pass", "scope": "full", "exit_code": 2},
                {"command": "python3 -m unittest tests.test_x", "scope": "related", "exit_code": 0},
            ],
            item_results={
                "1.1": {"status": "delivered", "files": ["code.py"], "evidence": "ran:x",
                        "observed": "看到列表", "observed_evidence": "pending-manual:開列表頁捲到底"},
                "1.2": {"status": "delivered", "files": ["code.py"], "evidence": "ran:x",
                        "observed": "看到回應", "observed_evidence": "ran:curl -> 200"},
            },
        )
        self.save()
        result = self.cli("status", "--run-id", "r1", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["full_suite"], 2)
        self.assertEqual(value["pending_manual"], [{"item": "1.1", "steps": "開列表頁捲到底"}])
        self.assertEqual(value["latest_verification"]["exit_code"], 0)
        text = self.cli("status", "--run-id", "r1").stdout
        self.assertIn("full_suite: 2 / pending_manual: 1", text)
        self.manifest["verification_commands"] = self.manifest["verification_commands"][1:]
        self.manifest["item_results"] = {}
        self.save()
        value = json.loads(self.cli("status", "--run-id", "r1", "--json").stdout)
        self.assertEqual((value["full_suite"], value["pending_manual"]), (None, []))



    def test_scope_accepts_symlink_entries_but_not_directories(self):
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "x.py").write_text("")
        (self.repo / "link").symlink_to("pkg")
        self.git("add", "link", "pkg/x.py")
        self.git("reset", "-q", "code.py")
        sys.path.insert(0, str(CLI.parent))
        import flow
        with self.assertRaises(ValueError):
            flow.scope_check(["pkg", "link"])
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            flow.scope_check(["link", "pkg/x.py"])
        finally:
            os.chdir(cwd)



if __name__ == "__main__":
    unittest.main()
