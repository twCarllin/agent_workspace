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
        "review_reds": 2,
        "verify_passed": True,
        "rounds": [
            {
                "round": 1,
                "quality_score": 8,
                "deduction_reasons": [
                    {"points_lost": 1, "dimension": "Completeness", "reason": "r", "evidence": "a.py:1"},
                    {"points_lost": 1, "dimension": "Clarity", "reason": "r", "evidence": "a.py:2"},
                ],
                "dimensions": {
                    "Correctness": 2,
                    "Completeness": 1,
                    "Clarity": 1,
                    "Test_Quality": 2,
                    "Maintainability": 2,
                },
            }
        ],
    }
    st.update(overrides)
    return st


class RoundsInvariantTest(unittest.TestCase):
    def test_valid_deduction_sum_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        eval_gates.check_rounds_invariant(make_sub_task(), "test")

    def test_perfect_score_with_empty_deductions_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 10, "deduction_reasons": [], "dimensions": {"A": 4, "B": 3, "C": 3}}])
        eval_gates.check_rounds_invariant(st, "test")

    def test_deduction_sum_mismatch_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 8, "deduction_reasons": [], "dimensions": {"A": 8}}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_quality_score_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "deduction_reasons": [], "dimensions": {"A": 10}}])
        with self.assertRaises(SystemExit):
            eval_gates.check_rounds_invariant(st, "test")

    def test_missing_dimensions_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 8, "deduction_reasons": [
            {"points_lost": 2, "dimension": "A", "reason": "r", "evidence": "e"},
        ]}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)

    def test_empty_dimensions_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 0, "deduction_reasons": [
            {"points_lost": 10, "dimension": "A", "reason": "r", "evidence": "e"},
        ], "dimensions": {}}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)

    def test_non_numeric_dimension_value_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 8, "deduction_reasons": [
            {"points_lost": 2, "dimension": "A", "reason": "r", "evidence": "e"},
        ], "dimensions": {"A": 6, "B": None, "C": 2}}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)

    def test_dimensions_sum_mismatch_blocks(self):
        st = make_sub_task(rounds=[{"round": 1, "quality_score": 8, "deduction_reasons": [
            {"points_lost": 2, "dimension": "A", "reason": "r", "evidence": "e"},
        ], "dimensions": {"A": 5, "B": 2}}])
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_rounds_invariant(st, "test")
        self.assertEqual(ctx.exception.code, 2)


class ValidateStateTest(unittest.TestCase):
    def state(self, **overrides):
        return {"run_id": "t", "sub_tasks": [make_sub_task(**overrides)]}

    def test_complete_passed_state_passes(self):  # testlint: allow — 斷言的是「不拋例外」
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

    def test_require_passed_false_skips_status_checks(self):  # testlint: allow — 斷言的是「不拋例外」
        eval_gates.validate_state(self.state(status="in_progress", local_test_passed=False), "test")

    # review_reds 相關
    def test_missing_review_reds_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(review_reds=None), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_bool_review_reds_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(review_reds=True), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_negative_review_reds_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(review_reds=-1), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # verify_passed 相關
    def test_verify_passed_false_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(verify_passed=False), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_verify_passed_missing_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(verify_passed=None), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # rounds ↔ review_reds 一致性
    def test_empty_rounds_nonzero_reds_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(rounds=[], review_reds=1), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_nonempty_rounds_zero_reds_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(review_reds=0), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # Floor 規則
    def test_final_round_zero_dimension_blocks(self):
        rounds_with_zero = [
            {
                "round": 1,
                "quality_score": 8,
                "deduction_reasons": [
                    {"points_lost": 1, "dimension": "A", "reason": "r", "evidence": "e"},
                    {"points_lost": 1, "dimension": "B", "reason": "r", "evidence": "e"},
                ],
                "dimensions": {"Correctness": 0, "Completeness": 3, "Clarity": 2, "Test_Quality": 2, "Maintainability": 1},
            }
        ]
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(rounds=rounds_with_zero, review_reds=2), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # 合法跳過路徑（rounds 空＋review_reds=0＋verify_passed=true）
    def test_legal_skip_path_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        eval_gates.validate_state(
            self.state(rounds=[], review_reds=0, verify_passed=True),
            "test",
            require_passed=True,
        )


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


