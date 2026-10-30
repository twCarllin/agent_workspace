"""eval_gates.py 的不變量與判定邏輯測試。

執行：python3 -m unittest discover -s tests -v
block() 以 sys.exit(2) 實作，測試以 SystemExit 斷言攔截行為。
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import eval_gates  # noqa: E402
import stats  # noqa: E402


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


class SharedRuleCompatibilityTest(unittest.TestCase):
    def test_hook_aliases_use_shared_phase_and_identity(self):
        import flow_rules

        self.assertIs(eval_gates.MANIFEST_RE, flow_rules.MANIFEST_RE)
        self.assertIs(eval_gates.PHASES, flow_rules.PHASES)
        self.assertIs(eval_gates.PENDING_STATUSES, flow_rules.PENDING_STATUSES)
        self.assertEqual(
            eval_gates.manifest_phase({"phase": "risk_done", "task_file": "task"}),
            flow_rules.manifest_phase({"phase": "risk_done", "task_file": "task"}),
        )


class ValidateStateTest(unittest.TestCase):
    def state(self, **overrides):
        return {"run_id": "t", "sub_tasks": [make_sub_task(**overrides)]}

    def test_passing_states(self):  # testlint: allow
        # 放行契約：不得拋出阻擋例外。舊格式歸檔多帶 rounds／品質欄位時寬容放行。
        eval_gates.validate_state(self.state(), "test", require_passed=True)
        eval_gates.validate_state(
            self.state(status="in_progress", local_test_passed=False), "test"
        )
        legacy = make_sub_task(rounds=[{"round": 1, "quality_score": 8}])
        eval_gates.validate_state(
            {"run_id": "t", "sub_tasks": [legacy]}, "test", require_passed=True
        )

    def test_blocking_states_exit_2(self):
        absent = make_sub_task()
        del absent["review_reds"]
        cases = {
            "missing_run_id": {"sub_tasks": []},
            "status_not_passed": self.state(status="failed"),
            "local_test_not_passed": self.state(local_test_passed=False),
            "empty_evidence": self.state(local_test_evidence=""),
            "none_evidence": self.state(local_test_evidence=None),
            "review_reds_none": self.state(review_reds=None),
            "review_reds_bool": self.state(review_reds=True),
            "review_reds_negative": self.state(review_reds=-1),
            "review_reds_absent": {"run_id": "t", "sub_tasks": [absent]},
            "verify_passed_false": self.state(verify_passed=False),
            "verify_passed_none": self.state(verify_passed=None),
        }
        for name, state in cases.items():
            with self.subTest(name=name), self.assertRaises(SystemExit) as ctx:
                eval_gates.validate_state(state, "test", require_passed=True)
            self.assertEqual(ctx.exception.code, 2)


class ManifestPhaseTest(unittest.TestCase):
    # 2026-09-22 tier2-slimming（Spec §3.2）：PHASES 5→3，risk_done／usage_confirmed
    # 兩值移除。舊 manifest 顯式帶這兩值時必須映射為 init（向後相容，不可拋例外）；
    # 顯式 legacy 值優先於 task_file 推導（映射若搬到推導之後，第 4 列會誤回 decomposed）。
    def test_phase_mapping_table(self):
        for manifest, expected in (
            ({"phase": "risk_done"}, "init"),
            ({"phase": "usage_confirmed"}, "init"),
            ({"phase": "decomposed"}, "decomposed"),
            ({"phase": "risk_done", "task_file": "task/x.md"}, "init"),
            ({"task_file": "task/x.md"}, "decomposed"),
            ({"usage_report_path": "usage/x.md"}, "init"),
            ({}, "init"),
            ({"phase": "bogus"}, "init"),
            ({"phase": "risk_done", "parent_run_id": "P"}, "init"),
            ({"task_file": "task/x.md", "parent_run_id": "P"}, "decomposed"),
        ):
            with self.subTest(manifest=manifest):
                self.assertEqual(eval_gates.manifest_phase(manifest), expected)


class ManifestRegexTest(unittest.TestCase):
    def test_manifest_path_table(self):
        for path, run_id in (
            ("run/2026-07-15-foo.json", "2026-07-15-foo"),
            ("run/2026-07-25-x-item-1.json", "2026-07-25-x-item-1"),
            ("run/2026-07-15-foo.eval.json", None),
            ("run/2026-07-15-foo.test_baseline.json", None),
            ("run/2026-07-25-x-item-1.eval.json", None),
            ("run/sub/foo.json", None),
        ):
            with self.subTest(path=path):
                m = eval_gates.MANIFEST_RE.match(path)
                self.assertEqual(m.group("run_id") if m else None, run_id)


class TestFileDetectionTest(unittest.TestCase):
    def test_detection_table(self):
        for path, expected in (
            ("test_foo.py", True),
            ("src/foo_test.py", True),
            ("tests/helpers.py", True),
            ("src/foo.py", False),
            ("tests/foo.js", False),
        ):
            with self.subTest(path=path):
                self.assertEqual(eval_gates.is_test_file(path), expected)


HOOK_PY = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_gates.py")
EVAL_STATE_PY = str(
    Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_state.py"
)


def run_hook_proc(payload, project_dir, cwd=None):
    """以 subprocess 跑 eval_gates.py --hook（真實 stdin payload），回傳 CompletedProcess。"""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": project_dir}
    return subprocess.run(
        [sys.executable, HOOK_PY, "--hook"],
        input=json.dumps(payload),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def eval_state_cli(*args):
    return subprocess.run(
        [sys.executable, EVAL_STATE_PY, *args], capture_output=True, text=True
    )


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True)


class CwdTmpCase(unittest.TestCase):
    """在拋棄式暫存目錄內執行（process cwd 切換並於 tearDown 還原）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()
        eval_gates._hint_enabled = False


