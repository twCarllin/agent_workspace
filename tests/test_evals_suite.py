"""evals/ 行為評測套件的**靜態**結構測試（item 11.3）。

本檔不執行任何 agent：runner 只以 --dry-run 呼叫（本機 python、零費用），情境只做檔案與 AST 檢查。
評測本身是付費、非確定性的真實 agent run，故不進 pytest 預設套件；這裡釘住的是「套件結構不壞」。

執行：python3 -m pytest tests/test_evals_suite.py -q
"""

import ast
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
GITIGNORE = os.path.join(ROOT, ".gitignore")

# 內嵌 CLAUDE.md 副本的指紋：Router 節名只該出現在 repo 根 CLAUDE.md，不該被複製進 evals/ 或 runner
CLAUDE_MD_FINGERPRINT = "難易度分級"
LOAD_RUNNER = (
    "import importlib.util,sys\n"
    f"s=importlib.util.spec_from_file_location('se', {RUNNER!r}); "
    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
)


def case_dirs():
    return sorted(
        os.path.join(EVALS, n)
        for n in os.listdir(EVALS)
        if os.path.isdir(os.path.join(EVALS, n))
        and n != "results"
        and not n.startswith((".", "_"))
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

    def test_dry_run_lists_every_case(self):
        proc = run_runner("--dry-run")
        for d in case_dirs():
            self.assertIn(f"## {os.path.basename(d)}", proc.stdout)

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

    def test_codex_preview_has_requested_model_without_dollar_budget(self):
        proc = run_runner("--dry-run", "--harness", "codex")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("codex exec", proc.stdout)
        self.assertIn("gpt-6.1-terra", proc.stdout)
        self.assertNotIn("--max-budget-usd", proc.stdout)
        self.assertNotIn("--dangerously-bypass", proc.stdout)

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


class CaseStructureTest(unittest.TestCase):
    def test_each_case_has_prompt_check_and_natural_prompt(self):
        self.assertTrue(case_dirs(), "評測案例不可為空")
        for d in case_dirs():
            with self.subTest(case=os.path.basename(d)):
                self.assertTrue(os.path.isfile(os.path.join(d, "prompt.md")))
                src = read(os.path.join(d, "check.py"))
                ast.parse(src)
                self.assertIn(
                    "綁定", src.split('"""', 2)[1], "檔頭 docstring 須註明綁定欄位"
                )
                self.assertNotRegex(
                    read(os.path.join(d, "prompt.md")),
                    r"評測|eval|測試情境",
                    "prompt.md 須是自然需求，不可透露這是評測",
                )

    def test_setup_scripts_parse(self):
        setups = [
            os.path.join(d, "setup.py")
            for d in case_dirs()
            if os.path.isfile(os.path.join(d, "setup.py"))
        ]
        self.assertTrue(setups, "至少 resume-interrupted 須有 setup.py（中斷現場）")
        for p in setups:
            self.assertIsInstance(ast.parse(read(p)), ast.Module, f"{p} 無法解析")


class NoEmbeddedRulesTest(unittest.TestCase):
    """fixture 的規則檔只准以 cp 自 repo 現檔複製；evals/ 與 runner 內不得有 CLAUDE.md 副本（會漂移）。"""

    def test_no_claude_md_fingerprint_under_evals(self):
        hits = []
        for dirpath, dirnames, filenames in os.walk(EVALS):
            dirnames[:] = [x for x in dirnames if x not in ("results", "__pycache__")]
            for n in filenames:
                p = os.path.join(dirpath, n)
                if CLAUDE_MD_FINGERPRINT in read(p):
                    hits.append(os.path.relpath(p, ROOT))
        self.assertEqual(hits, [], f"evals/ 內出現 CLAUDE.md 指紋：{hits}")


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

    def test_min_case_budget_covers_measured_cost(self):
        """門檻須 ≥ 2.0：實測單情境 1.6–2.6 美元，1.0 會開一個必被切斷的 session。"""
        self.assertGreaterEqual(self.se.MIN_CASE_BUDGET_USD, 2.0)

    def test_runner_source_budget_contracts(self):
        src = read(RUNNER)
        for name, snippet in (
            (
                "fail dominates ceiling",
                "if any_fail:\n        return 1\n    return 2 if ceiling_hit else 0",
            ),
            ("unknown cost charged conservatively", 'rec["cost_usd"] = remaining'),
        ):
            with self.subTest(name):
                self.assertIn(snippet, src)


class CheckerZeroAssertionTest(unittest.TestCase):
    def test_finish_with_no_assertions_is_not_pass(self):
        sys.path.insert(0, EVALS)
        try:
            common = importlib.import_module("_common")
        finally:
            sys.path.pop(0)
        self.assertEqual(common.Checker().finish(), 3)


class VersionControlHygieneTest(unittest.TestCase):
    def test_results_dir_ignored(self):
        self.assertIn("evals/results/", read(GITIGNORE).splitlines())


if __name__ == "__main__":
    unittest.main()