class ManifestRegexTest(unittest.TestCase):
    def test_matches_plain_manifest(self):
        m = eval_gates.MANIFEST_RE.match("run/2026-07-15-foo.json")
        self.assertIsNotNone(m)
        self.assertEqual(m.group("run_id"), "2026-07-15-foo")

    def test_ignores_eval_archive(self):
        self.assertIsNone(eval_gates.MANIFEST_RE.match("run/2026-07-15-foo.eval.json"))

    def test_ignores_test_baseline(self):
        self.assertIsNone(
            eval_gates.MANIFEST_RE.match("run/2026-07-15-foo.test_baseline.json")
        )

    def test_ignores_nested_paths(self):
        self.assertIsNone(eval_gates.MANIFEST_RE.match("run/sub/foo.json"))


class TestFileDetectionTest(unittest.TestCase):
    def test_conventional_names(self):
        self.assertTrue(eval_gates.is_test_file("test_foo.py"))
        self.assertTrue(eval_gates.is_test_file("src/foo_test.py"))
        self.assertTrue(eval_gates.is_test_file("tests/helpers.py"))

    def test_non_test_files(self):
        self.assertFalse(eval_gates.is_test_file("src/foo.py"))
        self.assertFalse(eval_gates.is_test_file("tests/foo.js"))


class GateHitLogTest(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()
        eval_gates._hint_enabled = False

    def test_block_in_hook_mode_logs_hit_when_run_dir_exists(self):
        import os
        os.makedirs("run")
        eval_gates._hint_enabled = True
        with self.assertRaises(SystemExit):
            eval_gates.block("測試訊息：第一行\n第二行不記")
        with open("run/gate_hits.log", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("測試訊息：第一行", content)
        self.assertNotIn("第二行", content)

    def test_no_log_without_run_dir(self):
        import os
        eval_gates._hint_enabled = True
        with self.assertRaises(SystemExit):
            eval_gates.block("x")
        self.assertFalse(os.path.exists("run"))

    def test_validate_mode_does_not_log(self):
        import os
        os.makedirs("run")
        eval_gates._hint_enabled = False
        with self.assertRaises(SystemExit):
            eval_gates.block("x")
        self.assertFalse(os.path.exists("run/gate_hits.log"))


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


class EvalScorerGateTest(unittest.TestCase):
    """測試 check_task_gate() 對 eval-scorer 的 review_reds 前置檢查。"""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _write_state_and_manifest(self, review_reds):
        import json
        import os
        os.makedirs("run")
        manifest = {
            "run_id": "test-run",
            "spec_inline": "test spec",
            "status": "in_progress",
            "phase": "decomposed",
            "task_file": "task/2026-01-01.md",
        }
        with open("run/test-run.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        state = {
            "run_id": "test-run",
            "sub_tasks": [
                {
                    "id": 1,
                    "name": "demo",
                    "status": "in_progress",
                    "local_test_passed": True,
                    "local_test_evidence": "pytest ok",
                    "review_reds": review_reds,
                    "verify_passed": False,
                    "rounds": [],
                }
            ],
        }
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f)

    def test_review_reds_none_blocks(self):
        self._write_state_and_manifest(None)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "eval-scorer"})
        self.assertEqual(ctx.exception.code, 2)

    def test_review_reds_zero_blocks(self):
        self._write_state_and_manifest(0)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "eval-scorer"})
        self.assertEqual(ctx.exception.code, 2)

    def test_review_reds_one_passes(self):  # testlint: allow — 斷言的是「不拋例外（exit 0）」
        self._write_state_and_manifest(1)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "eval-scorer"})
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