class GateHitLogTest(CwdTmpCase):
    def test_block_in_hook_mode_logs_hit_when_run_dir_exists(self):
        os.makedirs("run")
        eval_gates._hint_enabled = True
        with self.assertRaises(SystemExit):
            eval_gates.block(
                "測試訊息：第一行\n第二行完整", gate_id="gate.example", run_id="r1"
            )
        record = json.loads(Path("run/gate_hits.log").read_text(encoding="utf-8"))
        self.assertEqual(record["message"], "測試訊息：第一行\n第二行完整")
        self.assertEqual(record["gate_id"], "gate.example")
        self.assertEqual(record["reason"], "gate.example")
        self.assertEqual(record["run_id"], "r1")
        self.assertEqual(record["outcome"], "blocked")
        self.assertEqual(
            datetime.fromisoformat(record["ts"]).utcoffset().total_seconds(), 0
        )

    def test_real_hook_keeps_exit_and_output_contract(self):
        subprocess.run(["git", "init", "-q"], check=True, capture_output=True)
        Path("run").mkdir()
        Path("eval_state.json").write_text(json.dumps({"run_id": "source-run"}))
        root = Path(__file__).resolve().parents[1]
        payload = {
            "cwd": str(Path.cwd()),
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
        }
        for entry in (
            root / ".agent-flow/scripts/eval_gates.py",
            root / ".claude/hooks/eval_gates.py",
        ):
            with self.subTest(entry=entry):
                result = subprocess.run(
                    [sys.executable, str(entry), "--hook"],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("[gate-check] BLOCK:", result.stderr)
                record = json.loads(
                    Path("run/gate_hits.log").read_text().splitlines()[-1]
                )
                self.assertEqual(record["gate_id"], "gate.state_not_archived")
                self.assertEqual(record["run_id"], "source-run")
                self.assertEqual(record["outcome"], "blocked")
                self.assertIn("→ 補救", record["message"])

    def test_log_write_failure_preserves_block(self):
        Path("run/gate_hits.log").mkdir(parents=True)
        eval_gates._hint_enabled = True
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(
            SystemExit
        ) as caught:
            eval_gates.block("original reason", gate_id="gate.example")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("original reason", stderr.getvalue())

    def test_no_log_written(self):
        # hook 模式但無 run/ 目錄不建目錄；validate 模式不寫 log
        eval_gates._hint_enabled = True
        with self.assertRaises(SystemExit):
            eval_gates.block("x")
        self.assertFalse(os.path.exists("run"))
        os.makedirs("run")
        eval_gates._hint_enabled = False
        with self.assertRaises(SystemExit):
            eval_gates.block("x")
        self.assertFalse(os.path.exists("run/gate_hits.log"))

class GitCommitRegexTest(unittest.TestCase):
    def test_commit_detection_table(self):
        for command, expected in (
            ("git commit -m 'x'", True),
            ("git -C /repo commit -m x", True),
            ("cd /repo && git commit --amend", True),
            ("git log --grep 'Run-Id: x'", False),
            ("git diff --cached", False),
        ):
            with self.subTest(command=command):
                self.assertEqual(bool(eval_gates.GIT_COMMIT_RE.search(command)), expected)



class ParentRunIdCompatTest(CwdTmpCase):
    """check_other_runs／check_manifest 對含 parent_run_id 欄位的 manifest 相容性迴歸測試。"""

    def test_parent_run_id_manifest_compat(self):
        for name, status, call, blocks in (
            ("other_runs_in_progress", "in_progress",
             lambda: eval_gates.check_other_runs("current-run"), True),
            ("other_runs_completed", "completed",
             lambda: eval_gates.check_other_runs("current-run"), False),
            # archive not in staged → block（同無 parent_run_id 的 completed manifest 路徑）
            ("manifest_requires_archive", "completed",
             lambda: eval_gates.check_manifest("run/other-run.json", set()), True),
        ):
            with self.subTest(name=name):
                os.makedirs("run", exist_ok=True)
                manifest = {"run_id": "other-run", "status": status,
                            "spec_inline": "s", "parent_run_id": "parent-x"}
                Path("run/other-run.json").write_text(json.dumps(manifest), encoding="utf-8")
                if blocks:  # testlint: allow — else 分支為放行契約：不得拋出阻擋例外
                    with self.assertRaises(SystemExit):
                        call()
                else:
                    call()


class Tier1ManifestCommitTest(CwdTmpCase):
    """DoD (c)：Tier 1 manifest commit gate 的三條路徑。"""

    def setUp(self):
        super().setUp()
        os.makedirs("run")

    def _write_manifest(self, **extra):
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
        Path("run/t1-run.json").write_text(json.dumps(base), encoding="utf-8")

    def test_tier1_four_fields_gate(self):
        # DoD (d) case 1：四欄齊全（含字串 tier "1"）放行；case 2：缺任一欄 block；Tier 2 不受豁免
        # complete／local_test_passed／empty evidence／tier2 無歸檔由 ColdFile C1／C3／C8 e2e 覆蓋
        self._write_manifest(tier="1")  # tier 字串 "1" 與整數 1 皆容許
        eval_gates.check_manifest("run/t1-run.json", set())  # 不得拋出
        for name, extra in (
            ("null_review_reds", {"review_reds": None}),
            ("verify_passed_false", {"verify_passed": False}),
        ):
            with self.subTest(name=name):
                self._write_manifest(**extra)
                with self.assertRaises(SystemExit) as ctx:
                    eval_gates.check_manifest("run/t1-run.json", set())
                self.assertEqual(ctx.exception.code, 2)

    # DoD (d) case 3：有 staged 歸檔檔 → 走舊路徑（向後相容回歸）
    def test_tier1_with_staged_archive_uses_old_path(self):  # testlint: allow
        # manifest 四欄故意非法：走四欄驗證路徑 → block；走歸檔路徑 → pass
        self._write_manifest(local_test_passed=False, review_reds=None)
        archive = {"run_id": "t1-run", "sub_tasks": [make_sub_task()]}
        Path("run/t1-run.eval.json").write_text(json.dumps(archive), encoding="utf-8")
        eval_gates.check_manifest(
            "run/t1-run.json", {"run/t1-run.json", "run/t1-run.eval.json"}
        )


class Tier1SubagentGateTest(CwdTmpCase):
    """DoD (a)(b)：check_task_gate 在無 eval_state.json 時的路徑。"""

    def setUp(self):
        super().setUp()
        os.makedirs("run")

    def _write_manifest(self, run_id, tier=1, status="in_progress", phase="decomposed"):
        m = {"run_id": run_id, "tier": tier, "status": status, "phase": phase,
             "spec_inline": "spec", "task_file": "task/x.md"}
        Path(f"run/{run_id}.json").write_text(json.dumps(m), encoding="utf-8")

    def test_no_eval_state_task_gate_table(self):
        # (name, manifests, expected exit code)；DoD (d) case 4/5/6 與邊界
        for name, manifests, expected in (
            ("unique_tier1_inprogress_passes", [dict(run_id="tier1-run")], 0),
            ("only_tier2_blocks", [dict(run_id="t2-run", tier=2)], 2),
            ("no_manifest_blocks", [], 2),
            ("other_inprogress_blocks",
             [dict(run_id="tier1-run"), dict(run_id="other-run", tier=2)], 2),
            ("phase_below_decomposed_blocks", [dict(run_id="tier1-run", phase="init")], 2),
            ("multiple_tier1_blocks",
             [dict(run_id="tier1-run-a"), dict(run_id="tier1-run-b")], 2),
        ):
            with self.subTest(name=name):
                for p in Path("run").glob("*.json"):
                    p.unlink()
                for kwargs in manifests:
                    self._write_manifest(**kwargs)
                with self.assertRaises(SystemExit) as ctx:
                    eval_gates.check_task_gate({"subagent_type": "code-writer"})
                self.assertEqual(ctx.exception.code, expected)

class RunHookWorktreeRootTest(unittest.TestCase):
    """e2e：run_hook() root 解析在真實 git worktree 下的正確性（拋棄式 repo，不碰真實 run/）。"""

    def setUp(self):
        self.tmp_base = tempfile.TemporaryDirectory()
        base = self.tmp_base.name
        self.main = os.path.join(base, "main")
        os.makedirs(self.main)
        # 初始化拋棄式 main git repo；worktree add 需要至少一個 commit
        git("init", self.main)
        git("-C", self.main, "config", "user.email", "t@t.com")
        git("-C", self.main, "config", "user.name", "T")
        open(os.path.join(self.main, ".gitkeep"), "w").close()
        git("-C", self.main, "add", ".gitkeep")
        git("-C", self.main, "commit", "-m", "init")
        # 建立 worktree（path 不可預先存在）
        self.worktree = os.path.join(base, "worktree")
        git("-C", self.main, "worktree", "add", "--detach", self.worktree)
        self.eval_gates_py = str(
            Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "eval_gates.py"
        )

    def tearDown(self):
        self.tmp_base.cleanup()

    def _run_hook(self, payload, cpd):
        """以 subprocess 跑 eval_gates.py --hook，回傳 returncode。"""
        env = {**os.environ, "CLAUDE_PROJECT_DIR": cpd}
        result = subprocess.run(
            [sys.executable, self.eval_gates_py, "--hook"],
            input=json.dumps(payload),
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode

    def test_hook_links_toolchain_into_worktree_before_gates(self):
        """main 有未追蹤 `.agent-flow/`、worktree 沒有 → hook 後 worktree 內為指回 main 的 symlink。"""
        os.makedirs(os.path.join(self.main, ".agent-flow", "scripts"))
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "cwd": self.worktree,
        }
        rc = self._run_hook(payload, self.main)
        self.assertEqual(rc, 0)
        link = os.path.join(self.worktree, ".agent-flow")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(
            os.path.realpath(link),
            os.path.realpath(os.path.join(self.main, ".agent-flow")),
        )
        # 在主工作區呼叫 → 不建任何連結
        rc = self._run_hook({**payload, "cwd": self.main}, self.main)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.islink(os.path.join(self.main, ".agent-flow")))

    def test_commit_gate_root_resolution(self):
        """eval_state.json 所在目錄 exit 2 證明 root 解析選對目錄。G=核心；A/H 短路；
        E 無 cwd 鍵；C 子目錄 CPD；D 非 git cwd 回落 CPD；B-edge1 worktree 子目錄 chdir 到根。"""
        main, wt = self.main, self.worktree
        sub = os.path.join(main, "subproject")
        wt_src = os.path.join(wt, "src")
        for d in (sub, wt_src):
            os.makedirs(d)
        with tempfile.TemporaryDirectory() as non_git:
            # (name, state 所在目錄, payload cwd, CPD)
            for name, state_dir, cwd, cpd in (
                ("G_worktree_state", wt, wt, main),
                ("A_H_same_dir", main, main, main),
                ("E_no_cwd_key", main, None, main),
                ("C_subdir_cpd", sub, main, sub),
                ("D_non_git_cwd", main, non_git, main),
                ("B_edge1_worktree_subdir", wt, wt_src, main),
            ):
                with self.subTest(name=name):
                    state = os.path.join(state_dir, "eval_state.json")
                    Path(state).write_text(json.dumps({"run_id": "r"}), encoding="utf-8")
                    payload = {"tool_name": "Bash",
                               "tool_input": {"command": "git commit -m x"}}
                    if cwd is not None:
                        payload["cwd"] = cwd
                    self.assertEqual(self._run_hook(payload, cpd), 2)
                    os.remove(state)

    def test_f_subagent_gate_reads_worktree_state(self):
        """[核心/F] worktree 備妥合法 tier2 state+manifest → check_task_gate 讀 worktree → exit 0。"""
        wt_run_dir = os.path.join(self.worktree, "run")
        os.makedirs(wt_run_dir)
        Path(os.path.join(self.worktree, "eval_state.json")).write_text(json.dumps({"run_id": "wt-run", "sub_tasks": []}), encoding="utf-8")
        manifest = {
            "run_id": "wt-run",
            "tier": 2,
            "status": "in_progress",
            "phase": "decomposed",
            "spec_inline": "spec",
            "task_file": "task/x.md",
        }
        Path(os.path.join(wt_run_dir, "wt-run.json")).write_text(json.dumps(manifest), encoding="utf-8")
        payload = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "code-writer"},
            "cwd": self.worktree,
        }
        self.assertEqual(self._run_hook(payload, self.main), 0)

