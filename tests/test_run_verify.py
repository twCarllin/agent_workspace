"""run_verify.py 簿記 wrapper 的行為測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（wrapper 以 cwd 的 run/ 與 eval_state.json 為對象）。
"""
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_state  # noqa: E402
import run_verify  # noqa: E402


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


class RunVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def write_manifest(self, run_id="r1"):
        os.makedirs("run", exist_ok=True)
        with open(os.path.join("run", f"{run_id}.json"), "w", encoding="utf-8") as f:
            json.dump({"run_id": run_id, "verification_commands": []}, f)

    def read_manifest(self, run_id="r1"):
        with open(os.path.join("run", f"{run_id}.json"), encoding="utf-8") as f:
            return json.load(f)

    def read_events(self, run_id):
        with open(os.path.join("run", f"{run_id}.events.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_real_subprocess_v2_rejects_nested_then_reuses_approved_exclusion(self):
        subprocess.run(['git', 'init', '-q'], check=True, capture_output=True)
        self.write_manifest()
        manifest = self.read_manifest()
        manifest['evidence_schema'] = 2
        Path('run/r1.json').write_text(json.dumps(manifest))
        Path('agent_workspace').mkdir()
        subprocess.run(['git', '-C', 'agent_workspace', 'init', '-q'], check=True, capture_output=True)
        Path('agent_workspace/code.py').write_text('child')
        entry = Path(__file__).resolve().parents[1] / '.agent-flow/scripts/run_verify.py'
        argv = [sys.executable, str(entry), '--run-id', 'r1', '--cmd', 'python3 -c pass']
        blocked = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn('Untracked nested repository', self.read_manifest()['verification_commands'][-1]['error'])
        self.assertFalse(self.read_manifest()['verification_commands'][-1]['executed'])
        self.assertFalse(self.read_manifest()['local_test_passed'])
        self.assertEqual([ev['cmd'] for ev in self.read_events('r1')], ['verify_cmd'])
        Path('.git/info/exclude').write_text('agent_workspace/\n')
        first = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        record = self.read_manifest()['verification_commands'][-1]
        self.assertEqual(record['snapshot_kind'], 'inputs-v2')
        reused = subprocess.run(argv + ['--reuse'], capture_output=True, text=True)
        self.assertEqual(reused.returncode, 0, reused.stderr)
        self.assertTrue(self.read_manifest()['verification_commands'][-1]['reused'])
        manifest = self.read_manifest()
        self.assertTrue(manifest['local_test_passed'])
        self.assertIn('python3 -c pass -> exit=0; executed=False; reused=True', manifest['local_test_evidence'].splitlines())
        event = self.read_events('r1')[-1]
        self.assertEqual(event['cmd'], 'verified')
        self.assertEqual(event['args'], {'sub_task': None, 'verify_command': 'python3 -c pass', 'exit_code': 0,
            'executed': False, 'reused': True, 'evidence': 'python3 -c pass -> exit=0; executed=False; reused=True'})
        with Path('.git/info/exclude').open('a') as stream:
            stream.write('# approved scope changed\n')
        changed = subprocess.run(argv + ['--reuse'], capture_output=True, text=True)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertFalse(self.read_manifest()['verification_commands'][-1]['reused'])

    def test_arbitration_evidence_survives_failure_success_and_reuse(self):
        subprocess.run(['git', 'init', '-q'], check=True, capture_output=True)
        self.write_manifest()
        manifest = self.read_manifest()
        note = '仲裁：依原契約修正；豁免說明保留'
        manifest.update(evidence_schema=2, local_test_evidence=note, verify_passed=True)
        Path('run/r1.json').write_text(json.dumps(manifest))
        entry = Path(__file__).resolve().parents[1] / '.claude/hooks/run_verify.py'
        failure = "python3 -c 'raise SystemExit(3)'"
        success = 'python3 -c pass'
        expected = [note]
        for command, reuse, status in ((failure, False, 3), (success, False, 0),
                                       (success, True, 0), (success, True, 0)):
            argv = [sys.executable, str(entry), '--run-id', 'r1', '--cmd', command]
            if reuse:
                argv.append('--reuse')
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(result.returncode, status, result.stderr)
            summary = f'{command} -> exit={status}; executed={not reuse}; reused={reuse}'
            if summary not in expected:
                expected.append(summary)
            manifest = self.read_manifest()
            self.assertEqual(manifest['local_test_evidence'], '\n'.join(expected))
            self.assertEqual(manifest['local_test_passed'], status == 0)
            self.assertTrue(manifest['verify_passed'])

    def test_event_write_failure_is_warning_after_test_state_saved(self):
        self.write_manifest()
        Path("run/r1.events.jsonl").mkdir()
        entry = Path(__file__).resolve().parents[1] / '.claude/hooks/run_verify.py'
        result = subprocess.run([sys.executable, str(entry), '--run-id', 'r1', '--cmd', 'python3 -c pass'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('事件記錄寫入失敗', result.stderr)
        manifest = self.read_manifest()
        self.assertTrue(manifest['local_test_passed'])
        self.assertEqual(manifest['local_test_evidence'], 'python3 -c pass -> exit=0; executed=True; reused=False')
        self.assertEqual(manifest['verification_commands'][0]['command'], 'python3 -c pass')
        self.assertEqual(manifest['verification_commands'][0]['exit_code'], 0)

    def test_tier1_success_records_to_manifest_and_events(self):
        self.write_manifest()
        code = run_cli("--run-id", "r1", "--cmd", "python3 -c pass")
        self.assertEqual(code, 0)
        cmds = self.read_manifest()["verification_commands"]
        manifest = self.read_manifest()
        self.assertTrue(manifest["local_test_passed"])
        self.assertEqual(manifest["local_test_evidence"], "python3 -c pass -> exit=0; executed=True; reused=False")
        self.assertNotIn("verify_passed", manifest)
        verified = self.read_events("r1")[-1]
        self.assertEqual(verified["cmd"], "verified")
        self.assertEqual(verified["args"], {"sub_task": None, "verify_command": "python3 -c pass",
            "exit_code": 0, "executed": True, "reused": False, "evidence": manifest["local_test_evidence"]})
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["exit_code"], 0)
        ev = self.read_events("r1")[-2]
        self.assertEqual(ev["cmd"], "verify_cmd")
        self.assertIn("ts", ev)
        self.assertEqual(ev["args"]["exit_code"], 0)
        self.assertEqual(ev["args"]["verify_command"], "python3 -c pass")  # 2026-09-21：指令原文留痕

    def test_failing_command_exit_code_propagated_and_recorded(self):
        self.write_manifest()
        manifest = self.read_manifest()
        manifest.update(local_test_passed=True, verify_passed=True)
        Path("run/r1.json").write_text(json.dumps(manifest))
        code = run_cli("--run-id", "r1", "--cmd", "python3 -c 'raise SystemExit(3)'")
        self.assertEqual(code, 3)
        cmds = self.read_manifest()["verification_commands"]
        self.assertEqual(cmds[0]["exit_code"], 3)
        self.assertTrue(cmds[0]["executed"])
        manifest = self.read_manifest()
        self.assertFalse(manifest["local_test_passed"])
        self.assertTrue(manifest["verify_passed"])
        self.assertEqual(manifest["local_test_evidence"], "python3 -c 'raise SystemExit(3)' -> exit=3; executed=True; reused=False")
        self.assertEqual([ev["cmd"] for ev in self.read_events("r1")], ["verify_cmd"])

    def test_tier2_records_to_subtask_not_manifest(self):
        self.write_manifest()
        eval_state_cli("init", "--run-id", "r1")
        eval_state_cli("add-subtask", "--id", "1", "--name", "demo")
        code = run_cli("--run-id", "r1", "--sub-task", "1", "--cmd", "python3 -c pass")
        self.assertEqual(code, 0)
        with open("eval_state.json", encoding="utf-8") as f:
            st = json.load(f)["sub_tasks"][0]
        self.assertTrue(st["local_test_passed"])
        self.assertEqual(st["local_test_evidence"], "python3 -c pass -> exit=0; executed=True; reused=False")
        self.assertFalse(st["verify_passed"])
        verified = self.read_events("r1")[-1]
        self.assertEqual(verified["cmd"], "verified")
        self.assertEqual(verified["args"], {"sub_task": 1, "verify_command": "python3 -c pass", "exit_code": 0,
            "executed": True, "reused": False, "evidence": st["local_test_evidence"]})
        self.assertEqual(len(st["verification_commands"]), 1)
        self.assertEqual(self.read_manifest()["verification_commands"], [])  # manifest 不動
        ev = self.read_events("r1")[-2]
        self.assertEqual(ev["cmd"], "add-verification")
        self.assertEqual(ev["args"]["verify_command"], "python3 -c pass")  # Tier 2 路徑同樣留痕

    def test_missing_manifest_exits_before_running_command(self):
        code = run_cli("--run-id", "no-such", "--cmd", "python3 -c pass")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join("run", "no-such.json")))

    def test_state_present_but_no_subtask_flag_falls_back_to_manifest(self):
        self.write_manifest()
        eval_state_cli("init", "--run-id", "r1")
        code = run_cli("--run-id", "r1", "--cmd", "python3 -c pass")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.read_manifest()["verification_commands"]), 1)


