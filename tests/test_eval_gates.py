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


class RunHookWorktreeRootTest(unittest.TestCase):
    """end-to-end 測試：run_hook() root 解析在 git worktree 下的正確性。

    以 subprocess 跑 eval_gates.py --hook，每個案例都建真實 git worktree，
    斷言 returncode（exit 0 放行 / exit 2 攔截）反映了對正確工作區的判定。
    安全慣例：所有操作在 TemporaryDirectory 拋棄式 git repo 內，絕不觸碰真實 run/。
    """

    def setUp(self):
        import json
        import os
        import subprocess
        import tempfile
        self.old_cwd = os.getcwd()
        self.tmp_base = tempfile.TemporaryDirectory()
        base = self.tmp_base.name
        self.main = os.path.join(base, "main")
        os.makedirs(self.main)

        # 初始化拋棄式 main git repo
        subprocess.run(["git", "init", self.main], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "config", "user.email", "t@t.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "config", "user.name", "T"],
                       check=True, capture_output=True)
        # worktree add 需要至少一個 commit
        open(os.path.join(self.main, ".gitkeep"), "w").close()
        subprocess.run(["git", "-C", self.main, "add", ".gitkeep"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "commit", "-m", "init"],
                       check=True, capture_output=True)

        # 建立 worktree（path 不可預先存在）
        self.worktree = os.path.join(base, "worktree")
        subprocess.run(
            ["git", "-C", self.main, "worktree", "add", "--detach", self.worktree],
            check=True, capture_output=True,
        )
        self.eval_gates_py = str(
            Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_gates.py"
        )

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp_base.cleanup()

    def _run_hook(self, payload, cpd):
        """以 subprocess 跑 eval_gates.py --hook，回傳 returncode。"""
        import json
        import os
        import subprocess
        env = {**os.environ, "CLAUDE_PROJECT_DIR": cpd}
        result = subprocess.run(
            [sys.executable, self.eval_gates_py, "--hook"],
            input=json.dumps(payload),
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode

    def test_g_commit_gate_reads_worktree_eval_state(self):
        """[核心/G] worktree 有 eval_state.json、主 repo 無 → exit 2（命中歸檔 gate）。
        修正前：chdir 到主 repo（無 eval_state.json）→ exit 0（此即 RED 錨點）。"""
        import json
        import os
        with open(os.path.join(self.worktree, "eval_state.json"), "w") as f:
            json.dump({"run_id": "wt-run"}, f)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": self.worktree,
        }
        rc = self._run_hook(payload, self.main)
        # 命中 worktree eval_state.json → block → exit 2
        self.assertEqual(rc, 2)

    def test_f_subagent_gate_reads_worktree_state(self):
        """[核心/F] worktree 備妥合法 tier2 state+manifest → check_task_gate 讀 worktree → exit 0。
        修正前：chdir 到主 repo（無 eval_state.json 且無 tier1 manifest）→ exit 2（誤判）。"""
        import json
        import os
        wt_run_dir = os.path.join(self.worktree, "run")
        os.makedirs(wt_run_dir)
        state = {"run_id": "wt-run", "sub_tasks": []}
        with open(os.path.join(self.worktree, "eval_state.json"), "w") as f:
            json.dump(state, f)
        manifest = {
            "run_id": "wt-run",
            "tier": 2,
            "status": "in_progress",
            "phase": "decomposed",
            "spec_inline": "spec",
            "task_file": "task/x.md",
        }
        with open(os.path.join(wt_run_dir, "wt-run.json"), "w") as f:
            json.dump(manifest, f)
        payload = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "code-writer"},
            "cwd": self.worktree,
        }
        rc = self._run_hook(payload, self.main)
        # chdir 到 worktree → 讀正確 state → phase=decomposed 放行 → exit 0
        self.assertEqual(rc, 0)

    def test_a_h_same_dir_short_circuit(self):
        """[核心/A,H] CPD==cwd 字串相等 → 短路回 CPD，行為與修正前逐位元同。
        主 repo 有 eval_state.json → exit 2；worktree 無 → exit 0（差別行為驗短路）。"""
        import json
        import os
        with open(os.path.join(self.main, "eval_state.json"), "w") as f:
            json.dump({"run_id": "main-run"}, f)
        # worktree 無 eval_state.json
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": self.main,  # == CPD
        }
        rc = self._run_hook(payload, self.main)
        # 短路到主 repo → 命中 eval_state.json → exit 2
        self.assertEqual(rc, 2)

    def test_e_no_cwd_key_uses_cpd(self):
        """[邊界/E] payload 無 cwd 鍵 → 嚴格回 CPD（主 repo），不拋例外。
        主 repo 有 eval_state.json → exit 2 證明確實讀了主 repo。"""
        import json
        import os
        with open(os.path.join(self.main, "eval_state.json"), "w") as f:
            json.dump({"run_id": "main-run"}, f)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            # 故意不帶 cwd 鍵
        }
        rc = self._run_hook(payload, self.main)
        # 嚴格回 CPD（主 repo）→ 命中 eval_state.json → exit 2
        self.assertEqual(rc, 2)

    def test_c_subdir_cpd_regression(self):
        """[邊界/C] CPD 為子目錄、cwd 為同 repo 他處 → git toplevel 相等 → 回 CPD（子目錄）。
        eval_state.json 放在子目錄（CPD），exit 2 證明 chdir 到子目錄而非 git 根。"""
        import json
        import os
        subdir = os.path.join(self.main, "subproject")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "eval_state.json"), "w") as f:
            json.dump({"run_id": "sub-run"}, f)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": self.main,  # 同 repo 他處（git root）
        }
        # CPD = subdir（子目錄），cwd = main（git root）；两者 git toplevel 相等
        rc = self._run_hook(payload, subdir)
        # toplevel 相等 → 回 CPD(=subdir) → 命中 eval_state.json → exit 2
        self.assertEqual(rc, 2)

    def test_d_non_git_cwd_falls_back_to_cpd(self):
        """[邊界/D] cwd 為非 git 目錄 → _git_toplevel 失敗 → 回 CPD，不拋例外。
        主 repo 有 eval_state.json → exit 2 證明確實回落到 CPD（主 repo）。"""
        import json
        import os
        import tempfile
        with open(os.path.join(self.main, "eval_state.json"), "w") as f:
            json.dump({"run_id": "main-run"}, f)
        with tempfile.TemporaryDirectory() as non_git_dir:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m x"},
                "cwd": non_git_dir,
            }
            rc = self._run_hook(payload, self.main)
        # _git_toplevel(non_git_dir) 失敗 → 回 CPD → exit 2
        self.assertEqual(rc, 2)

    def test_b_edge1_worktree_subdir_chdir_to_root(self):
        """[邊界/B-edge1] cwd 為 worktree 子目錄 → git rev-parse 回 worktree 根 → chdir 到根。
        eval_state.json 在 worktree 根（非子目錄），exit 2 證明 chdir 目標是根而非子目錄。"""
        import json
        import os
        subdir = os.path.join(self.worktree, "src")
        os.makedirs(subdir)
        # eval_state.json 在 worktree 根（不在 subdir）
        with open(os.path.join(self.worktree, "eval_state.json"), "w") as f:
            json.dump({"run_id": "wt-run"}, f)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": subdir,  # worktree 子目錄
        }
        rc = self._run_hook(payload, self.main)
        # git rev-parse(subdir) → worktree 根 → chdir 到根 → 命中 eval_state.json → exit 2
        self.assertEqual(rc, 2)


