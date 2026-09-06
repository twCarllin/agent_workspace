"""run_verify.py 簿記 wrapper 的行為測試。

執行：python3 -m unittest discover -s tests -v
在暫存目錄操作真實檔案（wrapper 以 cwd 的 run/ 與 eval_state.json 為對象）。
"""
import json
import os
import sys
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

    def test_tier1_success_records_to_manifest_and_events(self):
        self.write_manifest()
        code = run_cli("--run-id", "r1", "--cmd", "python3 -c pass")
        self.assertEqual(code, 0)
        cmds = self.read_manifest()["verification_commands"]
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["exit_code"], 0)
        ev = self.read_events("r1")[-1]
        self.assertEqual(ev["cmd"], "verify_cmd")
        self.assertIn("ts", ev)
        self.assertEqual(ev["args"]["exit_code"], 0)

    def test_failing_command_exit_code_propagated_and_recorded(self):
        self.write_manifest()
        code = run_cli("--run-id", "r1", "--cmd", "python3 -c 'raise SystemExit(3)'")
        self.assertEqual(code, 3)
        cmds = self.read_manifest()["verification_commands"]
        self.assertEqual(cmds[0]["exit_code"], 3)

    def test_tier2_records_to_subtask_not_manifest(self):
        self.write_manifest()
        eval_state_cli("init", "--run-id", "r1")
        eval_state_cli("add-subtask", "--id", "1", "--name", "demo")
        code = run_cli("--run-id", "r1", "--sub-task", "1", "--cmd", "python3 -c pass")
        self.assertEqual(code, 0)
        with open("eval_state.json", encoding="utf-8") as f:
            st = json.load(f)["sub_tasks"][0]
        self.assertEqual(len(st["verification_commands"]), 1)
        self.assertEqual(self.read_manifest()["verification_commands"], [])  # manifest 不動

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


if __name__ == "__main__":
    unittest.main()
