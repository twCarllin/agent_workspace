"""evals/ 行為評測套件的**靜態**結構測試（item 11.3）。

本檔不執行任何 agent：runner 只以 --dry-run 呼叫（本機 python、零費用），情境只做檔案與 AST 檢查。
評測本身是付費、非確定性的真實 agent run，故不進 pytest 預設套件；這裡釘住的是「套件結構不壞」。

執行：python3 -m pytest tests/test_evals_suite.py -q
"""

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, ".claude", "hooks", "skill_eval.py")
EVALS = os.path.join(ROOT, "evals")
LOAD_RUNNER = (
    "import importlib.util,sys\n"
    f"s=importlib.util.spec_from_file_location('se', {RUNNER!r}); "
    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run_runner(*args, env=None):
    return subprocess.run(
        [sys.executable, RUNNER, *args], capture_output=True, text=True, env=env
    )


def _load_runner():
    spec = importlib.util.spec_from_file_location("skill_eval", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_claude(directory, body):
    """在 directory 放假 claude；回傳含該目錄的 PATH。"""
    fake = os.path.join(directory, "claude")
    write(fake, "#!/bin/sh\n" + body + "\n")
    os.chmod(fake, 0o755)
    return directory + os.pathsep + os.environ.get("PATH", "")


def _run_check(case, fixture, result_obj, workdir):
    """以合成 result.json 執行情境 check.py（零費用）；回傳 (exit, stdout)。"""
    rp = os.path.join(workdir, "result.json")
    write(rp, json.dumps(result_obj, ensure_ascii=False))
    case_dir = os.path.join(EVALS, case)
    proc = subprocess.run(
        [sys.executable, os.path.join(case_dir, "check.py"), fixture, rp],
        cwd=case_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


class RunnerDefaultsTest(unittest.TestCase):
    """預算預設值是使用者裁示（runs 1、上限 3 美元），改掉即 FAIL。"""

    def test_dry_run_prints_defaults_and_override_without_calling_claude(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = os.path.join(directory, "invoked")
            path = _fake_claude(directory, 'printf invoked > "$MARKER"\nexit 2')
            env = {**os.environ, "PATH": path, "MARKER": marker}
            for name, args, expected in (
                ("defaults", [], ("runs=1", "max_cost_usd=3.0")),
                ("cost override", ["--max-cost-usd", "1.5"], ("max_cost_usd=1.5",)),
            ):
                with self.subTest(name):
                    proc = run_runner("--dry-run", *args, env=env)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertFalse(os.path.exists(marker), "dry-run 不可呼叫模型 CLI")
                    for token in expected:
                        self.assertIn(token, proc.stdout)

    def test_usage_error_is_exit_one(self):
        self.assertEqual(run_runner("--bogus").returncode, 1)


class RepoRootRejectionTest(unittest.TestCase):
    def test_installed_fixture_matrix_has_resolvable_skills_and_selected_manifest(self):
        runner = _load_runner()
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as td:
                fixture = runner.build_fixture(
                    os.path.join(EVALS, "resume-interrupted"), td, harness
                )
                root = Path(fixture)
                entry = (
                    (root / "CLAUDE.local.md").read_text()
                    if harness == "claude"
                    else tomllib.loads((root / ".codex/config.toml").read_text())[
                        "developer_instructions"
                    ]
                )
                self.assertIn(f'harness: "{harness}"', entry)
                self.assertTrue((root / ".agents/skills/eval-flow/SKILL.md").is_file())
                self.assertTrue(
                    harness != "claude"
                    or (root / ".claude/skills/eval-flow/SKILL.md").is_file()
                )
                manifest = json.loads(
                    (root / "run/2026-10-01-greeting-module.json").read_text()
                )
                self.assertEqual(manifest["harness"], harness)
                self.assertTrue((root / ".git/hooks/commit-msg").is_file())

    def test_runner_refuses_repo_as_fixture_including_symlink_alias(self):
        """R-020：abspath 不解 symlink，別名指向 repo 時也要拒。"""
        with tempfile.TemporaryDirectory() as td:
            alias = os.path.join(td, "alias")
            os.symlink(ROOT, alias)
            for name, target in (("repo root", ROOT), ("symlink alias", alias)):
                with self.subTest(name):
                    proc = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            LOAD_RUNNER + f"m.assert_not_repo({target!r})\n",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(proc.returncode, 1, proc.stderr)


class CheckerContractTest(unittest.TestCase):
    """契約 row（item 11.2）：各 check.py 對合成產物的判定。fixture 由 runner 的 build_fixture 真建（git init＋cp），
    模型回應以合成 result.json 取代——測的是斷言邏輯，不是模型。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def _fixture(self, case):
        wd = tempfile.mkdtemp(prefix="skill-eval-test-")
        self.addCleanup(lambda: shutil.rmtree(wd, ignore_errors=True))
        return wd, self.se.build_fixture(os.path.join(EVALS, case), wd)

    def test_s3_setup_builds_interrupted_scene(self):
        wd, fx = self._fixture("resume-interrupted")
        st = json.loads(read(os.path.join(fx, "eval_state.json")))
        self.assertEqual(st["sub_tasks"][1]["step"], "reviewing")
        self.assertEqual(st["sub_tasks"][0]["status"], "passed")

        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=fx, capture_output=True, text=True
            ).stdout

        # task 2 的測試檔須在 staging；commit 1 不得含 task 2 的實作（現場要真）
        self.assertIn("test_greeting_farewell.py", git("diff", "--cached", "--stat"))
        self.assertNotIn("farewell", git("show", "HEAD:lib/greeting.py"))
        # 須含 .gitignore，否則 run/ 進程式樹快照
        self.assertTrue(os.path.isfile(os.path.join(fx, ".gitignore")))

    def test_checker_verdicts_per_scenario(self):
        resume, routing, hitl = "resume-interrupted", "tier1-routing", "tier1-hitl-stop"
        good = "run 2026-10-01-greeting-module：重派 checker、從步驟 3 續跑。"
        rid = "2026-10-03-stats-json"
        events = f"run/{rid}.events.jsonl"
        init_event = '{"ts": "t", "cmd": "init", "args": {}}\n'

        def manifest(tier):
            return json.dumps({"run_id": rid, "tier": tier, "tier_rationale": "x"})

        plan = "請確認 1 task／1 item 的計畫。"
        for name, case, result, files, append, code_expected, expect_in in (
            ("s3 good resume passes", resume, {"result": good}, {}, {}, 0, ""),
            (
                "s3 wrong response",
                resume,
                {"result": "我不知道要做什麼。"},
                {},
                {},
                1,
                "",
            ),
            ("s3 missing result key", resume, {"is_error": True}, {}, {}, 1, ""),
            (
                # 終態相同也要抓到重跑：events.jsonl 出現 id 1 的事件（🟡-4）
                "s3 rerun of task 1 detected via events",
                resume,
                {"result": good},
                {
                    "run/2026-10-01-greeting-module.events.jsonl": '{"ts": "t", "cmd": "set-step", "args": {"id": 1, "step": "writing"}}\n'
                },
                {},
                1,
                "",
            ),
            (
                "s1 bare fixture",
                routing,
                {"result": "已載入 eval-flow。"},
                {},
                {},
                1,
                "",
            ),
            (
                "s1 tier 1 manifest and init event pass",
                routing,
                {"result": "判 Tier 1"},
                {f"run/{rid}.json": manifest(1), events: init_event},
                {},
                0,
                "",
            ),
            (
                "s1 tier 2 fails",
                routing,
                {"result": "判 Tier 2"},
                {f"run/{rid}.json": manifest(2), events: init_event},
                {},
                1,
                "",
            ),
            (
                "s2 task file and untouched py pass",
                hitl,
                {"result": plan},
                {"task/2026-10-03.md": "- [ ] 1.1 x\n"},
                {},
                0,
                "",
            ),
            (
                "s2 touched py before HITL fails",
                hitl,
                {"result": plan},
                {"task/2026-10-03.md": "- [ ] 1.1 x\n"},
                {".claude/hooks/stats.py": "\n# touched\n"},
                1,
                "stats.py",
            ),
        ):
            with self.subTest(name):
                wd, fx = self._fixture(case)
                for rel, text in files.items():
                    write(os.path.join(fx, rel), text)
                for rel, text in append.items():
                    with open(os.path.join(fx, rel), "a", encoding="utf-8") as f:
                        f.write(text)
                code, out = _run_check(case, fx, result, wd)
                self.assertEqual(code, code_expected, out)
                self.assertNotIn("Traceback", out)
                self.assertIn(expect_in, out)


class RunnerErrorPathTest(unittest.TestCase):
    """契約 row（item 11.1 [邊界]＋claude 缺席）：以假 claude／會拋例外的 check.py 觸發，不呼叫真 claude。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def test_check_script_exception_or_absence_is_checker_error_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            raising = os.path.join(td, "case")
            write(os.path.join(raising, "check.py"), "raise RuntimeError('boom')\n")
            missing = os.path.join(td, "empty")
            os.makedirs(missing)
            for name, case in (
                ("check raises", raising),
                ("check.py missing", missing),
            ):
                with self.subTest(name):
                    verdict, out = self.se.run_check(
                        case, td, os.path.join(td, "nonexistent.json")
                    )
                    self.assertEqual(verdict, "checker_error")
            self.assertIn("boom", self.se.run_check(raising, td, "x")[1])

    def test_non_json_claude_output_is_unparsable_not_pass(self):
        """PATH 前置一個假 claude（印非 JSON）→ run_claude 回 (None, raw, note)。"""
        with tempfile.TemporaryDirectory() as td:
            path = _fake_claude(td, "echo 'this is not json'")
            with mock.patch.dict(os.environ, {"PATH": path}):
                data, raw, note = self.se.run_claude(td, "ping", 1.0, 30)
        self.assertIsNone(data)
        self.assertIn("not json", raw)
        self.assertTrue(note)

    def test_claude_missing_from_path_is_exit_one(self):
        """非 dry-run 且 PATH 無 claude → exit 1，不建 fixture。"""
        with tempfile.TemporaryDirectory() as td:
            proc = run_runner("--case", "tier1-routing", env=dict(os.environ, PATH=td))
        self.assertEqual(proc.returncode, 1, proc.stderr)


class BudgetAccountingTest(unittest.TestCase):
    """🟡-1／🟡-2：預算切斷的 session 記 budget_exhausted 不記 FAIL；拿不到成本時保守記滿。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def test_budget_cut_session_is_budget_exhausted_not_fail(self):
        with tempfile.TemporaryDirectory() as td:
            path = _fake_claude(
                td,
                'echo \'{"is_error": true, "subtype": "error_max_budget_usd", "num_turns": 1, "total_cost_usd": 0.4}\'',
            )
            with mock.patch.dict(os.environ, {"PATH": path}):
                data, raw, note = self.se.run_claude(td, "ping", 0.4, 30)
        self.assertEqual(note, "budget_exhausted")


class CheckerZeroAssertionTest(unittest.TestCase):
    def test_finish_with_no_assertions_is_not_pass(self):
        sys.path.insert(0, EVALS)
        try:
            common = importlib.import_module("_common")
        finally:
            sys.path.pop(0)
        self.assertEqual(common.Checker().finish(), 3)


if __name__ == "__main__":
    unittest.main()
