"""Local checks for the reuse scenario and paired comparison plan."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "evals/reuse-existing"


def load_runner():
    path = ROOT / ".agent-flow/scripts/skill_eval.py"
    spec = importlib.util.spec_from_file_location("skill_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_compare():
    path = ROOT / "evals/compare_practices.py"
    spec = importlib.util.spec_from_file_location("compare_practices", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReuseComparisonTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.fixture = Path(
            load_runner().build_fixture(str(CASE), self.workdir.name, "codex")
        )

    def check_case(self):
        result = subprocess.run(
            [
                sys.executable,
                str(CASE / "check.py"),
                str(self.fixture),
                str(self.fixture / "result.json"),
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout

    def test_existing_helper_passes(self):
        (self.fixture / "lib/receipt.py").write_text(
            "from lib.money import format_usd\n\ndef render_total(amount):\n"
            "    return 'Pay ' + format_usd(amount)\n",
            encoding="utf-8",
        )
        code, output = self.check_case()
        self.assertEqual(code, 0, output)

    def test_duplicate_money_rule_fails(self):
        (self.fixture / "lib/receipt.py").write_text(
            "def render_total(amount):\n    return f'Pay ${amount:,.2f}'\n",
            encoding="utf-8",
        )
        code, output = self.check_case()
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 金額行為正確且重用現有規則", output)

    def test_compare_dry_run_uses_two_distinct_rules(self):
        baseline = Path(self.workdir.name) / "baseline.md"
        baseline.write_text("older rule\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "evals/compare_practices.py"),
                "--baseline",
                str(baseline),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("case=reuse-existing", result.stdout)
        self.assertIn("candidate=", result.stdout)

    def test_baseline_rule_swap_keeps_fixture_clean(self):
        baseline = Path(self.workdir.name) / "baseline.md"
        baseline.write_text("older rule\n", encoding="utf-8")
        load_compare().set_practices(self.fixture, baseline)
        self.assertEqual(
            (self.fixture / ".agent-flow/PRACTICES.md").read_text(encoding="utf-8"),
            "older rule\n",
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.fixture,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(status, "")
        (self.fixture / ".agent-flow/PRACTICES.md").write_text(
            "agent changed this\n", encoding="utf-8"
        )
        changed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.fixture,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn(".agent-flow/PRACTICES.md", changed)


if __name__ == "__main__":
    unittest.main()