class RunVerifyCacheTest(RunVerifyTest):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], check=True)
        self.write_manifest()
        manifest = self.read_manifest()
        manifest["evidence_schema"] = 2
        Path("run/r1.json").write_text(json.dumps(manifest))
        Path(".gitignore").write_text("counter\n")
        Path("input.py").write_text("one")
        self.command = "python3 -c \"from pathlib import Path; p=Path('counter'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\""

    def verify(self, reuse=False, command=None):
        return run_cli("--run-id", "r1", "--cmd", command or self.command,
                       *(["--reuse"] if reuse else []))

    def test_reuse_requires_optin_and_matching_inputs_environment(self):
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.verify(True), 0)
        self.assertEqual(Path("counter").read_text(), "1")
        self.assertTrue(self.read_manifest()["verification_commands"][-1]["reused"])
        self.assertFalse(self.read_manifest()["verification_commands"][-1]["executed"])
        Path("README.md").write_text("doc")
        self.assertEqual(self.verify(True), 0)
        Path("input.py").write_text("two")
        self.assertEqual(self.verify(True), 0)
        with mock.patch.dict(os.environ, {"CACHE_TEST_ENV": "changed"}):
            self.assertEqual(self.verify(True), 0)
        self.assertEqual(self.verify(), 0)
        self.assertEqual(Path("counter").read_text(), "4")

    def test_input_mutation_and_snapshot_errors_fail_closed(self):
        self.assertEqual(self.verify(command="python3 -c \"from pathlib import Path; Path('input.py').write_text('changed')\""), 2)
        record = self.read_manifest()["verification_commands"][-1]
        self.assertNotIn("snapshot", record)
        with mock.patch.object(run_verify.verification_snapshot, "input_snapshot_v2", side_effect=OSError("error")):
            self.assertEqual(self.verify(True), 2)
        self.assertNotIn("snapshot", self.read_manifest()["verification_commands"][-1])

    def test_snapshot_before_failure_records_blocked_without_command_side_effect(self):
        Path("agent_workspace").mkdir()
        subprocess.run(["git", "-C", "agent_workspace", "init", "-q"], check=True, capture_output=True)
        entry = Path(__file__).resolve().parents[1] / ".agent-flow/scripts/run_verify.py"
        proc = subprocess.run([sys.executable, str(entry), "--run-id", "r1", "--cmd", self.command],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertFalse(Path("counter").exists())
        record = self.read_manifest()["verification_commands"][-1]
        self.assertFalse(record["executed"])
        self.assertFalse(record["reused"])
        self.assertIn("Untracked nested repository", record["error"])
        self.assertIn("agent_workspace", record["error"])

    def test_snapshot_after_failure_records_actual_execution(self):
        entry = Path(__file__).resolve().parents[1] / ".agent-flow/scripts/run_verify.py"
        command = self.command + " && git init -q agent_workspace"
        proc = subprocess.run([sys.executable, str(entry), "--run-id", "r1", "--cmd", command],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(Path("counter").read_text(), "1")
        record = self.read_manifest()["verification_commands"][-1]
        self.assertTrue(record["executed"])
        self.assertFalse(record["reused"])
        self.assertIn("Untracked nested repository", record["error"])
        self.assertIn("agent_workspace", record["error"])

    def test_latest_failure_prevents_reusing_earlier_success(self):
        self.assertEqual(self.verify(), 0)
        real_run = subprocess.run
        with mock.patch.object(run_verify.subprocess, "run") as runner:
            def execute(*args, **kwargs):
                return subprocess.CompletedProcess(args[0], 3) if kwargs.get("shell") else real_run(*args, **kwargs)
            runner.side_effect = execute
            self.assertEqual(self.verify(), 3)
        self.assertEqual(self.verify(True), 0)
        self.assertEqual(Path("counter").read_text(), "2")

    def test_tier2_cache_is_scoped_to_same_run_and_subtask(self):
        eval_state_cli("init", "--run-id", "r1")
        eval_state_cli("add-subtask", "--id", "1", "--name", "demo")
        args = ("--run-id", "r1", "--sub-task", "1", "--cmd", self.command)
        self.assertEqual(run_cli(*args), 0)
        self.assertEqual(run_cli(*args, "--reuse"), 0)
        self.assertEqual(Path("counter").read_text(), "1")
        self.write_manifest("r2")
        self.assertEqual(run_cli("--run-id", "r2", "--sub-task", "1", "--cmd", self.command, "--reuse"), 2)

    def test_real_cli_and_compatibility_entrypoint_share_cache(self):
        root = Path(__file__).resolve().parents[1]
        for entry, extra in ((root / '.agent-flow/scripts/run_verify.py', []),
                             (root / '.claude/hooks/run_verify.py', ['--reuse'])):
            proc = subprocess.run([sys.executable, str(entry), '--run-id', 'r1',
                                   '--cmd', self.command, *extra], capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(Path('counter').read_text(), '1')

    def test_live_reuse_is_rejected_before_execution(self):
        for command in ("python3 harness_smoke.py --live", "python3 skill_eval.py", "codex exec test", "claude -p test"):
            self.assertEqual(self.verify(True, command), 2)


if __name__ == "__main__":
    unittest.main()
