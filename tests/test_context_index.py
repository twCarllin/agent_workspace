"""Black-box context index and dispatch contracts, including real CLI execution."""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent-flow/scripts"


class ContextIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "run").mkdir()
        (self.root / "source.py").write_text(
            "literal.* target\nother\n", encoding="utf-8"
        )
        (self.root / "ignored.py").write_text("literal.*\n", encoding="utf-8")
        self.index = "run/pilot.context.json"

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "context_index.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def build(self, *extra):
        return self.cli(
            "build",
            "--run-id",
            "pilot",
            "--files",
            "source.py",
            "--query",
            "literal.*",
            "--output",
            self.index,
            *extra
        )

    def test_literal_locations_hash_and_events_real_cli(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads((self.root / self.index).read_text())
        self.assertEqual(packet["files"], ["source.py"])
        self.assertEqual(
            packet["matches"],
            [
                dict(
                    file="source.py",
                    line=1,
                    query="literal.*",
                    snippet="literal.* target",
                )
            ],
        )
        self.assertEqual(len(packet["sources"]["source.py"]), 64)
        self.assertEqual(packet["review_decision"], "not_evaluated")
        result = self.cli("validate", "--index", self.index, "--run-id", "pilot")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [
            json.loads(row)
            for row in (self.root / "run/pilot.events.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [row["args"]["action"] for row in events], ["build", "validate"]
        )

    def test_source_and_query_drift_rejected(self):
        self.assertEqual(self.build().returncode, 0)
        path = self.root / self.index
        packet = json.loads(path.read_text())
        packet["queries"] = ["other"]
        path.write_text(json.dumps(packet))
        self.assertNotEqual(self.cli("validate", "--index", self.index).returncode, 0)
        self.assertEqual(self.build().returncode, 0)
        (self.root / "source.py").write_text("changed")
        self.assertNotEqual(self.cli("validate", "--index", self.index).returncode, 0)

    def test_paths_and_size_fail_closed(self):
        for source in ("../outside.py", str(self.root / "source.py")):
            with self.subTest(source=source):
                result = self.cli(
                    "build",
                    "--run-id",
                    "pilot",
                    "--files",
                    source,
                    "--query",
                    "literal",
                    "--output",
                    self.index,
                )
                self.assertNotEqual(result.returncode, 0)
        (self.root / "escape.py").symlink_to(ROOT / "init.sh")
        self.assertNotEqual(
            self.cli(
                "build",
                "--run-id",
                "pilot",
                "--files",
                "escape.py",
                "--query",
                "literal",
                "--output",
                self.index,
            ).returncode,
            0,
        )
        self.assertNotEqual(self.build("--output", "run/pilot.json").returncode, 0)
        (self.root / "source.py").write_text("literal.*\n" * 65)
        self.assertNotEqual(self.build().returncode, 0)
        (self.root / "source.py").write_bytes(b"x" * 1048577)
        self.assertNotEqual(self.build().returncode, 0)

    def test_output_aliases_rejected_without_changing_sources(self):
        original = (self.root / "source.py").read_bytes()
        target = self.root / self.index
        for alias in ("symlink", "spelling", "hardlink"):
            with self.subTest(alias=alias):
                if alias == "symlink":
                    target.symlink_to(self.root / "source.py")
                    source = "source.py"
                elif alias == "hardlink":
                    os.link(self.root / "source.py", target)
                    source = "source.py"
                else:
                    target.write_bytes(original)
                    source = "./" + self.index
                result = self.build("--files", source)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual((self.root / "source.py").read_bytes(), original)
                self.assertEqual(target.read_bytes(), original)
                target.unlink()

    def test_cli_diagnostics_and_filter_preserve_results_and_events(self):
        built = self.build("--log-format", "json")
        checked = self.cli(
            "--log-format",
            "json",
            "validate",
            "--index",
            self.index,
            "--run-id",
            "pilot",
        )
        failed = self.build("--log-format", "json", "--files", "missing.py")
        cases = (
            (built, "build_completed", "INFO", "success", 0),
            (checked, "validate_completed", "INFO", "success", 0),
            (failed, "operation_failed", "ERROR", "failure", 2),
        )
        for result, event, level, outcome, exit_code in cases:
            with self.subTest(event=event):
                self.assertEqual(result.returncode, exit_code)
                rows = result.stderr.splitlines()
                self.assertEqual(len(rows), 1)
                diagnostic = json.loads(rows[0])
                self.assertEqual(diagnostic["event"], "context_index." + event)
                self.assertEqual(diagnostic["level"], level)
                self.assertEqual(diagnostic["outcome"], outcome)
                self.assertEqual(diagnostic["exit_code"], exit_code)
                self.assertEqual(diagnostic["run_id"], "pilot")
                self.assertIsInstance(diagnostic["logger"], str)
                self.assertTrue(diagnostic["logger"])
                self.assertTrue(diagnostic["message"])
                self.assertEqual(
                    datetime.fromisoformat(diagnostic["timestamp"])
                    .utcoffset()
                    .total_seconds(),
                    0,
                )
                self.assertNotIn("literal.*", result.stderr)
                if exit_code == 0:
                    self.assertEqual(
                        json.loads(result.stdout)["review_decision"], "not_evaluated"
                    )
                else:
                    self.assertEqual(result.stdout, "")
        filtered = self.build("--log-level", "ERROR", "--log-format", "json")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        self.assertEqual(filtered.stderr, "")
        self.assertEqual(json.loads(filtered.stdout), json.loads(built.stdout))
        events = [
            json.loads(row)
            for row in (self.root / "run/pilot.events.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [row["args"]["action"] for row in events], ["build", "validate", "build"]
        )
        text = self.build()
        self.assertEqual(text.returncode, 0, text.stderr)
        for key in (
            "timestamp",
            "level",
            "logger",
            "event",
            "message",
            "run_id",
            "outcome",
            "exit_code",
        ):
            self.assertIn(key + "=", text.stderr)
        self.assertEqual(json.loads(text.stdout), json.loads(built.stdout))

    def test_dispatch_reuses_hints_and_rejects_stale_before_backend(self):
        self.assertEqual(self.build().returncode, 0)
        (self.root / "eval_state.json").write_text(json.dumps({"run_id": "pilot"}))
        (self.root / "prompt.md").write_text("Do assigned work")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(
            "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
            'Path("called.txt").write_text(sys.stdin.read())\n'
            'print(json.dumps({"type":"result", "result":"Self-check: done", "is_error":False}))\n'
        )
        fake.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
        for role in ("code-writer", "code-reviewer"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "dispatch.py"),
                    role,
                    "--prompt-file",
                    "prompt.md",
                    "--backend",
                    "claude",
                    "--context-index",
                    self.index,
                ],
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertIn(result.returncode, (0, 2), result.stderr)
            prompt = (self.root / "called.txt").read_text()
            self.assertIn("index does not mean implementation is verified", prompt)
            self.assertIn("staged diff", prompt)
        record = json.loads(
            (self.root / "run/pilot.dispatch.jsonl").read_text().splitlines()[-1]
        )
        self.assertEqual(set(record["context_index"]), {"index_id", "size_bytes"})
        self.assertNotIn("literal.*", json.dumps(record))
        (self.root / "called.txt").unlink()
        (self.root / "source.py").write_text("changed")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "dispatch.py"),
                "code-writer",
                "--prompt-file",
                "prompt.md",
                "--context-index",
                self.index,
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.root / "called.txt").exists())

    def test_stats_uses_actual_events_and_marks_missing_duration(self):
        self.assertEqual(self.build().returncode, 0)
        (self.root / "run/pilot.json").write_text(json.dumps({"run_id": "pilot"}))
        with (self.root / "run/pilot.events.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"cmd": "context-index", "args": {"action": "reuse"}}) + "\n"
            )
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "stats.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build 1 筆", result.stdout)
        self.assertIn("validate 0 筆，耗時無記錄", result.stdout)
        self.assertIn("reuse 1 筆，耗時無記錄", result.stdout)
        self.assertIn("不推估", result.stdout)