class AbortedConsumptionTest(CwdTmpCase):
    """1a 契約：aborted／failed 皆為「非 in_progress」，四消費點中可離開 git 直接單元測的兩點。
    （另兩點 stats.py Counter、eval-flow-resume SKILL.md 文件面分別見 test_stats.py 與人工核對。）"""

    def setUp(self):
        super().setUp()
        os.makedirs("run")

    def _write(self, name, obj):
        Path(f"run/{name}").write_text(json.dumps(obj), encoding="utf-8")

    def test_check_other_runs_by_status(self):
        # aborted／failed 不擋新 run；in_progress 仍擋（回歸，防止改壞判定式）
        for status, blocks in (("aborted", False), ("failed", False), ("in_progress", True)):
            with self.subTest(status=status):
                self._write("other.json", {"run_id": "other", "status": status})
                if blocks:  # testlint: allow — else 分支為放行契約：不得拋出阻擋例外
                    with self.assertRaises(SystemExit):
                        eval_gates.check_other_runs("current")
                else:
                    eval_gates.check_other_runs("current")  # 不得拋出

    def test_find_unique_tier1_ignores_aborted_and_failed(self):
        for status in ("aborted", "failed"):
            with self.subTest(status=status):
                self._write("a.json", {"run_id": "a", "tier": 1, "status": status})
                self.assertIsNone(eval_gates._find_unique_tier1_inprogress())
        # aborted 與真正 in_progress 共存 → 仍能唯一定位到 in_progress 那個
        self._write("live-run.json", {"run_id": "live-run", "tier": 1, "status": "in_progress"})
        found = eval_gates._find_unique_tier1_inprogress()
        self.assertIsNotNone(found)
        self.assertEqual(found[1]["run_id"], "live-run")