class AbortedConsumptionTest(unittest.TestCase):
    """1a 契約：aborted／failed 皆為「非 in_progress」，四消費點中可離開 git 直接單元測的兩點。
    （另兩點 stats.py Counter、eval-flow-resume SKILL.md 文件面分別見 test_stats.py 與人工核對。）"""

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

    def _write(self, name, obj):
        import json
        with open(f"run/{name}", "w", encoding="utf-8") as f:
            json.dump(obj, f)

    # check_other_runs：aborted 不擋新 run
    def test_check_other_runs_ignores_aborted(self):  # testlint: allow — 斷言的是「不拋例外」
        self._write("other.json", {"run_id": "other", "status": "aborted"})
        eval_gates.check_other_runs("current")  # must not raise

    # 邊界：failed 與 aborted 同待遇
    def test_check_other_runs_ignores_failed(self):  # testlint: allow — 斷言的是「不拋例外」
        self._write("other.json", {"run_id": "other", "status": "failed"})
        eval_gates.check_other_runs("current")  # must not raise

    # check_other_runs 仍正確擋 in_progress（回歸，防止改壞判定式）
    def test_check_other_runs_still_blocks_in_progress(self):
        self._write("other.json", {"run_id": "other", "status": "in_progress"})
        with self.assertRaises(SystemExit):
            eval_gates.check_other_runs("current")

    # _find_unique_tier1_inprogress：只有 aborted 的 tier1 manifest → 找不到（回 None）
    def test_find_unique_tier1_ignores_aborted(self):
        self._write("a.json", {"run_id": "a", "tier": 1, "status": "aborted"})
        self.assertIsNone(eval_gates._find_unique_tier1_inprogress())

    # 邊界：只有 failed 的 tier1 manifest → 同樣找不到
    def test_find_unique_tier1_ignores_failed(self):
        self._write("a.json", {"run_id": "a", "tier": 1, "status": "failed"})
        self.assertIsNone(eval_gates._find_unique_tier1_inprogress())

    # aborted 與真正 in_progress 的 tier1 manifest 共存 → 仍能唯一定位到 in_progress 那個
    def test_find_unique_tier1_finds_inprogress_alongside_aborted(self):
        self._write("aborted-run.json", {"run_id": "aborted-run", "tier": 1, "status": "aborted"})
        self._write("live-run.json", {"run_id": "live-run", "tier": 1, "status": "in_progress"})
        found = eval_gates._find_unique_tier1_inprogress()
        self.assertIsNotNone(found)
        self.assertEqual(found[1]["run_id"], "live-run")


