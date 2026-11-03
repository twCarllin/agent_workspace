"""Black-box context index and dispatch contracts, including real CLI execution."""

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