class ManifestDeletionGateTest(CwdTmpCase):
    """1b 契約：check_manifest_deletion 正反向測試（真實 git repo，覆蓋正常/含空白/含特殊字元/
    rename 邊界，依規則消費 git 輸出前查規格選 -z + NUL split 的安全解析）。"""

    def setUp(self):
        super().setUp()
        git("init", "-q")
        git("config", "user.email", "t@t.com")
        git("config", "user.name", "T")

    def _commit_file(self, path, content):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        git("add", path)
        git("commit", "-q", "-m", "init")

    def test_manifest_deletion_blocks(self):
        # 正常／含空白／含特殊字元；rename 視同讓原路徑消失（--no-renames 拆解為刪＋加）
        for name, path, op in (
            ("space", "run/2026-08-20 with space.json", ("rm", "-q")),
            ("special_chars", "run/2026-08-20-a&b-特殊.json", ("rm", "-q")),
            ("rename", "run/2026-08-20-old.json", ("mv",)),
        ):
            with self.subTest(name=name):
                self._commit_file(path, '{"run_id": "x"}')
                if op[0] == "mv":
                    git("mv", path, "run/2026-08-20-new.json")
                else:
                    git(*op, path)
                with self.assertRaises(SystemExit) as ctx:
                    eval_gates.check_manifest_deletion()
                self.assertEqual(ctx.exception.code, 2)
                git("reset", "-q", "--hard")

    def test_non_manifest_changes_pass(self):  # testlint: allow
        # 放行契約：歸檔檔／baseline 檔刪除（B-edge1）、manifest 僅修改、一般檔案刪除皆不得拋出阻擋例外
        for name, path in (
            ("eval_archive", "run/2026-08-20-x.eval.json"),
            ("test_baseline", "run/2026-08-20-x.test_baseline.json"),
            ("non_manifest", "README_temp.md"),
        ):
            with self.subTest(name=name):
                self._commit_file(path, '{"run_id": "x"}')
                git("rm", "-q", path)
                eval_gates.check_manifest_deletion()
                git("reset", "-q", "--hard")
        with self.subTest(name="modify_not_delete"):
            self._commit_file("run/2026-08-20-m.json", '{"status": "in_progress"}')
            Path("run/2026-08-20-m.json").write_text('{"status": "completed"}', encoding="utf-8")
            git("add", "run/2026-08-20-m.json")
            eval_gates.check_manifest_deletion()


class NarrowExceptionGateTest(CwdTmpCase):
    """1d 契約：check_abort_failed_narrow_exception 正反向測試（純函式，僅需檔案存在，不需 git）。"""

    def test_narrow_exception_table(self):
        reason = {"status": "aborted", "failed_reason": "放棄"}
        # (name, 寫入的檔案名, 內容, staged 集合, 預期)
        for name, fname, obj, staged, expected in (
            # aborted＋reason 為 True、混入其他檔為 False：由 IntegrationHookGatesTest e2e 覆蓋
            ("failed_with_reason", "x.json",
             {"status": "failed", "failed_reason": "卡在 step 3"}, {"run/x.json"}, True),
            ("status_completed", "x.json", {"status": "completed"}, {"run/x.json"}, False),
            # 1a「必填」機械強制點
            ("empty_failed_reason", "x.json",
             {"status": "aborted", "failed_reason": ""}, {"run/x.json"}, False),
            ("none_failed_reason", "x.json",
             {"status": "aborted", "failed_reason": None}, {"run/x.json"}, False),
            # 恰一檔但非 manifest（如歸檔檔）
            ("non_manifest_single_file", "x.eval.json", reason, {"run/x.eval.json"}, False),
            ("empty_staged", None, None, set(), False),
            # manifest 不存在（如被刪除）→ 落回防刪除 gate 判定，不誤放行
            ("manifest_file_missing", None, None, {"run/missing.json"}, False),
        ):
            with self.subTest(name=name):
                for p in Path("run").glob("*") if Path("run").exists() else ():
                    p.unlink()
                os.makedirs("run", exist_ok=True)
                if fname:
                    Path(f"run/{fname}").write_text(json.dumps({"run_id": "x", **obj}), encoding="utf-8")
                self.assertIs(
                    eval_gates.check_abort_failed_narrow_exception(staged), expected
                )