class ManifestDeletionGateTest(unittest.TestCase):
    """1b 契約：check_manifest_deletion 正反向測試（真實 git repo，覆蓋正常/含空白/含特殊字元/
    rename 邊界，依規則消費 git 輸出前查規格選 -z + NUL split 的安全解析）。"""

    def setUp(self):
        import os
        import subprocess
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        subprocess.run(["git", "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True)

    def tearDown(self):
        import os
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _commit_file(self, path, content):
        import os
        import subprocess
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        subprocess.run(["git", "add", path], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], check=True, capture_output=True)

    # 正常路徑：刪除 manifest → block
    def test_deleting_manifest_blocks(self):
        import subprocess
        self._commit_file("run/2026-08-20-x.json", '{"run_id": "x"}')
        subprocess.run(["git", "rm", "-q", "run/2026-08-20-x.json"], check=True, capture_output=True)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest_deletion()
        self.assertEqual(ctx.exception.code, 2)

    # 含空白路徑
    def test_deleting_manifest_with_space_blocks(self):
        import subprocess
        path = "run/2026-08-20 with space.json"
        self._commit_file(path, '{"run_id": "x"}')
        subprocess.run(["git", "rm", "-q", path], check=True, capture_output=True)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest_deletion()
        self.assertEqual(ctx.exception.code, 2)

    # 含特殊字元路徑
    def test_deleting_manifest_with_special_chars_blocks(self):
        import subprocess
        path = "run/2026-08-20-a&b-特殊.json"
        self._commit_file(path, '{"run_id": "x"}')
        subprocess.run(["git", "rm", "-q", path], check=True, capture_output=True)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest_deletion()
        self.assertEqual(ctx.exception.code, 2)

    # rename 邊界：manifest 改名等同讓原路徑消失，須視同刪除（--no-renames 使其被拆解為刪＋加）
    def test_renaming_manifest_blocks(self):
        import subprocess
        self._commit_file("run/2026-08-20-old.json", '{"run_id": "old"}')
        subprocess.run(
            ["git", "mv", "run/2026-08-20-old.json", "run/2026-08-20-new.json"],
            check=True, capture_output=True,
        )
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest_deletion()
        self.assertEqual(ctx.exception.code, 2)

    # 歸檔檔刪除 → 放行（B-edge1）
    def test_deleting_eval_archive_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        import subprocess
        self._commit_file("run/2026-08-20-x.eval.json", '{"run_id": "x"}')
        subprocess.run(["git", "rm", "-q", "run/2026-08-20-x.eval.json"], check=True, capture_output=True)
        eval_gates.check_manifest_deletion()  # must not raise

    # baseline 檔刪除 → 放行（B-edge1）
    def test_deleting_test_baseline_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        import subprocess
        self._commit_file("run/2026-08-20-x.test_baseline.json", '{"run_id": "x"}')
        subprocess.run(["git", "rm", "-q", "run/2026-08-20-x.test_baseline.json"], check=True, capture_output=True)
        eval_gates.check_manifest_deletion()  # must not raise

    # 邊界：manifest 被修改（非刪除）→ 本 gate 不觸發
    def test_modifying_manifest_not_deleting_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        import subprocess
        self._commit_file("run/2026-08-20-x.json", '{"run_id": "x", "status": "in_progress"}')
        with open("run/2026-08-20-x.json", "w", encoding="utf-8") as f:
            f.write('{"run_id": "x", "status": "completed"}')
        subprocess.run(["git", "add", "run/2026-08-20-x.json"], check=True, capture_output=True)
        eval_gates.check_manifest_deletion()  # must not raise

    # 刪除非 manifest 的一般檔案 → 放行
    def test_deleting_non_manifest_file_passes(self):  # testlint: allow — 斷言的是「不拋例外」
        import subprocess
        self._commit_file("README_temp.md", "hello")
        subprocess.run(["git", "rm", "-q", "README_temp.md"], check=True, capture_output=True)
        eval_gates.check_manifest_deletion()  # must not raise

    # 回歸（2026-08-20 code-review 🔴）：`git rm --cached` 只移除索引、保留工作區檔案——
    # 判定必須看 git 索引狀態（--diff-filter=D），不能被「檔案仍在磁碟上」誤導成未刪除
    def test_git_rm_cached_manifest_still_blocks_even_if_worktree_file_kept(self):
        import os
        import subprocess
        self._commit_file("run/2026-08-20-x.json", '{"run_id": "x", "status": "aborted", "failed_reason": "放棄"}')
        subprocess.run(["git", "rm", "-q", "--cached", "run/2026-08-20-x.json"],
                        check=True, capture_output=True)
        # 工作區檔案仍存在（--cached 只動索引）
        self.assertTrue(os.path.exists("run/2026-08-20-x.json"))
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_manifest_deletion()
        self.assertEqual(ctx.exception.code, 2)


class NarrowExceptionGateTest(unittest.TestCase):
    """1d 契約：check_abort_failed_narrow_exception 正反向測試（純函式，僅需檔案存在，不需 git）。"""

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

    def _write(self, name, obj):
        import json
        with open(f"run/{name}", "w", encoding="utf-8") as f:
            json.dump(obj, f)

    # 恰一 manifest＋status=aborted＋failed_reason 非空 → True
    def test_aborted_with_reason_true(self):
        self._write("x.json", {"run_id": "x", "status": "aborted", "failed_reason": "使用者放棄"})
        self.assertTrue(eval_gates.check_abort_failed_narrow_exception({"run/x.json"}))

    # 恰一 manifest＋status=failed＋failed_reason 非空 → True
    def test_failed_with_reason_true(self):
        self._write("x.json", {"run_id": "x", "status": "failed", "failed_reason": "卡在 step 3"})
        self.assertTrue(eval_gates.check_abort_failed_narrow_exception({"run/x.json"}))

    # 混入其他檔 → False（落回原判定）
    def test_mixed_other_file_false(self):
        self._write("x.json", {"run_id": "x", "status": "aborted", "failed_reason": "放棄"})
        staged = {"run/x.json", "README.md"}
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception(staged))

    # status=completed → False（非窄例外，走原路）
    def test_status_completed_false(self):
        self._write("x.json", {"run_id": "x", "status": "completed"})
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception({"run/x.json"}))

    # 邊界：failed_reason 為空字串 → False（1a「必填」機械強制點）
    def test_empty_failed_reason_false(self):
        self._write("x.json", {"run_id": "x", "status": "aborted", "failed_reason": ""})
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception({"run/x.json"}))

    # failed_reason 為 None → False
    def test_none_failed_reason_false(self):
        self._write("x.json", {"run_id": "x", "status": "aborted", "failed_reason": None})
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception({"run/x.json"}))

    # 恰一檔但非 manifest（如歸檔檔）→ False
    def test_non_manifest_single_file_false(self):
        self._write("x.eval.json", {"run_id": "x", "status": "aborted", "failed_reason": "放棄"})
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception({"run/x.eval.json"}))

    # staged 空集合 → False
    def test_empty_staged_false(self):
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception(set()))

    # manifest 不存在（如被刪除）→ False（落回防刪除 gate 判定，不誤放行）
    def test_manifest_file_missing_false(self):
        self.assertFalse(eval_gates.check_abort_failed_narrow_exception({"run/missing.json"}))


