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
    }
    st.update(overrides)
    return st


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

    # 舊格式歸檔（含 rounds／任意品質欄位）通過 validate_state（寬容放行）
    def test_legacy_archive_with_rounds_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        st = make_sub_task(rounds=[
            {
                "round": 1,
                "quality_score": 8,
                "deduction_reasons": [
                    {"points_lost": 1, "dimension": "Completeness", "reason": "r", "evidence": "a.py:1"},
                    {"points_lost": 1, "dimension": "Clarity", "reason": "r", "evidence": "a.py:2"},
                ],
                "dimensions": {"Correctness": 2, "Completeness": 1, "Clarity": 1, "Test_Quality": 2, "Maintainability": 2},
            }
        ])
        eval_gates.validate_state({"run_id": "t", "sub_tasks": [st]}, "test", require_passed=True)

    # review_reds 缺失或非 int 仍擋
    def test_review_reds_absent_key_blocks(self):
        st = make_sub_task()
        del st["review_reds"]
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state({"run_id": "t", "sub_tasks": [st]}, "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # verify_passed 非 true 仍擋
    def test_verify_passed_false_key_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self.state(verify_passed=False), "test", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)


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

    # parent_run_id 相容：多帶此欄不影響 phase 推導
    def test_explicit_phase_unaffected_by_parent_run_id(self):
        without = eval_gates.manifest_phase({"phase": "risk_done"})
        with_parent = eval_gates.manifest_phase({"phase": "risk_done", "parent_run_id": "P"})
        self.assertEqual(without, with_parent)
        self.assertEqual(with_parent, "risk_done")

    def test_legacy_task_file_path_unaffected_by_parent_run_id(self):
        without = eval_gates.manifest_phase({"task_file": "task/x.md"})
        with_parent = eval_gates.manifest_phase({"task_file": "task/x.md", "parent_run_id": "P"})
        self.assertEqual(without, with_parent)
        self.assertEqual(with_parent, "decomposed")


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

    def test_matches_sub_manifest_with_item_suffix(self):
        m = eval_gates.MANIFEST_RE.match("run/2026-07-25-x-item-1.json")
        self.assertIsNotNone(m)
        self.assertEqual(m.group("run_id"), "2026-07-25-x-item-1")

    def test_ignores_sub_manifest_eval_archive(self):
        self.assertIsNone(eval_gates.MANIFEST_RE.match("run/2026-07-25-x-item-1.eval.json"))


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



class ImpactAnalyzerGateTest(unittest.TestCase):
    """測試 check_task_gate() 對 impact-analyzer 的 phase 前置檢查。"""

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

    def _write_state_and_manifest(self, phase):
        import json
        import os
        os.makedirs("run")
        manifest = {
            "run_id": "test-run",
            "spec_inline": "test spec",
            "status": "in_progress",
            "phase": phase,
        }
        with open("run/test-run.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        with open("eval_state.json", "w", encoding="utf-8") as f:
            json.dump({"run_id": "test-run", "sub_tasks": []}, f)

    def test_phase_below_usage_confirmed_blocks(self):
        self._write_state_and_manifest("risk_done")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "impact-analyzer"})
        self.assertEqual(ctx.exception.code, 2)

    def test_phase_usage_confirmed_passes(self):
        self._write_state_and_manifest("usage_confirmed")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "impact-analyzer"})
        self.assertEqual(ctx.exception.code, 0)


