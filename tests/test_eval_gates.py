"""eval_gates.py 的不變量與判定邏輯測試。

執行：python3 -m unittest discover -s tests -v
block() 以 sys.exit(2) 實作，測試以 SystemExit 斷言攔截行為。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_gates  # noqa: E402


def make_sub_task(**overrides):
    st = {
        "id": 1,
        "name": "demo",
        "status": "passed",
        "local_test_passed": True,
        "local_test_evidence": "pytest -q -> 12 passed",
        "rounds": [
            {
                "round": 1,
                "quality_score": 8,
                "deduction_reasons": [
                    {"points_lost": 1, "dimension": "Completeness", "reason": "r", "evidence": "a.py:1"},
                    {"points_lost": 1, "dimension": "Clarity", "reason": "r", "evidence": "a.py:2"},
                ],
            }
        ],
    }
    st.update(overrides)
    return st


class RoundsInvariantTest(unittest.TestCase):
    def test_valid_deduction_sum_passes(self):
        eval_gates.check_rounds_invariant(make_sub_task(), "test")

    def test_perfect_score_with_empty_deductions_passes(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 10, "deduction_reasons": []}])
        eval_gates.check_rounds_invariant(st, "test")

    def test_deduction_sum_mismatch_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 8, "deduction_reasons": []}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_quality_score_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "deduction_reasons": []}])
        with self.assertRaises(SystemExit):
            eval_gates.check_rounds_invariant(st, "test")


class ValidateStateTest(unittest.TestCase):
    def state(self, **overrides):
        return {"run_id": "t", "sub_tasks": [make_sub_task(**overrides)]}

    def test_complete_passed_state_passes(self):
        eval_gates.validate_state(self.state(), "test", require_passed=True)

    def test_missing_run_id_blocks(self):
        with self.assertRaises(SystemExit):
            eval_gates.validate_state({"sub_tasks": []}, "test")

    def test_status_not_passed_blocks(self):
        with self.assertRaises(SystemExit):
            eval_gates.validate_state(self.state(status="failed"), "test", require_passed=True)

    def test_local_test_not_passed_blocks(self):
        with self.assertRaises(SystemExit):
            eval_gates.validate_state(self.state(local_test_passed=False), "test", require_passed=True)

    def test_empty_evidence_blocks(self):
        with self.assertRaises(SystemExit):
            eval_gates.validate_state(self.state(local_test_evidence=""), "test", require_passed=True)
        with self.assertRaises(SystemExit):
            eval_gates.validate_state(self.state(local_test_evidence=None), "test", require_passed=True)

    def test_require_passed_false_skips_status_checks(self):
        eval_gates.validate_state(self.state(status="in_progress", local_test_passed=False), "test")


class ManifestPhaseTest(unittest.TestCase):
    def test_explicit_phase_wins(self):
        self.assertEqual(eval_gates.manifest_phase({"phase": "risk_done"}), "risk_done")

    def test_legacy_derivation_from_task_file(self):
        self.assertEqual(eval_gates.manifest_phase({"task_file": "task/x.md"}), "decomposed")

    def test_legacy_derivation_from_usage_report(self):
        self.assertEqual(
            eval_gates.manifest_phase({"usage_report_path": "usage/x.md"}), "usage_confirmed"
        )

    def test_default_is_init(self):
        self.assertEqual(eval_gates.manifest_phase({}), "init")

    def test_unknown_phase_falls_back_to_derivation(self):
        self.assertEqual(eval_gates.manifest_phase({"phase": "bogus"}), "init")


class GitCommitRegexTest(unittest.TestCase):
    def test_matches_plain_commit(self):
        self.assertTrue(eval_gates.GIT_COMMIT_RE.search("git commit -m 'x'"))

    def test_matches_commit_with_global_flags(self):
        self.assertTrue(eval_gates.GIT_COMMIT_RE.search("git -C /repo commit -m x"))

    def test_matches_commit_in_compound_command(self):
        self.assertTrue(eval_gates.GIT_COMMIT_RE.search("cd /repo && git commit --amend"))

    def test_ignores_other_git_commands(self):
        self.assertFalse(eval_gates.GIT_COMMIT_RE.search("git log --grep 'Run-Id: x'"))
        self.assertFalse(eval_gates.GIT_COMMIT_RE.search("git diff --cached"))


if __name__ == "__main__":
    unittest.main()
