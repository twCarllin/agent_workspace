"""run_verify.py 簿記 wrapper 的行為測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（wrapper 以 cwd 的 run/ 與 eval_state.json 為對象）。
"""

import json
import os
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_state  # noqa: E402
import run_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agent-flow/scripts/run_verify.py"
HOOK = ROOT / ".claude/hooks/run_verify.py"
PASS_CMD = "python3 -c pass"


def run_cli(*argv):
    """跑 wrapper 並回傳 exit code（main 一律 sys.exit）。"""
    with mock.patch.object(sys, "argv", ["run_verify.py", *argv]):
        try:
            run_verify.main()
        except SystemExit as e:
            return e.code or 0
    return 0


def eval_state_cli(*argv):
    with mock.patch.object(sys, "argv", ["eval_state.py", *argv]):
        eval_state.main()


def run_entry(entry, command, *extra):
    """以真實 subprocess 跑指定入口（r1）。"""
    return subprocess.run(
        [sys.executable, str(entry), "--run-id", "r1", "--cmd", command, *extra],
        capture_output=True,
        text=True,
    )


def verified_args(command, evidence, sub_task=None, executed=True, reused=False):
    return {
        "sub_task": sub_task,
        "verify_command": command,
        "exit_code": 0,
        "executed": executed,
        "reused": reused,
        "evidence": evidence,
    }


def init_subtask():
    eval_state_cli("init", "--run-id", "r1")
    eval_state_cli("add-subtask", "--id", "1", "--name", "demo")


def git_init(*path):
    subprocess.run(["git", *path, "init", "-q"], check=True, capture_output=True)


class RunVerifyFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def write_manifest(self, run_id="r1", **extra):
        os.makedirs("run", exist_ok=True)
        data = {"run_id": run_id, "verification_commands": [], **extra}
        Path("run", f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")

    def read_manifest(self, run_id="r1"):
        with open(os.path.join("run", f"{run_id}.json"), encoding="utf-8") as f:
            return json.load(f)

    def read_events(self, run_id):
        with open(os.path.join("run", f"{run_id}.events.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def last_record(self):
        return self.read_manifest()["verification_commands"][-1]


class RunVerifyTest(RunVerifyFixture, unittest.TestCase):
    def test_growth_ratio_counts_staged_test_lines_against_code(self):
        git_init()
        self.assertIsNone(run_verify.test_growth_ratio())
        Path("src.py").write_text("a\n")
        Path("tests").mkdir()
        Path("tests/test_src.py").write_text("x\ny\nz\n")
        subprocess.run(["git", "add", "."], check=True)
        self.assertEqual(run_verify.test_growth_ratio(), 3.0)

    def test_rerun_reasons_real_subprocess(self):
        git_init()
        self.write_manifest(evidence_schema=2)
        command = """python3 -c 'from pathlib import Path; raise SystemExit(0 if Path("ok").exists() else 1)'"""
        for expected, extra in (
            (1, []),
            (1, []),
            (0, []),
            (0, ["--rerun-reason", "user_requested"]),
            (2, []),
        ):
            if expected == 0:
                Path("ok").touch()
            result = run_entry(SCRIPT, command, *extra)
            self.assertEqual(result.returncode, expected, result.stderr)
        records = self.read_manifest()["verification_commands"]
        self.assertNotIn("rerun_reason", records[0])
        self.assertEqual(
            [row["rerun_reason"] for row in records[1:]],
            ["previous_failed", "input_changed", "user_requested"],
        )
        self.assertTrue(all(row["elapsed_seconds"] >= 0 for row in records))
        event = [row for row in self.read_events("r1") if row["cmd"] == "verify_cmd"][
            -1
        ]
        self.assertEqual(event["args"]["rerun_reason"], "user_requested")
        self.assertGreaterEqual(event["args"]["elapsed_seconds"], 0)

    def test_repeat_blocked_before_subprocess_for_both_entries(self):
        git_init()
        self.write_manifest(evidence_schema=2)
        command = """python3 -c 'from pathlib import Path; p=Path("run/count"); p.write_text(p.read_text()+"x" if p.exists() else "x")'"""
        first = run_entry(SCRIPT, command)
        self.assertEqual(first.returncode, 0, first.stderr)
        for entry in (SCRIPT, HOOK):
            original = Path("run/r1.json").read_bytes()
            blocked = run_entry(entry, command)
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("rerun_reason_required", blocked.stderr)
            self.assertEqual(Path("run/count").read_text(), "x")
            self.assertEqual(Path("run/r1.json").read_bytes(), original)
        refreshed = run_entry(HOOK, command, "--rerun-reason", "evidence_refresh")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertEqual(Path("run/count").read_text(), "xx")

    def test_real_subprocess_v2_rejects_nested_then_reuses_approved_exclusion(self):
        git_init()
        self.write_manifest(evidence_schema=2)
        Path("agent_workspace").mkdir()
        git_init("-C", "agent_workspace")
        Path("agent_workspace/code.py").write_text("child")
        blocked = run_entry(SCRIPT, PASS_CMD)
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        record = self.last_record()
        self.assertIn("Untracked nested repository", record["error"])
        self.assertFalse(record["executed"])
        self.assertFalse(self.read_manifest()["local_test_passed"])
        self.assertEqual([ev["cmd"] for ev in self.read_events("r1")], ["verify_cmd"])
        Path(".git/info/exclude").write_text("agent_workspace/\n")
        first = run_entry(SCRIPT, PASS_CMD)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.last_record()["snapshot_kind"], "inputs-v2")
        reused = run_entry(SCRIPT, PASS_CMD, "--reuse")
        self.assertEqual(reused.returncode, 0, reused.stderr)
        self.assertTrue(self.last_record()["reused"])
        self.assertNotIn("rerun_reason", self.last_record())
        manifest = self.read_manifest()
        self.assertTrue(manifest["local_test_passed"])
        evidence = "python3 -c pass -> exit=0; executed=False; reused=True"
        self.assertIn(evidence, manifest["local_test_evidence"].splitlines())
        event = self.read_events("r1")[-1]
        self.assertEqual(event["cmd"], "verified")
        self.assertEqual(
            event["args"],
            verified_args(PASS_CMD, evidence, executed=False, reused=True),
        )
        with Path(".git/info/exclude").open("a") as stream:
            stream.write("# approved scope changed\n")
        changed = run_entry(SCRIPT, PASS_CMD, "--reuse")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertFalse(self.last_record()["reused"])

    def test_arbitration_evidence_survives_failure_success_and_reuse(self):
        git_init()
        note = "仲裁：依原契約修正；豁免說明保留"
        self.write_manifest(
            evidence_schema=2, local_test_evidence=note, verify_passed=True
        )
        failure = "python3 -c 'raise SystemExit(3)'"
        expected = [note]
        for command, reuse, status in (
            (failure, False, 3),
            (PASS_CMD, False, 0),
            (PASS_CMD, True, 0),
            (PASS_CMD, True, 0),
        ):
            result = run_entry(HOOK, command, *(["--reuse"] if reuse else []))
            self.assertEqual(result.returncode, status, result.stderr)
            summary = (
                f"{command} -> exit={status}; executed={not reuse}; reused={reuse}"
            )
            if summary not in expected:
                expected.append(summary)
            manifest = self.read_manifest()
            self.assertEqual(manifest["local_test_evidence"], "\n".join(expected))
            self.assertEqual(manifest["local_test_passed"], status == 0)
            self.assertTrue(manifest["verify_passed"])

    def test_event_write_failure_is_warning_after_test_state_saved(self):
        self.write_manifest()
        Path("run/r1.events.jsonl").mkdir()
        result = run_entry(HOOK, PASS_CMD)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.read_manifest()
        self.assertTrue(manifest["local_test_passed"])
        self.assertEqual(
            manifest["local_test_evidence"],
            "python3 -c pass -> exit=0; executed=True; reused=False",
        )
        self.assertEqual(manifest["verification_commands"][0]["command"], PASS_CMD)
        self.assertEqual(manifest["verification_commands"][0]["exit_code"], 0)

    def test_tier1_records_to_manifest_and_events(self):
        for name, command, code, preset in (
            ("success", PASS_CMD, 0, {}),
            (
                "failure exit code propagated",
                "python3 -c 'raise SystemExit(3)'",
                3,
                {"local_test_passed": True, "verify_passed": True},
            ),
        ):
            with self.subTest(name):
                shutil.rmtree("run", ignore_errors=True)
                self.write_manifest(**preset)
                self.assertEqual(run_cli("--run-id", "r1", "--cmd", command), code)
                manifest = self.read_manifest()
                evidence = f"{command} -> exit={code}; executed=True; reused=False"
                (record,) = manifest["verification_commands"]
                self.assertEqual(
                    (record["exit_code"], record["executed"]), (code, True)
                )
                self.assertEqual(manifest["local_test_passed"], code == 0)
                self.assertEqual(manifest["local_test_evidence"], evidence)
                self.assertEqual(
                    manifest.get("verify_passed"), preset.get("verify_passed")
                )
                events = self.read_events("r1")
                (vc,) = [ev for ev in events if ev["cmd"] == "verify_cmd"]
                self.assertIn("ts", vc)
                self.assertEqual(vc["args"]["exit_code"], code)
                self.assertEqual(
                    vc["args"]["verify_command"], command
                )  # 2026-09-21 留痕
                if code == 0:
                    self.assertEqual(events[-1]["cmd"], "verified")
                    self.assertEqual(
                        events[-1]["args"], verified_args(command, evidence)
                    )
                else:
                    self.assertEqual([ev["cmd"] for ev in events], ["verify_cmd"])

    def test_tier2_records_to_subtask_not_manifest(self):
        self.write_manifest()
        init_subtask()
        code = run_cli("--run-id", "r1", "--sub-task", "1", "--cmd", PASS_CMD)
        self.assertEqual(code, 0)
        with open("eval_state.json", encoding="utf-8") as f:
            st = json.load(f)["sub_tasks"][0]
        self.assertTrue(st["local_test_passed"])
        self.assertEqual(
            st["local_test_evidence"],
            "python3 -c pass -> exit=0; executed=True; reused=False",
        )
        self.assertFalse(st["verify_passed"])
        verified = self.read_events("r1")[-1]
        self.assertEqual(verified["cmd"], "verified")
        self.assertEqual(
            verified["args"],
            verified_args(PASS_CMD, st["local_test_evidence"], sub_task=1),
        )
        self.assertEqual(len(st["verification_commands"]), 1)
        self.assertEqual(self.read_manifest()["verification_commands"], [])
        ev = self.read_events("r1")[-2]
        self.assertEqual(ev["cmd"], "add-verification")
        self.assertEqual(ev["args"]["verify_command"], PASS_CMD)

    def test_missing_manifest_exits_before_running_command(self):
        self.assertEqual(run_cli("--run-id", "no-such", "--cmd", PASS_CMD), 2)
        self.assertFalse(os.path.exists(os.path.join("run", "no-such.json")))

    def test_state_present_but_no_subtask_flag_falls_back_to_manifest(self):
        self.write_manifest()
        eval_state_cli("init", "--run-id", "r1")
        self.assertEqual(run_cli("--run-id", "r1", "--cmd", PASS_CMD), 0)
        self.assertEqual(len(self.read_manifest()["verification_commands"]), 1)


class RunVerifyCacheTest(RunVerifyFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        git_init()
        self.write_manifest(evidence_schema=2)
        Path(".gitignore").write_text("counter\n")
        Path("input.py").write_text("one")
        self.command = "python3 -c \"from pathlib import Path; p=Path('counter'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\""

    def verify(self, reuse=False, command=None, reason=None):
        return run_cli(
            "--run-id",
            "r1",
            "--cmd",
            command or self.command,
            *(["--reuse"] if reuse else []),
            *(["--rerun-reason", reason] if reason else []),
        )

    def test_reuse_requires_optin_and_matching_inputs_environment(self):
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.verify(True), 0)
        self.assertEqual(Path("counter").read_text(), "1")
        self.assertTrue(self.last_record()["reused"])
        self.assertNotIn("rerun_reason", self.last_record())
        self.assertFalse(self.last_record()["executed"])
        Path("README.md").write_text("doc")
        self.assertEqual(self.verify(True), 0)
        Path("input.py").write_text("two")
        self.assertEqual(self.verify(True), 0)
        with mock.patch.dict(os.environ, {"CACHE_TEST_ENV": "changed"}):
            self.assertEqual(self.verify(True, reason="environment_changed"), 0)
        self.assertEqual(self.verify(reason="environment_changed"), 0)
        self.assertEqual(Path("counter").read_text(), "4")

    def test_input_mutation_and_snapshot_errors_fail_closed(self):
        mutate = "python3 -c \"from pathlib import Path; Path('input.py').write_text('changed')\""
        self.assertEqual(self.verify(command=mutate), 2)
        self.assertNotIn("snapshot", self.last_record())
        with mock.patch.object(
            run_verify.verification_snapshot,
            "input_snapshot_v2",
            side_effect=OSError("error"),
        ):
            self.assertEqual(self.verify(True), 2)
        self.assertNotIn("snapshot", self.last_record())

    def test_nested_repository_snapshot_before_and_after_execution(self):
        for name, precreate, command, counter, executed in (
            ("before execution blocks command", True, self.command, None, False),
            (
                "after execution records actual run",
                False,
                self.command + " && git init -q agent_workspace",
                "1",
                True,
            ),
        ):
            with self.subTest(name):
                shutil.rmtree("agent_workspace", ignore_errors=True)
                Path("counter").unlink(missing_ok=True)
                self.write_manifest(evidence_schema=2)
                if precreate:
                    Path("agent_workspace").mkdir()
                    git_init("-C", "agent_workspace")
                proc = run_entry(SCRIPT, command)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                if counter is None:
                    self.assertFalse(Path("counter").exists())
                else:
                    self.assertEqual(Path("counter").read_text(), counter)
                record = self.last_record()
                self.assertEqual(record["executed"], executed)
                self.assertFalse(record["reused"])
                self.assertIn("Untracked nested repository", record["error"])
                self.assertIn("agent_workspace", record["error"])

    def test_latest_failure_prevents_reusing_earlier_success(self):
        self.assertEqual(self.verify(), 0)
        real_run = subprocess.run
        with mock.patch.object(run_verify.subprocess, "run") as runner:

            def execute(*args, **kwargs):
                return (
                    subprocess.CompletedProcess(args[0], 3)
                    if kwargs.get("shell")
                    else real_run(*args, **kwargs)
                )

            runner.side_effect = execute
            self.assertEqual(self.verify(reason="evidence_refresh"), 3)
        self.assertEqual(self.verify(True), 0)
        self.assertEqual(Path("counter").read_text(), "2")

    def test_tier2_cache_is_scoped_to_same_run_and_subtask(self):
        init_subtask()
        args = ("--run-id", "r1", "--sub-task", "1", "--cmd", self.command)
        self.assertEqual(run_cli(*args), 0)
        self.assertEqual(run_cli(*args, "--reuse"), 0)
        self.assertEqual(Path("counter").read_text(), "1")
        self.write_manifest("r2")
        self.assertEqual(
            run_cli(
                "--run-id", "r2", "--sub-task", "1", "--cmd", self.command, "--reuse"
            ),
            2,
        )

    def test_real_cli_and_compatibility_entrypoint_share_cache(self):
        for entry, extra in ((SCRIPT, []), (HOOK, ["--reuse"])):
            proc = run_entry(entry, self.command, *extra)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path("counter").read_text(), "1")

    def test_live_reuse_is_rejected_before_execution(self):
        for command in (
            "python3 harness_smoke.py --live",
            "python3 skill_eval.py",
            "codex exec test",
            "claude -p test",
        ):
            self.assertEqual(self.verify(True, command), 2)

    def test_quiet_failure_shows_tail_and_retains_full_output(self):
        command = "python3 -c \"print('failure detail'); raise SystemExit(7)\""
        result = run_entry(SCRIPT, command, "--quiet-success")
        self.assertEqual(result.returncode, 7)
        self.assertIn("failure detail", result.stderr)
        output = Path(self.last_record()["output_file"])
        self.assertIn("failure detail", output.read_text())

    def test_quiet_success_saves_full_output_and_reuse_preserves_log(self):
        command = "python3 -c \"print('full output')\""
        first = run_entry(SCRIPT, command, "--quiet-success")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn("full output", first.stdout)
        output = Path(self.last_record()["output_file"])
        self.assertEqual(output.read_text(), "full output\n")
        reused = run_entry(SCRIPT, command, "--quiet-success", "--reuse")
        self.assertEqual(reused.returncode, 0, reused.stderr)
        self.assertEqual(self.last_record()["output_file"], str(output))
        self.assertEqual(output.read_text(), "full output\n")

    def test_quiet_reuse_executes_if_prior_success_has_no_output_file(self):
        command = "python3 -c \"print('saved on second run')\""
        first = run_entry(SCRIPT, command)
        self.assertEqual(first.returncode, 0, first.stderr)
        result = run_entry(
            SCRIPT,
            command,
            "--quiet-success",
            "--reuse",
            "--rerun-reason",
            "evidence_refresh",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.last_record()
        self.assertTrue(record["executed"])
        self.assertFalse(record["reused"])
        self.assertIn("saved on second run", Path(record["output_file"]).read_text())


if __name__ == "__main__":
    unittest.main()
