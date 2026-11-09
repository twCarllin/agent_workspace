"""Verify metering status through both real CLI entries and historical stats."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".agent-flow/scripts"))
import stats


class UsageStatusTest(unittest.TestCase):
    def test_codex_status_and_history_preservation(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = run / "2026-10-26-old.json"
            old.write_text(
                json.dumps({"run_id": old.stem, "token_usage_status": "unknown_codex"})
            )
            original = old.read_bytes()
            for index, entry in enumerate((".agent-flow/scripts", ".claude/hooks")):
                path = run / f"2026-10-27-new{index}.json"
                path.write_text(json.dumps({"run_id": path.stem, "harness": "codex"}))
                result = subprocess.run(
                    [
                        sys.executable,
                        str(root / entry / "token_usage.py"),
                        path.stem,
                        "--dir",
                        directory,
                        "--write",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads(path.read_text())
                self.assertEqual(manifest["token_usage_status"], "unknown")
                self.assertIsNone(manifest["token_usage"]["main"])
                self.assertIsNone(manifest["subagent_usage"]["main"])
            (run / "2026-10-27-missing.json").write_text(
                json.dumps({"run_id": "2026-10-27-missing"})
            )
            data = stats.collect(directory)
            self.assertEqual(
                dict(data["token_usage_statuses"]),
                {"unknown_codex": 1, "unknown": 2, "missing": 1},
            )
            output = stats.report(data)
            self.assertIn("歷史未知（Codex）1", output)
            self.assertIn("資料缺失 1 個 run", output)
            self.assertEqual(old.read_bytes(), original)
