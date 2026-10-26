"""Black-box and unit checks for evaluation evidence audits."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "evals/evidence_audit.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("evidence_audit", AUDIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvidenceAuditTest(unittest.TestCase):
    def setUp(self):
        self.audit = load_audit()

    def pair(self, old="pass", new="pass"):
        return {
            "records": [
                {
                    "variant": "baseline",
                    "run": 1,
                    "verdict": old,
                    "duration_seconds": 10,
                    "cost_usd": None,
                },
                {
                    "variant": "candidate",
                    "run": 1,
                    "verdict": new,
                    "duration_seconds": 7,
                    "cost_usd": None,
                },
            ]
        }

    def test_paired_quality_and_time_are_separate(self):
        outcome = self.audit.assess_comparison(self.pair("fail", "pass"))
        self.assertEqual(outcome["quality_delta"], 1)
        self.assertEqual(outcome["seconds_delta"], -3)
        self.assertEqual(outcome["cost_status"], "unknown")

    def test_incomplete_or_tool_error_cannot_be_compared(self):
        for records in (
            self.pair()["records"][:1],
            self.pair("error", "pass")["records"],
            [
                dict(self.pair()["records"][0], duration_seconds=None),
                self.pair()["records"][1],
            ],
        ):
            with self.subTest(records=records):
                self.assertEqual(
                    self.audit.assess_comparison({"records": records})["status"],
                    "insufficient",
                )

    def test_old_results_expose_missing_reproduction_data(self):
        old = json.loads(
            (
                ROOT / "evals/results/2026-10-24T15-15-39-practice-compare.json"
            ).read_text()
        )
        self.assertIn("case_files_sha256", self.audit.provenance_gaps(old))
        self.assertEqual(
            self.audit.provenance_gaps(
                {
                    "provenance": {
                        **{key: "recorded" for key in self.audit.REQUIRED_PROVENANCE},
                        "source_clean": True,
                    }
                }
            ),
            [],
        )

    def test_new_provenance_captures_real_sources_without_model_call(self):
        spec = importlib.util.spec_from_file_location(
            "eval_provenance", ROOT / ".agent-flow/scripts/eval_provenance.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record = module.collect(
            ROOT / "evals/reuse-existing",
            ROOT / "evals/compare_practices.py",
            "git",
            "edits",
            90,
        )
        gaps = self.audit.provenance_gaps({"provenance": record})
        self.assertEqual(gaps, [] if record["source_clean"] else ["source_clean"])
        self.assertIn("prompt.md", record["case_files_sha256"])
        self.assertEqual(record["timeout_seconds"], 90)

    def test_handoff_requires_attempts_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example-blocked.md"
            path.write_text(
                "## 重現步驟\ncmd\n## 目前的根因假設\nunknown\n"
                "## 使用者裁決\nresume\n",
                encoding="utf-8",
            )
            self.assertIn("失敗嘗試與結果", self.audit.assess_handoff(path))
            self.assertIn("證據位置", self.audit.assess_handoff(path))
            path.write_text(
                path.read_text() + "## 失敗嘗試與結果\n尚未嘗試：原因\n"
                "## 證據位置\nrun/example.log\n",
                encoding="utf-8",
            )
            self.assertEqual(self.audit.assess_handoff(path), [])

    def test_cli_audits_real_records_and_reports_no_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(AUDIT), "--run-dir", directory],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("重現缺項=", result.stdout)
            self.assertIn("真實卡點報告：0 份", result.stdout)


if __name__ == "__main__":
    unittest.main()