class ColdFileLocationGateTest(unittest.TestCase):
    """commit gate 以工作目錄定位 manifest 的契約（task/2026-09-22.md item 1.1 契約表 C1–C12）：
    `Run-Id:` trailer ∪ staged，皆落空時以工作目錄 `status: in_progress` 當安全網。
    全部走真實 git repo ＋ subprocess `--hook`（R-005）。"""

    # 拼接組出 `git commit`，避免本檔文字被 Bash 工具讀寫時命中 PreToolUse 的 GIT_COMMIT_RE。
    GIT_COMMIT = "git " + "commit"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git("init", "-q", self.repo)
        self._git("config", "user.email", "t@t.com")
        self._git("config", "user.name", "T")
        # 先做一個 initial commit，讓 `git diff --cached` 有 HEAD 可比
        self._write_text("seed.txt", "seed\n")
        self._git("add", "seed.txt")
        self._git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    # --- fixture helpers ---

    def _git(self, *args):
        git("-C", self.repo, *args)

    def _reset(self):
        """還原到 initial commit 狀態。"""
        self._git("reset", "-q", "--hard", "HEAD")
        self._git("clean", "-fdq")

    def _write_text(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")

    def _write_json(self, rel, obj):
        self._write_text(rel, json.dumps(obj, ensure_ascii=False))

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

    def _stage_code(self):
        """staged 一個與溯源無關的程式碼檔，模擬正常收尾 commit 的 staging 內容。"""
        self._write_text("app.py", "x = 1\n")
        self._git("add", "app.py")

    def _stage_manifest(self, run_id):
        self._git("add", f"run/{run_id}.json")

    def _run_hook(self, command, project_dir=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        return run_hook_proc(payload, project_dir or self.repo)

    def _commit_cmd(self, run_id=None):
        """commit 指令原文；run_id 非 None 時附 `Run-Id:` trailer（含收尾引號）。"""
        if run_id is None:
            return f'{self.GIT_COMMIT} -m "ADD: demo"'
        return f'{self.GIT_COMMIT} -m "ADD: demo\n\nRun-Id: {run_id}"'

    def test_commit_gate_location_contract(self):
        """C1–C11 + eval_state 不變量。每列：(name, setup(), trailer run_id, 預期 rc,
        stderr 必含的 key, stderr 不得含的字串)。"""
        m, code, stage = self._manifest, self._stage_code, self._stage_manifest
        archive_ok = {"run_id": "2026-09-22-c8", "sub_tasks": [{
            "id": 1, "name": "s1", "status": "passed", "local_test_passed": True,
            "local_test_evidence": "ok", "review_reds": 0, "verify_passed": True}]}
        fake_test = "def test_nothing():\n    assert True\n"

        def c3(): m("2026-09-22-c3", local_test_passed=None); code()
        def c3b(): m("2026-09-22-c3b", local_test_evidence="   "); code()
        def c8():
            m("2026-09-22-c8", tier=2)
            self._write_json("run/2026-09-22-c8.eval.json", archive_ok)
            code()
        def c8c():
            m("2026-09-22-c8c", tier=2)
            self._write_json("run/2026-09-22-c8c.eval.json", {"run_id": "other", "sub_tasks": []})
            code()
        def c9():
            m("2026-09-22-c9")
            self._write_text("tests/test_fake.py", fake_test)
            self._git("add", "tests/test_fake.py")
        def c9b():
            self._write_text("tests/test_fake.py", fake_test)
            self._git("add", "tests/test_fake.py")
        def c7a(): m("2026-09-22-c7"); code(); stage("2026-09-22-c7")
        def c7b(): m("2026-09-22-c7b", status="in_progress"); stage("2026-09-22-c7b")
        def c7c(): m("2026-09-22-c7c", spec_inline=None); stage("2026-09-22-c7c")
        # C10（R-008 組合測試：放行型 vs 攔截型的相互遮蔽）：staged 恰一個 aborted manifest
        # （窄例外三條件全中）同時工作目錄另有 in_progress 的 run → 維持放行（兩者 status
        # 條件互斥，不存在攔截型被永久遮蔽）；多 staged 一個 code 檔則窄例外不成立，
        # 走既有 staged 路徑（check_manifest 攔下 aborted 那份）。
        def c10():
            m("2026-09-22-c10busy", status="in_progress")
            m("2026-09-22-c10", status="aborted", failed_reason="使用者決定不做了")
            stage("2026-09-22-c10")
        def c10b():
            m("2026-09-22-c10busy2", status="in_progress")
            m("2026-09-22-c10b", status="aborted", failed_reason="放棄")
            stage("2026-09-22-c10b"); code()
        # 1.4 情境 N：窄例外三條件全滿足 → 放行，即使 eval_state.json 仍存在也被豁免
        # （情境 B 刪除 manifest＝C11；N-err1 混入其他檔＝C10b，不另列）
        def n_scenario():
            m("2026-09-22-n", status="aborted", failed_reason="使用者決定不做了")
            stage("2026-09-22-n")
            self._write_json("eval_state.json", {"run_id": "n"})
        def c11():
            m("2026-09-22-c11")
            stage("2026-09-22-c11")
            self._git("commit", "-q", "-m", "keep")
            self._git("rm", "-q", "run/2026-09-22-c11.json")
        def es():
            self._write_json("eval_state.json", {"run_id": "x", "sub_tasks": []})
            m("2026-09-22-es"); code()

        for name, setup, trailer, rc, keys, absent in (
            ("C1_trailer_completed_passes", lambda: (m("2026-09-22-c1"), code()),
             "2026-09-22-c1", 0, (), ()),
            ("C2_trailer_inprogress_blocks",
             lambda: (m("2026-09-22-c2", status="in_progress"), code()),
             "2026-09-22-c2", 2, ("status 非 completed",), ()),
            ("C3_missing_credential_blocks", c3, "2026-09-22-c3", 2, ("local_test_passed",), ()),
            ("C3_blank_evidence_blocks", c3b, "2026-09-22-c3b", 2, ("local_test_evidence",), ()),
            ("C4_trailer_missing_manifest_no_block", code, "2026-09-22-nonexistent", 0, (), ()),
            ("C4_trailer_path_traversal_rejected", code, "../../etc/passwd", 0, (), ()),
            ("C5_inprogress_on_disk_blocks_without_trailer",
             lambda: (m("2026-09-22-c5", status="in_progress"), code()),
             None, 2, ("run/2026-09-22-c5.json", "in_progress"), ()),
            ("C6_nothing_passes", code, None, 0, (), ()),
            ("C6_completed_on_disk_no_block",
             lambda: (m("2026-09-22-c6old"), code()), None, 0, (), ()),
            ("C6_aborted_on_disk_no_block",
             lambda: (m("2026-09-22-c6ab", status="aborted", failed_reason="放棄"), code()),
             None, 0, (), ()),
            ("C7_staged_manifest_legacy_passes", c7a, None, 0, (), ()),
            ("C7_staged_inprogress_blocks", c7b, None, 2, ("status 非 completed",), ()),
            ("C7_staged_missing_intent_blocks", c7c, None, 2, ("intent gate",), ()),
            ("C8_tier2_archive_on_disk_passes", c8, "2026-09-22-c8", 0, (), ()),
            ("C8_tier2_missing_archive_blocks",
             lambda: (m("2026-09-22-c8b", tier=2), code()), "2026-09-22-c8b", 2,
             ("run/2026-09-22-c8b.eval.json",), ("git add run/2026-09-22-c8b.eval.json",)),
            ("C8_tier2_archive_run_id_mismatch_blocks", c8c, "2026-09-22-c8c", 2, ("不一致",), ()),
            ("C9_test_lint_runs_via_trailer", c9, "2026-09-22-c9", 2, ("假測試 lint",), ()),
            ("C9_test_lint_not_run_without_manifest", c9b, None, 0, (), ()),
            ("C10_narrow_exception_wins_over_safety_net", c10, None, 0, (), ()),
            ("C10_narrow_exception_requires_sole_staged_file", c10b, None, 2,
             ("run/2026-09-22-c10b.json", "status 非 completed"), ()),
            ("N_narrow_exception_exempts_eval_state", n_scenario, None, 0, (), ()),
            ("C11_manifest_deletion_blocks", c11, None, 2, ("被刪除",), ()),
            ("eval_state_blocks_before_locator", es, "2026-09-22-es", 2, ("eval_state.json",), ()),
        ):
            with self.subTest(name=name):
                self._reset()
                setup()
                result = self._run_hook(self._commit_cmd(trailer))
                self.assertEqual(result.returncode, rc, result.stderr)
                for key in keys:
                    self.assertIn(key, result.stderr)
                for s in absent:
                    self.assertNotIn(s, result.stderr)

    # 回歸（2026-08-20 code-review 🔴；R-008 組合）：`git rm --cached` 保留工作區檔案內容為
    # status=aborted＋failed_reason 非空（窄例外三條件全中）。修正前窄例外先於防刪除 gate
    # 判定而放行（exit 0）；修正後防刪除 gate 先看 git 索引狀態，仍須 block（exit 2）。
    def test_git_rm_cached_aborted_manifest_still_blocked_end_to_end(self):
        self._manifest("2026-08-20-rc", status="aborted", failed_reason="使用者決定不做了")
        self._stage_manifest("2026-08-20-rc")
        self._git("commit", "-q", "-m", "keep")
        self._git("rm", "-q", "--cached", "run/2026-08-20-rc.json")
        self.assertTrue(os.path.exists(os.path.join(self.repo, "run/2026-08-20-rc.json")))
        result = self._run_hook(self._commit_cmd())
        self.assertEqual(result.returncode, 2)
        self.assertIn("被刪除", result.stderr)

    def test_c12_non_git_repo_fails_open(self):
        """C12：非 git repo → fail-open（exit 0），安全網不得把 gate 變成硬失敗。"""
        with tempfile.TemporaryDirectory() as plain:
            result = self._run_hook(self._commit_cmd(), project_dir=plain)
            self.assertEqual(result.returncode, 0, result.stderr)


class LegacyPhaseCompatibilityTest(unittest.TestCase):
    """item 3.2（task/2026-09-22.md）：舊 manifest phase 值域（risk_done／usage_confirmed）
    與 check_task_gate()／manifest_phase() 的向後相容（Spec §3.2、DoD 2）。
    走真實 `--hook` 子程序與 `tool_name: "Task"` payload（R-005）。"""

    # 欄位組合取自 run/2026-08-20-obs-hardening.json（真實 Tier 2 manifest 形狀）
    LEGACY_FIELD_SHAPE = {
        "tier": 2,
        "spec_path": "spec/demo.md",
        "spec_inline": None,
        "risk_report_path": "risk/demo.md",
        "usage_report_path": "usage/demo.md",
        "impact_report_path": None,
        "task_file": None,
        "status": "in_progress",
        "failed_reason": None,
        "local_test_passed": None,
        "local_test_evidence": None,
        "verification_commands": [],
        "review_reds": None,
        "verify_passed": None,
    }

    def test_legacy_phase_manifest_subagent_gate_e2e(self):
        # (name, manifest 的 phase（None＝無顯式 phase 鍵）, subagent, expected rc)
        for name, phase, subagent, rc in (
            # AGENT_MIN_PHASE 改 init 後，舊值 risk_done 映射 init，init>=init → 放行
            ("risk_done_impact_analyzer", "risk_done", "impact-analyzer", 0),
            # 舊值 usage_confirmed 映射 init；擋人兩條（usage_report_path 空/skipped）已隨 §3.2 移除
            ("usage_confirmed_task_decomposer", "usage_confirmed", "task-decomposer", 0),
            # [組合] init < decomposed（code-writer 門檻）→ block；無 Traceback 坐實映射未讓
            # PHASES.index() 對離域值拋 ValueError（R-005 同型防線，DoD 2）
            ("usage_confirmed_code_writer_blocks", "usage_confirmed", "code-writer", 2),
            # sabotage 2：無顯式 phase 鍵、usage_report_path 非空走推導分支，若映射修正被撤銷
            # 會回傳離域值 → PHASES.index 拋 ValueError（非 exit 2）
            ("no_explicit_phase_derivation", None, "impact-analyzer", 0),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as repo:
                os.makedirs(os.path.join(repo, "run"))
                m = {"run_id": "2026-09-22-legacy", **self.LEGACY_FIELD_SHAPE}
                if phase is not None:
                    m["phase"] = phase
                Path(os.path.join(repo, "run", "2026-09-22-legacy.json")).write_text(json.dumps(m), encoding="utf-8")
                Path(os.path.join(repo, "eval_state.json")).write_text(json.dumps({"run_id": "2026-09-22-legacy", "sub_tasks": []}), encoding="utf-8")
                payload = {"tool_name": "Task", "tool_input": {"subagent_type": subagent}}
                result = run_hook_proc(payload, repo)
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    # --- DoD ②：新值 ⊂ 舊值域（雙向相容，H-err2）---

    def test_existing_phases_keep_legacy_domain_with_partial_extension(self):
        """既有 phase 保持相容；partial 明確擴充終態，不冒用 completed。"""
        legacy_domain = {
            "init",
            "risk_done",
            "usage_confirmed",
            "decomposed",
            "completed",
        }
        self.assertTrue((set(eval_gates.PHASES) - {"partial"}).issubset(legacy_domain))
        self.assertEqual(
            set(eval_gates.PHASES), {"init", "decomposed", "completed", "partial"}
        )


class RunIdTrailerRegexTest(unittest.TestCase):
    """`RUN_ID_TRAILER_RE` 的解析邊界：對象是 Bash 指令原文，行尾可能殘留 shell 語法。"""

    def test_trailer_parse_table(self):
        cases = (
            ('x -m "m\n\nRun-Id: 2026-09-22-a"', "2026-09-22-a"),  # 收尾引號不捲入
            ('m\n\nRun-Id: 2026-09-22-b\nEOF\n)"', "2026-09-22-b"),  # heredoc 結尾
            ("  Run-Id:\t2026-09-22-c  ", "2026-09-22-c"),  # 前後空白
            ("ADD: something without a trailer", None),
            ("see the Run-Id: 2026-09-22-d for details", None),  # 行首錨點
            ("Run-Id: ../../etc/passwd", ".."),  # 字元集排除 `/`
            ("Run-Id: 2026-09-22-e\nRun-Id: 2026-09-22-f", "2026-09-22-e"),  # 第一個為準
        )
        for command, expected in cases:
            with self.subTest(command=command):
                m = eval_gates.RUN_ID_TRAILER_RE.search(command)
                self.assertEqual(m.group(1) if m else None, expected)


class PerTaskSubTaskChainTest(CwdTmpCase):
    """item 4.4：per-task sub_task 全鏈整合 ＋ 舊歸檔形狀相容（Q2／Q8／Q10）。
    ①新形狀全鏈串得通 ②19 份舊歸檔（帶 risk_analysis／rounds）仍通過 ③不得回頭加 item 層。"""

    # 取自真實歸檔 run/2026-07-16-floor-audit-gates.eval.json；刻意保留已移除的
    # risk_analysis（Q8）與 legacy rounds 鍵：舊檔多帶的鍵不得造成判定變化。
    LEGACY_ARCHIVE_SUBTASK = {
        "id": 1,
        "name": "舊語義：這一筆代表一個 item",
        "status": "passed",
        "step": "done",
        "files": ["src/a.py"],
        "warning": False,
        "local_test_passed": True,
        "local_test_evidence": "pytest -q -> 12 passed",
        "review_reds": 0,
        "verify_passed": True,
        "risk_analysis": {"technical": "🟡 舊前置 1 留下的面向映射"},
        "rounds": [{"score": 9}],
    }

    def _read_state(self):
        with open("eval_state.json", encoding="utf-8") as f:
            return json.load(f)

    # --- DoD① 新形狀全鏈 ---

    def test_per_task_chain_reaches_valid_state(self):
        """全鏈以 task id 定址通過（Q2／Q10）；DoD③：state 不得出現 `items` 鍵。"""
        self.assertEqual(eval_state_cli("init", "--run-id", "r-chain").returncode, 0)
        self.assertEqual(
            eval_state_cli("add-subtask", "--id", "1", "--name", "Task 1").returncode, 0
        )
        for args in (
            ("set-files", "1", "src/a.py", "src/b.py"),
            ("set-review", "1", "0", "--checked-by", "checker"),
            ("set-verify", "1"),
            ("set-test", "1", "--passed", "--evidence", "unittest -> 380 passed"),
            ("set-status", "1", "passed"),
        ):
            self.assertEqual(eval_state_cli(*args).returncode, 0, args)

        state = self._read_state()
        # 不拋例外＝通過（validate_state 以 block()/SystemExit 表示失敗）
        eval_gates.validate_state(state, "chain", require_passed=True)

        st = state["sub_tasks"][0]
        self.assertEqual(st["files"], ["src/a.py", "src/b.py"])
        self.assertEqual(st["review_reds"], 0)
        self.assertIs(st["verify_passed"], True)
        self.assertIs(st["local_test_passed"], True)
        self.assertNotIn("items", st)

    def test_incomplete_task_still_blocked(self):
        """反向：憑據不齊的 task 仍被擋（per-task 化不得放寬既有不變量）。"""
        eval_state_cli("init", "--run-id", "r-chain2")
        eval_state_cli("add-subtask", "--id", "1", "--name", "Task 1")
        eval_state_cli("set-status", "1", "passed")
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(self._read_state(), "chain2", require_passed=True)
        self.assertEqual(ctx.exception.code, 2)

    # --- DoD② 舊歸檔形狀相容 ---

    def test_legacy_archive_shape(self):
        """19 份舊歸檔形狀仍通過驗證（Q8）；寬容不得變成放行——憑據真的缺時照樣擋。"""
        good = dict(self.LEGACY_ARCHIVE_SUBTASK)
        eval_gates.validate_state(  # 不拋例外＝通過
            {"run_id": "legacy", "sub_tasks": [good]}, "legacy", require_passed=True
        )
        bad = dict(self.LEGACY_ARCHIVE_SUBTASK, verify_passed=False)
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.validate_state(
                {"run_id": "legacy", "sub_tasks": [bad]}, "legacy", require_passed=True
            )
        self.assertEqual(ctx.exception.code, 2)


class CrossHookFullChainTest(CwdTmpCase):
    """item 5.3①：跨 hook 整合——manifest_phase → check_task_gate → validate_state →
    stats.collect 端到端自洽；run_id 用 2026-09-22 起的日期前綴以計入「新期」分母（R-007）。"""

    RUN_ID = "2026-09-22-fullchain-test"

    def _write_manifest(self, **overrides):
        os.makedirs("run", exist_ok=True)
        manifest = {
            "run_id": self.RUN_ID,
            "spec_inline": "test spec",
            "status": "in_progress",
            "phase": "decomposed",
            "task_file": "task/2026-09-22.md",
        }
        manifest.update(overrides)
        Path(f"run/{self.RUN_ID}.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_full_chain_self_consistent_and_counted_as_new_period(self):
        self._write_manifest()
        self.assertEqual(eval_state_cli("init", "--run-id", self.RUN_ID).returncode, 0)
        self.assertEqual(
            eval_state_cli("add-subtask", "--id", "1", "--name", "Task 1").returncode, 0
        )

        # ① manifest_phase → check_task_gate：decomposed 滿足 code-writer 門檻 → 放行
        with self.assertRaises(SystemExit) as ctx:
            eval_gates.check_task_gate({"subagent_type": "code-writer"})
        self.assertEqual(ctx.exception.code, 0)

        # 走完循環，憑據齊全
        for args in (
            ("set-files", "1", "src/a.py"),
            ("set-review", "1", "0", "--checked-by", "checker"),
            ("set-verify", "1"),
            ("set-test", "1", "--passed", "--evidence", "unittest -> ok"),
            ("set-status", "1", "passed"),
        ):
            self.assertEqual(eval_state_cli(*args).returncode, 0, args)

        # ② validate_state：不拋例外＝通過
        with open("eval_state.json", encoding="utf-8") as f:
            eval_gates.validate_state(json.load(f), "fullchain", require_passed=True)

        # 歸檔（archive 內部也呼叫 validate_state，二次坐實）＋收尾 manifest
        self.assertEqual(eval_state_cli("archive").returncode, 0)
        self._write_manifest(status="completed", phase="completed")

        # check_manifest：歸檔檔存在於工作目錄（未 staged）仍應通過，不 block
        eval_gates.check_manifest(f"run/{self.RUN_ID}.json", staged=set())

        # ③ stats.collect：新期（run_id >= PER_TASK_CUTOFF）分母＝task 數，正確累計且不崩
        data = stats.collect("run")
        self.assertEqual(data["sub_tasks_new"], 1)
        self.assertEqual(data["rework_new"], 0)  # review_reds=0
        self.assertEqual(data["checked_by_direct_new"], 1)  # checked_by=checker
        self.assertEqual(data["sub_tasks"], 0)  # 舊期分母不受污染
        self.assertIn(stats.PER_TASK_CUTOFF, stats.report(data))  # 斷點標示出現在輸出中


class DispatchCommandGateTest(unittest.TestCase):
    """item 1.3（task/2026-09-29.md）契約 G1–G4：Bash `dispatch.py <role>` 派工指令同受 gate 7
    phase 狀態機（Spec 2026-09-29 §3.2）。全部走真實 `--hook` 子程序路徑、`tool_name: "Bash"`
    payload（R-005）；Tier 1 manifest、無 eval_state.json。G5（commit gate 與 Task/Agent 路徑
    不變）由既有測試全綠坐實，不重列。"""

    def test_dispatch_gate_table(self):
        cd = "python3 .claude/hooks/dispatch.py"
        for name, phase, command, rc in (
            ("G1_code_writer_at_init_blocks", "init", f"{cd} code-writer --prompt-file p.md", 2),
            ("G2_code_writer_at_decomposed_passes", "decomposed",
             f"{cd} code-writer --prompt-file p.md", 0),
            # G3 [組合]：旗標在 role 前仍解析到 role；task-verifier 不在 AGENT_MIN_PHASE
            ("G3_flags_before_unmanaged_role_passes", "init",
             f"{cd} --backend codex task-verifier --prompt-file p.md", 0),
            ("G3_flags_before_code_writer_blocks", "init",
             f"{cd} --backend codex code-writer --prompt-file p.md", 2),
            # G4 [邊界]：非管轄角色、無派工字樣的指令不觸 gate
            ("G4_unmanaged_role_untouched", "init", f"{cd} explore-foo --prompt-file p.md", 0),
            ("G4_plain_command_untouched", "init", "git status", 0),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as repo:
                os.makedirs(os.path.join(repo, "run"))
                m = {"run_id": "2026-09-29-dispatch-gate", "tier": 1, "status": "in_progress",
                     "phase": phase, "spec_inline": "s", "task_file": "task/x.md"}
                Path(os.path.join(repo, "run", "2026-09-29-dispatch-gate.json")).write_text(json.dumps(m), encoding="utf-8")
                payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo}
                result = run_hook_proc(payload, repo)
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                if rc == 2:
                    self.assertIn("phase 狀態機", result.stderr)
                else:
                    self.assertEqual(result.stderr, "")


class WriteGateTest(unittest.TestCase):
    """item 13.1 契約：HITL 未過（phase < decomposed）不得以 Write／Edit 寫實作檔。
    全部走真實 `--hook` 子程序路徑（R-005），Tier 1 manifest、無 eval_state.json。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)  # macOS /var → /private/var：兩側同基準
        for d in ("run", "task", "spec", ".claude/hooks"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        Path(os.path.join(self.repo, ".claude", "hooks", "stats.py")).write_text("print('stats')\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest(self, phase="init", status="in_progress"):
        m = {"run_id": "2026-10-03-probe", "tier": 1, "status": status, "phase": phase,
             "spec_inline": "s", "task_file": "task/x.md"}
        Path(os.path.join(self.repo, "run", "2026-10-03-probe.json")).write_text(json.dumps(m), encoding="utf-8")

    def _run(self, tool_input, tool_name="Write"):
        payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": self.repo}
        return run_hook_proc(payload, self.repo)

    def _abs(self, rel):
        return os.path.join(self.repo, rel)

    def test_impl_file_blocked_before_hitl(self):
        """核心契約：in_progress＋phase init＋寫實作檔 → exit 2；Write／Edit／NotebookEdit
        同受攔截（notebook 走 notebook_path 鍵）；經 symlink 別名指向 repo 內仍擋（R-020）。"""
        self._write_manifest("init")
        stats_py = self._abs(".claude/hooks/stats.py")
        alias = os.path.join(os.path.dirname(self.repo), "alias-" + os.path.basename(self.repo))
        os.symlink(self.repo, alias)
        self.addCleanup(os.unlink, alias)
        for name, tool, tool_input in (
            ("write", "Write", {"file_path": stats_py}),
            ("edit", "Edit", {"file_path": stats_py}),
            ("notebook", "NotebookEdit", {"notebook_path": self._abs("nb.ipynb")}),
            ("symlink_alias", "Write",
             {"file_path": os.path.join(alias, ".claude", "hooks", "stats.py")}),
        ):
            with self.subTest(name=name):
                result = self._run(tool_input, tool_name=tool)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("phase=init", result.stderr)
                self.assertIn("hitl-confirm 2026-10-03-probe", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_blocking_gate_precedes_permissive_early_return(self):
        """R-008 組合測試：放行型早回的條件成立（payload 帶空 command，非 commit 指令）
        但攔截型也該觸發 → 仍須 exit 2。順序寫錯（攔截型排在早回之後）時本測試會綠轉紅。"""
        self._write_manifest("init")
        result = self._run({"file_path": self._abs(".claude/hooks/stats.py"), "command": ""})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("phase=init", result.stderr)

    def test_non_gated_cases_exit_0(self):
        stats_py = self._abs(".claude/hooks/stats.py")
        cases = [
            ("allowed_after_hitl", "decomposed", "Write", {"file_path": stats_py}),
            ("no_pending_run", None, "Write", {"file_path": stats_py}),
            ("aborted_run", ("init", "aborted"), "Write", {"file_path": stats_py}),
            ("failed_run", ("init", "failed"), "Write", {"file_path": stats_py}),
            ("outside_repo", "init", "Write", {"file_path": "/tmp/outside_probe.py"}),
            ("missing_file_path_key", "init", "Write", {}),
            ("non_string_file_path", "init", "Write", {"file_path": {"nested": 1}}),
            ("bash_payload", "init", "Bash", {"command": "git status"}),
        ] + [
            # 豁免清單：前置階段要寫的溯源與規格檔照常可寫
            (f"exempt:{rel}", "init", "Write", {"file_path": self._abs(rel)})
            for rel in ("task/2026-10-03.md", "spec/x.md", "run/2026-10-03-probe.json",
                        "eval_state.json", "retro/RETRO.md", "evals/results/r.json")
        ]
        for name, manifest, tool, tool_input in cases:
            with self.subTest(name=name):
                for p in Path(self.repo, "run").glob("*.json"):
                    p.unlink()
                if isinstance(manifest, tuple):
                    self._write_manifest(*manifest)
                elif manifest:
                    self._write_manifest(manifest)
                result = self._run(tool_input, tool_name=tool)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