class IntegrationHookGatesTest(unittest.TestCase):
    """1.4 整合測試：subprocess 跑真實 `eval_gates.py --hook`（仿 RunHookWorktreeRootTest 樣板），
    涵蓋情境 B／N／N-err1，並驗防刪除 gate 與窄例外 gate 共存不誤動既有正常收尾判定。"""

    def setUp(self):
        import os
        import subprocess
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "t@t.com"],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.name", "T"],
                        check=True, capture_output=True)
        os.makedirs(os.path.join(self.repo, "run"))
        self.eval_gates_py = str(
            Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_gates.py"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        import subprocess
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True)

    def _write(self, rel_path, obj):
        import json
        import os
        path = os.path.join(self.repo, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def _run_hook(self):
        import json
        import os
        import subprocess
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "cwd": self.repo,
        }
        env = {**os.environ, "CLAUDE_PROJECT_DIR": self.repo}
        return subprocess.run(
            [sys.executable, self.eval_gates_py, "--hook"],
            input=json.dumps(payload),
            env=env,
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    # 情境 B：staged 含 manifest 刪除 → block（exit 2）
    def test_scenario_b_deleting_staged_manifest_blocks(self):
        self._write("run/2026-08-20-b.json", {"run_id": "b", "status": "completed"})
        self._git("add", "run/2026-08-20-b.json")
        self._git("commit", "-q", "-m", "init")
        self._git("rm", "-q", "run/2026-08-20-b.json")
        result = self._run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn("被刪除", result.stderr)

    # 情境 N：窄例外三條件全滿足 → 放行（exit 0），即使 eval_state.json 仍存在也被豁免
    def test_scenario_n_narrow_exception_passes_with_eval_state_present(self):
        import json
        import os
        self._write("run/2026-08-20-n.json", {
            "run_id": "n", "status": "aborted", "failed_reason": "使用者決定不做了",
        })
        self._git("add", "run/2026-08-20-n.json")
        with open(os.path.join(self.repo, "eval_state.json"), "w", encoding="utf-8") as f:
            json.dump({"run_id": "n"}, f)
        result = self._run_hook()
        self.assertEqual(result.returncode, 0)

    # 情境 N-err1：混入其他檔 → 落回原判定（block）
    def test_scenario_n_err1_mixed_files_blocks(self):
        self._write("run/2026-08-20-n2.json", {
            "run_id": "n2", "status": "aborted", "failed_reason": "放棄",
        })
        self._write("README_temp.md", "hello")  # 內容不必是合法 JSON，_write 只是共用的寫檔 helper
        self._git("add", "run/2026-08-20-n2.json", "README_temp.md")
        result = self._run_hook()
        self.assertEqual(result.returncode, 2)

    # 共存驗證：正常完成的 Tier 1 manifest commit（既有判定）不被新 gate 誤攔
    def test_normal_tier1_completed_commit_not_blocked_by_new_gates(self):
        self._write("run/2026-08-20-t1.json", {
            "run_id": "t1", "tier": 1, "status": "completed", "spec_inline": "s",
            "local_test_passed": True, "local_test_evidence": "pytest -> 1 passed",
            "review_reds": 0, "verify_passed": True,
        })
        self._git("add", "run/2026-08-20-t1.json")
        result = self._run_hook()
        self.assertEqual(result.returncode, 0)

    # 回歸（2026-08-20 code-review 🔴）：`git rm --cached` 保留工作區檔案內容為
    # status=aborted＋failed_reason 非空（窄例外三條件全中的內容）。修正前：1d 窄例外
    # 先於 1b 防刪除 gate 判定，load_json_quiet 讀到工作區殘留內容誤判「非刪除」而放行
    # （exit 0）；修正後：防刪除 gate 先看 git 索引狀態，仍須 block（exit 2）。
    def test_git_rm_cached_aborted_manifest_still_blocked_end_to_end(self):
        import os
        self._write("run/2026-08-20-rc.json", {
            "run_id": "rc", "status": "aborted", "failed_reason": "使用者決定不做了",
        })
        self._git("add", "run/2026-08-20-rc.json")
        self._git("commit", "-q", "-m", "init")
        self._git("rm", "-q", "--cached", "run/2026-08-20-rc.json")
        # 工作區檔案仍在，且內容仍是窄例外三條件全中的內容
        self.assertTrue(os.path.exists(os.path.join(self.repo, "run/2026-08-20-rc.json")))
        result = self._run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn("被刪除", result.stderr)

class ColdFileLocationGateTest(unittest.TestCase):
    """commit gate 以工作目錄定位 manifest 的契約（task/2026-09-22.md item 1.1 契約表 C1–C12）。

    冷溯源檔不再進版控後，gate 不可再以「staged 中有 manifest」為啟動條件。本類逐 row
    驗證新定位路徑：commit message 的 `Run-Id:` trailer ∪ staged，兩者皆落空時以工作目錄
    的 `status: in_progress` 當安全網。

    全部案例走 **真實端到端路徑**：真 git repo ＋ subprocess 跑 `eval_gates.py --hook`
    ＋ 真 stdin payload，不以直接 import 內部函式繞過（R-005：以直接呼叫內部函式繞過
    跨進程執行契約的單元測試，不構成驗收證據）。
    """

    # hook 收到的是 Bash 指令原文；此處以拼接組出 `git commit`，避免本檔自身的文字
    # 在被 Bash 工具讀寫時命中 PreToolUse 的 GIT_COMMIT_RE（實測會攔下編輯指令本身）。
    GIT_COMMIT = "git " + "commit"

    def setUp(self):
        import os
        import subprocess
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.eval_gates_py = str(
            Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_gates.py"
        )
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        for k, v in (("user.email", "t@t.com"), ("user.name", "T")):
            subprocess.run(["git", "-C", self.repo, "config", k, v],
                           check=True, capture_output=True)
        os.makedirs(os.path.join(self.repo, "run"))
        # 先做一個 initial commit，讓 `git diff --cached` 有 HEAD 可比
        self._write_text("seed.txt", "seed\n")
        self._git("add", "seed.txt")
        self._git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    # --- fixture helpers ---

    def _git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", self.repo, *args],
                              check=True, capture_output=True, text=True)

    def _write_text(self, rel, text):
        import os
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path) or self.repo, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _write_json(self, rel, obj):
        import json
        return self._write_text(rel, json.dumps(obj, ensure_ascii=False))

    def _manifest(self, run_id, **overrides):
        """寫出一份 Tier 1 完整憑據齊備的 manifest，overrides 覆寫個別欄位。"""
        m = {
            "run_id": run_id,
            "tier": 1,
            "spec_inline": "demo",
            "status": "completed",
            "local_test_passed": True,
            "local_test_evidence": "unittest -> 3 passed",
            "review_reds": 0,
            "verify_passed": True,
        }
        m.update(overrides)
        self._write_json(f"run/{run_id}.json", m)
        return m

    def _stage_code(self):
        """staged 一個與溯源無關的程式碼檔，模擬正常收尾 commit 的 staging 內容。"""
        self._write_text("app.py", "x = 1\n")
        self._git("add", "app.py")

    def _run_hook(self, command, cwd=None, project_dir=None):
        """以 subprocess 跑 eval_gates.py --hook，回傳 CompletedProcess。"""
        import json
        import os
        import subprocess
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        if cwd is not None:
            payload["cwd"] = cwd
        env = {**os.environ, "CLAUDE_PROJECT_DIR": project_dir or self.repo}
        return subprocess.run(
            [sys.executable, self.eval_gates_py, "--hook"],
            input=json.dumps(payload), env=env, capture_output=True, text=True,
        )

    def _commit_cmd(self, run_id=None):
        """組出 commit 指令原文；run_id 非 None 時附 `Run-Id:` trailer（含收尾引號，
        與實際指令形狀一致——trailer 解析必須耐受行尾殘留的 shell 語法）。"""
        if run_id is None:
            return f'{self.GIT_COMMIT} -m "ADD: demo"'
        return f'{self.GIT_COMMIT} -m "ADD: demo\n\nRun-Id: {run_id}"'

    # --- C1 ---
    def test_c1_trailer_locates_completed_manifest_passes(self):
        """C1：trailer 指向的 manifest 存在、completed、四欄憑據齊（未 staged）→ 放行。"""
        self._manifest("2026-09-22-c1")
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c1"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c1_manifest_is_not_staged(self):
        """C1 的前提坐實：manifest 確實不在 staged 清單內（否則測的是舊路徑）。"""
        self._manifest("2026-09-22-c1b")
        self._stage_code()
        out = self._git("diff", "--cached", "--name-only").stdout
        self.assertNotIn("run/2026-09-22-c1b.json", out)
        self.assertIn("app.py", out)

    # --- C2 ---
    def test_c2_trailer_locates_inprogress_manifest_blocks(self):
        """C2：trailer 指向的 manifest 未 staged 且仍 in_progress → block。"""
        self._manifest("2026-09-22-c2", status="in_progress")
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c2"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("status 非 completed", result.stderr)

    # --- C3 ---
    def test_c3_trailer_located_manifest_missing_credential_blocks(self):
        """C3：trailer 定位到的 Tier 1 manifest 憑據不齊 → block，訊息指名缺的欄位。"""
        self._manifest("2026-09-22-c3", local_test_passed=None)
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c3"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("local_test_passed", result.stderr)

    def test_c3_empty_evidence_blocks(self):
        """C3 補強：`local_test_evidence` 空字串同樣 block（憑據不可只填旗標）。"""
        self._manifest("2026-09-22-c3b", local_test_evidence="   ")
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c3b"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("local_test_evidence", result.stderr)

    # --- C4 ---
    def test_c4_trailer_pointing_at_missing_manifest_does_not_block(self):
        """C4：trailer 指向不存在的 manifest → 不因 trailer 而 block（落回安全網判定）。"""
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-nonexistent"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c4_trailer_path_traversal_is_rejected(self):
        """C4 邊界：trailer 內容含路徑逃逸樣式時不得解析出 run/ 以外的路徑。"""
        self._stage_code()
        result = self._run_hook(
            f'{self.GIT_COMMIT} -m "x\n\nRun-Id: ../../etc/passwd"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- C5 ---
    def test_c5_inprogress_manifest_on_disk_blocks_without_trailer(self):
        """C5（本次改造的核心 RED 錨點）：無 trailer、manifest 未 staged，但工作目錄有
        in_progress 的 run → block。改造前此情境 exit 0 且無任何訊息（靜默放行）。"""
        self._manifest("2026-09-22-c5", status="in_progress")
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("run/2026-09-22-c5.json", result.stderr)
        self.assertIn("in_progress", result.stderr)

    def test_c5_remedy_names_aborted_path(self):
        """C5 訊息可操作性：補救指示須點出 aborted 留痕路徑，而非叫人刪檔。"""
        self._manifest("2026-09-22-c5c", status="in_progress")
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertIn("aborted", result.stderr)
        self.assertIn("failed_reason", result.stderr)

    # --- C6 ---
    def test_c6_no_trailer_no_manifest_passes(self):
        """C6：無 trailer、無 staged manifest、工作目錄無 in_progress run → 放行。"""
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c6_completed_manifest_on_disk_does_not_block(self):
        """C6 邊界：工作目錄只有已收尾（completed）的舊 run → 安全網不得誤攔。"""
        self._manifest("2026-09-22-c6old")
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c6_aborted_manifest_on_disk_does_not_block(self):
        """C6 邊界：aborted 的 run 不算佔用，安全網不得誤攔。"""
        self._manifest("2026-09-22-c6ab", status="aborted", failed_reason="放棄")
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- C7 ---
    def test_c7_staged_manifest_legacy_path_passes(self):
        """C7：manifest 被 staged（舊專案仍把 run/ 納入版控）→ 行為與改造前一致（放行）。"""
        self._manifest("2026-09-22-c7")
        self._stage_code()
        self._git("add", "run/2026-09-22-c7.json")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c7_staged_inprogress_manifest_still_blocks(self):
        """C7 反向：staged 的 manifest 仍 in_progress → 照舊 block（舊路徑不得被放寬）。"""
        self._manifest("2026-09-22-c7b", status="in_progress")
        self._git("add", "run/2026-09-22-c7b.json")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("status 非 completed", result.stderr)

    def test_c7_staged_manifest_missing_intent_blocks(self):
        """C7 反向：staged manifest 的 spec_path／spec_inline 皆空 → intent gate 照舊攔。"""
        self._manifest("2026-09-22-c7c", spec_inline=None)
        self._git("add", "run/2026-09-22-c7c.json")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("intent gate", result.stderr)

    # --- C8 ---
    def test_c8_tier2_archive_on_disk_not_staged_passes(self):
        """C8：Tier 2 經 trailer 定位，歸檔檔存在於工作目錄但未 staged → 放行。
        改造前此情境會 block（歸檔判定只認 staged 成員資格）。"""
        self._manifest("2026-09-22-c8", tier=2)
        self._write_json("run/2026-09-22-c8.eval.json", {
            "run_id": "2026-09-22-c8",
            "sub_tasks": [{
                "id": 1, "name": "s1", "status": "passed",
                "local_test_passed": True, "local_test_evidence": "ok",
                "review_reds": 0, "verify_passed": True,
            }],
        })
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c8"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c8_tier2_missing_archive_blocks(self):
        """C8 反向：Tier 2 定位到但歸檔檔不存在 → block，訊息不得再要求 git add。"""
        self._manifest("2026-09-22-c8b", tier=2)
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c8b"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("run/2026-09-22-c8b.eval.json", result.stderr)
        self.assertNotIn("git add run/2026-09-22-c8b.eval.json", result.stderr)

    def test_c8_tier2_archive_run_id_mismatch_blocks(self):
        """C8 不變量：歸檔檔 run_id 與 manifest 不符 → 照舊 block。"""
        self._manifest("2026-09-22-c8c", tier=2)
        self._write_json("run/2026-09-22-c8c.eval.json",
                         {"run_id": "someone-else", "sub_tasks": []})
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-c8c"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("不一致", result.stderr)

    # --- C9 ---
    def test_c9_test_lint_runs_when_located_via_trailer(self):
        """C9：僅靠 trailer 定位到 manifest 時，假測試 lint 仍須啟動。
        改造前 lint 掛在「staged 有 manifest」，manifest 不進版控後會整條失效。"""
        self._manifest("2026-09-22-c9")
        self._write_text("tests/test_fake.py",
                         "def test_nothing():\n    assert True\n")
        self._git("add", "tests/test_fake.py")
        result = self._run_hook(self._commit_cmd("2026-09-22-c9"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("假測試 lint", result.stderr)

    def test_c9_test_lint_not_run_without_any_manifest(self):
        """C9 邊界：完全沒有 run 在進行時（非 flow commit），lint 不介入。"""
        self._write_text("tests/test_fake.py",
                         "def test_nothing():\n    assert True\n")
        self._git("add", "tests/test_fake.py")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- C10（R-008 要求的組合測試：放行型 vs 攔截型的相互遮蔽）---
    def test_c10_narrow_exception_wins_over_inprogress_safety_net(self):
        """C10：staged 恰一個 aborted manifest（窄例外三條件全中），同時工作目錄另有一個
        in_progress 的 run → 維持放行。

        這是刻意的排序決定：窄例外的成立條件是「staged 只有一個 manifest、不含任何 code」，
        該 commit 純為留痕放棄的 run，不該被另一個未收尾的 run 卡死。兩者的 status 條件
        （aborted／failed vs in_progress）互斥，不存在攔截型被永久遮蔽的情境。
        """
        self._manifest("2026-09-22-c10busy", status="in_progress")
        self._manifest("2026-09-22-c10", status="aborted", failed_reason="使用者決定不做了")
        self._git("add", "run/2026-09-22-c10.json")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_c10_narrow_exception_requires_sole_staged_file(self):
        """C10 邊界：窄例外一旦多 staged 一個 code 檔即不成立，該 commit 照常受 gate 管轄。

        此時 staged 內已有 manifest，故走的是既有 staged 路徑（`check_manifest` 以
        `status 非 completed` 攔下 aborted 那份），安全網不會執行——安全網只在「一個
        manifest 都定位不到」時才是兜底。斷言鎖定「窄例外沒有生效」這件事本身。
        """
        self._manifest("2026-09-22-c10busy2", status="in_progress")
        self._manifest("2026-09-22-c10b", status="aborted", failed_reason="放棄")
        self._git("add", "run/2026-09-22-c10b.json")
        self._stage_code()
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("run/2026-09-22-c10b.json", result.stderr)
        self.assertIn("status 非 completed", result.stderr)

    # --- C11 ---
    def test_c11_manifest_deletion_still_blocks(self):
        """C11：1b 防刪除 gate 不受本次改造影響，且仍排在所有放行型判定之前。"""
        self._manifest("2026-09-22-c11")
        self._git("add", "run/2026-09-22-c11.json")
        self._git("commit", "-q", "-m", "keep")
        self._git("rm", "-q", "run/2026-09-22-c11.json")
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("被刪除", result.stderr)

    # --- C12 ---
    def test_c12_non_git_repo_fails_open(self):
        """C12：非 git repo → fail-open（exit 0），安全網不得把 gate 變成硬失敗。"""
        import tempfile
        with tempfile.TemporaryDirectory() as plain:
            result = self._run_hook(self._commit_cmd(), project_dir=plain)
            self.assertEqual(result.returncode, 0, result.stderr)

    # --- 既有不變量：eval_state.json 仍優先攔截 ---
    def test_eval_state_still_blocks_before_locator(self):
        """不變量：`eval_state.json` 存在時仍先 block，定位路徑不得把它繞過。"""
        self._write_json("eval_state.json", {"run_id": "x", "sub_tasks": []})
        self._manifest("2026-09-22-es")
        self._stage_code()
        result = self._run_hook(self._commit_cmd("2026-09-22-es"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("eval_state.json", result.stderr)


class RunIdTrailerRegexTest(unittest.TestCase):
    """`RUN_ID_TRAILER_RE` 的解析邊界：對象是 Bash 指令原文，行尾可能殘留 shell 語法。"""

    def parse(self, command):
        m = eval_gates.RUN_ID_TRAILER_RE.search(command)
        return m.group(1) if m else None

    def test_trailing_quote_is_not_captured(self):
        """`-m "…"` 的收尾引號不得被捲進 run_id（捲進去會靜默退化成定位不到）。"""
        self.assertEqual(self.parse('x -m "m\n\nRun-Id: 2026-09-22-a"'), "2026-09-22-a")

    def test_heredoc_terminator_line_does_not_break_parse(self):
        self.assertEqual(self.parse("m\n\nRun-Id: 2026-09-22-b\nEOF\n)\""), "2026-09-22-b")

    def test_leading_and_trailing_whitespace_tolerated(self):
        self.assertEqual(self.parse("  Run-Id:\t2026-09-22-c  "), "2026-09-22-c")

    def test_absent_trailer_returns_none(self):
        self.assertIsNone(self.parse("ADD: something without a trailer"))

    def test_inline_mention_without_line_start_is_not_matched(self):
        """行首錨點：散文中提到 Run-Id 不構成 trailer。"""
        self.assertIsNone(self.parse("see the Run-Id: 2026-09-22-d for details"))

    def test_path_separator_is_not_captured(self):
        """run_id 字元集排除 `/`，路徑逃逸樣式無法組出 run/ 以外的路徑。"""
        self.assertEqual(self.parse("Run-Id: ../../etc/passwd"), "..")

    def test_first_trailer_wins(self):
        self.assertEqual(self.parse("Run-Id: 2026-09-22-e\nRun-Id: 2026-09-22-f"),
                         "2026-09-22-e")


if __name__ == "__main__":
    unittest.main()