class ParentRunIdCompatTest(unittest.TestCase):
    """check_other_runs／check_manifest 對含 parent_run_id 欄位的 manifest 相容性迴歸測試。"""

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

    def test_check_other_runs_blocks_in_progress_with_parent_run_id(self):
        import json
        import os
        os.makedirs("run")
        other = {"run_id": "other-run", "status": "in_progress", "parent_run_id": "parent-x"}
        with open("run/other-run.json", "w", encoding="utf-8") as f:
            json.dump(other, f)
        with self.assertRaises(SystemExit):
            eval_gates.check_other_runs("current-run")

    def test_check_other_runs_allows_completed_with_parent_run_id(self):  # testlint: allow — 斷言的是「不拋例外」
        import json
        import os
        os.makedirs("run")
        other = {"run_id": "other-run", "status": "completed", "parent_run_id": "parent-x"}
        with open("run/other-run.json", "w", encoding="utf-8") as f:
            json.dump(other, f)
        eval_gates.check_other_runs("current-run")  # must not raise

    def test_check_manifest_requires_eval_archive_for_manifest_with_parent_run_id(self):
        import json
        import os
        os.makedirs("run")
        manifest = {
            "run_id": "test-run",
            "spec_inline": "test spec",
            "status": "completed",
            "parent_run_id": "parent-x",
        }
        with open("run/test-run.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        # archive not in staged → block（同無 parent_run_id 的 completed manifest 路徑）
        with self.assertRaises(SystemExit):
            eval_gates.check_manifest("run/test-run.json", set())


class Tier1ManifestCommitTest(unittest.TestCase):
    """DoD (c)：Tier 1 manifest commit gate 的三條路徑。"""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("run")

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _write_manifest(self, **extra):
        import json
        base = {
            "run_id": "t1-run",
            "tier": 1,
            "spec_inline": "test spec",
            "status": "completed",
            "local_test_passed": True,
            "local_test_evidence": "pytest -q -> 5 passed",
            "review_reds": 0,
            "verify_passed": True,
        }
        base.update(extra)
        with open("run/t1-run.json", "w", encoding="utf-8") as f:
            json.dump(base, f)

    # DoD (d) case 1：四欄齊全 → 放行
    def test_tier1_four_fields_complete_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        self._write_manifest()
        eval_gates.check_manifest("run/t1-run.json", set())

    # DoD (d) case 2：缺任一欄 → block（四欄各一 case）
    def test_tier1_missing_local_test_passed_blocks(self):
        self._write_manifest(local_test_passed=False)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest("run/t1-run.json", set())
        self.assertEqual(ctx.exception.code, 2)

    def test_tier1_empty_local_test_evidence_blocks(self):
        self._write_manifest(local_test_evidence="")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest("run/t1-run.json", set())
        self.assertEqual(ctx.exception.code, 2)

    def test_tier1_null_review_reds_blocks(self):
        self._write_manifest(review_reds=None)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest("run/t1-run.json", set())
        self.assertEqual(ctx.exception.code, 2)

    def test_tier1_missing_verify_passed_blocks(self):
        self._write_manifest(verify_passed=False)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest("run/t1-run.json", set())
        self.assertEqual(ctx.exception.code, 2)

    # DoD (d) case 3：有 staged 歸檔檔 → 走舊路徑（向後相容回歸）
    def test_tier1_with_staged_archive_uses_old_path(self):  # testlint: allow — 斷言的是「不拋例外」
        import json
        # manifest 四欄故意非法：走四欄驗證路徑 → block；走歸檔路徑 → pass
        # 藉此確認 archive_path in staged 判斷確實分流到正確路徑
        self._write_manifest(local_test_passed=False, review_reds=None)
        # 建立合法的 eval 歸檔檔（sub_tasks 全 passed）
        archive = {
            "run_id": "t1-run",
            "sub_tasks": [make_sub_task()],
        }
        with open("run/t1-run.eval.json", "w", encoding="utf-8") as f:
            json.dump(archive, f)
        staged = {"run/t1-run.json", "run/t1-run.eval.json"}
        # 應走歸檔路徑（validate_state），不拋例外
        eval_gates.check_manifest("run/t1-run.json", staged)

    # tier 字串 "1" 與整數 1 兩種都容許
    def test_tier1_string_tier_also_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        self._write_manifest(tier="1")
        eval_gates.check_manifest("run/t1-run.json", set())

    # Tier 2 不受豁免（現行行為不變）
    def test_tier2_without_archive_still_blocks(self):
        import json
        m = {
            "run_id": "t2-run",
            "tier": 2,
            "spec_inline": "spec",
            "status": "completed",
        }
        with open("run/t2-run.json", "w", encoding="utf-8") as f:
            json.dump(m, f)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest("run/t2-run.json", set())
        self.assertEqual(ctx.exception.code, 2)


class Tier1SubagentGateTest(unittest.TestCase):
    """DoD (a)(b)：check_task_gate 在無 eval_state.json 時的三條路徑。"""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("run")

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _write_manifest(self, run_id, tier=1, status="in_progress", phase="decomposed",
                        task_file="task/x.md", spec_inline="spec", **extra):
        import json
        m = {
            "run_id": run_id,
            "tier": tier,
            "status": status,
            "phase": phase,
            "spec_inline": spec_inline,
            "task_file": task_file,
        }
        m.update(extra)
        with open(f"run/{run_id}.json", "w", encoding="utf-8") as f:
            json.dump(m, f)

    # DoD (d) case 4：唯一 tier 1 in_progress manifest + decomposed → 放行
    def test_no_eval_state_unique_tier1_inprogress_passes(self):
        self._write_manifest("tier1-run")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 0)

    # DoD (d) case 5：無任何 tier 1 in_progress manifest → block
    def test_no_eval_state_no_tier1_manifest_blocks(self):
        # 只有 tier 2 manifest
        self._write_manifest("t2-run", tier=2)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 2)

    # DoD (d) case 5 變體：完全無 manifest
    def test_no_eval_state_no_manifest_at_all_blocks(self):
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 2)

    # DoD (d) case 6：有其他 in_progress manifest → check_other_runs 仍擋
    def test_no_eval_state_other_inprogress_manifest_blocks(self):
        import json
        self._write_manifest("tier1-run")
        # 另一個 in_progress manifest（tier 2）
        other = {"run_id": "other-run", "tier": 2, "status": "in_progress", "spec_inline": "s"}
        with open("run/other-run.json", "w", encoding="utf-8") as f:
            json.dump(other, f)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 2)

    # phase 未達 decomposed → block
    def test_no_eval_state_phase_below_decomposed_blocks(self):
        self._write_manifest("tier1-run", phase="init")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 2)

    # 兩個以上 tier 1 in_progress manifest → block（邊界）
    def test_no_eval_state_multiple_tier1_manifests_blocks(self):
        self._write_manifest("tier1-run-a")
        self._write_manifest("tier1-run-b")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
