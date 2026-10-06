"""evals/ 行為評測套件的**靜態**結構測試（item 11.3）。

本檔不執行任何 agent：runner 只以 --dry-run 呼叫（本機 python、零費用），情境只做檔案與 AST 檢查。
評測本身是付費、非確定性的真實 agent run，故不進 pytest 預設套件；這裡釘住的是「套件結構不壞」。

執行：python3 -m pytest tests/test_evals_suite.py -q
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, ".claude", "hooks", "skill_eval.py")
EVALS = os.path.join(ROOT, "evals")
GITIGNORE = os.path.join(ROOT, ".gitignore")

# 內嵌 CLAUDE.md 副本的指紋：Router 節名只該出現在 repo 根 CLAUDE.md，不該被複製進 evals/ 或 runner
CLAUDE_MD_FINGERPRINT = "難易度分級"


def case_dirs():
    return sorted(
        os.path.join(EVALS, n) for n in os.listdir(EVALS)
        if os.path.isdir(os.path.join(EVALS, n)) and n != "results" and not n.startswith((".", "_"))
    )


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_runner(*args):
    return subprocess.run([sys.executable, RUNNER, *args], capture_output=True, text=True)


class RunnerDefaultsTest(unittest.TestCase):
    """預算預設值是使用者裁示（runs 1、上限 3 美元），改掉即 FAIL。"""

    def test_dry_run_prints_defaults_without_calling_claude(self):
        proc = run_runner("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("runs=1", proc.stdout)
        self.assertIn("max_cost_usd=3.0", proc.stdout)
        self.assertIn("不呼叫 claude", proc.stdout)

    def test_default_constants_pinned(self):
        src = read(RUNNER)
        self.assertIsNotNone(re.search(r"^DEFAULT_RUNS = 1$", src, re.M), "DEFAULT_RUNS 預設須為 1")
        self.assertIsNotNone(re.search(r"^DEFAULT_MAX_COST_USD = 3\.0$", src, re.M), "DEFAULT_MAX_COST_USD 預設須為 3.0")

    def test_dry_run_lists_every_case(self):
        proc = run_runner("--dry-run")
        for d in case_dirs():
            self.assertIn(f"## {os.path.basename(d)}", proc.stdout)

    def test_cost_override_reflected(self):
        proc = run_runner("--dry-run", "--max-cost-usd", "1.5")
        self.assertIn("max_cost_usd=1.5", proc.stdout)

    def test_usage_error_is_exit_one(self):
        proc = run_runner("--bogus")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("參數錯誤", proc.stderr)

    def test_dry_run_source_has_no_claude_invocation_before_plan(self):
        """dry-run 路徑在 shutil.which('claude') 之前就 return：以 AST 確認 print_plan 的 return 先於 which。"""
        src = read(RUNNER)
        i_plan = src.index("print_plan(cases, args)")
        i_which = src.index('shutil.which(args.harness)')
        self.assertLess(i_plan, i_which, "dry-run 必須在檢查 claude CLI 之前返回")


class RepoRootRejectionTest(unittest.TestCase):
    def test_installed_fixture_matrix_has_resolvable_skills_and_selected_manifest(self):
        runner = _load_runner()
        for harness in ('claude', 'codex'):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as td:
                fixture = runner.build_fixture(os.path.join(EVALS, 'resume-interrupted'), td, harness)
                from pathlib import Path
                root = Path(fixture)
                entry = (root / 'CLAUDE.local.md').read_text() if harness == 'claude' else \
                    tomllib.loads((root / '.codex/config.toml').read_text())['developer_instructions']
                self.assertIn(f'harness: "{harness}"', entry)
                self.assertTrue((root / '.agents/skills/eval-flow/SKILL.md').is_file())
                if harness == 'claude':  # testlint: allow -- Claude-only path; shared-skill assertions run for both harnesses.
                    self.assertTrue((root / '.claude/skills/eval-flow/SKILL.md').is_file())
                import json
                manifest = json.loads((root / 'run/2026-10-01-greeting-module.json').read_text())
                self.assertEqual(manifest['harness'], harness)
                self.assertTrue((root / '.git/hooks/commit-msg').is_file())

    def test_codex_preview_has_requested_model_without_dollar_budget(self):
        proc = run_runner('--dry-run', '--harness', 'codex')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codex exec', proc.stdout)
        self.assertIn('gpt-6.1-sol', proc.stdout)
        self.assertNotIn('--max-budget-usd', proc.stdout)
        self.assertNotIn('--dangerously-bypass', proc.stdout)

    def test_runner_refuses_repo_as_fixture(self):
        code = (
            "import importlib.util,sys\n"
            f"s=importlib.util.spec_from_file_location('se', {RUNNER!r}); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            f"m.assert_not_repo({ROOT!r})\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("拒絕以 repo 本身為 fixture", proc.stderr)

    def test_rejection_uses_realpath(self):
        """symlink 別名指向 repo 時也要拒（R-020：abspath 不解 symlink）。"""
        with tempfile.TemporaryDirectory() as td:
            alias = os.path.join(td, "alias")
            os.symlink(ROOT, alias)
            code = (
                "import importlib.util,sys\n"
                f"s=importlib.util.spec_from_file_location('se', {RUNNER!r}); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                f"m.assert_not_repo({alias!r})\n"
            )
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1, "symlink 指向 repo 根仍須被拒")


class CaseStructureTest(unittest.TestCase):
    def test_at_least_three_cases(self):
        self.assertGreaterEqual(len(case_dirs()), 3, [os.path.basename(d) for d in case_dirs()])

    def test_each_case_has_prompt_and_check(self):
        for d in case_dirs():
            with self.subTest(case=os.path.basename(d)):
                self.assertTrue(os.path.isfile(os.path.join(d, "prompt.md")), f"{os.path.basename(d)} 缺 prompt.md")
                self.assertTrue(os.path.isfile(os.path.join(d, "check.py")), f"{os.path.basename(d)} 缺 check.py")

    def test_check_scripts_parse_and_declare_bound_fields(self):
        for d in case_dirs():
            p = os.path.join(d, "check.py")
            with self.subTest(case=os.path.basename(d)):
                src = read(p)
                ast.parse(src)
                self.assertIn("綁定", src.split('"""', 2)[1], f"{p} 檔頭 docstring 須註明綁定欄位")

    def test_setup_scripts_parse(self):
        setups = [os.path.join(d, "setup.py") for d in case_dirs() if os.path.isfile(os.path.join(d, "setup.py"))]
        self.assertTrue(setups, "至少 resume-interrupted 須有 setup.py（中斷現場）")
        for p in setups:
            self.assertIsInstance(ast.parse(read(p)), ast.Module, f"{p} 無法解析")

    def test_prompts_do_not_tell_the_model_it_is_being_evaluated(self):
        for d in case_dirs():
            with self.subTest(case=os.path.basename(d)):
                self.assertNotRegex(read(os.path.join(d, "prompt.md")), r"評測|eval|測試情境",
                                    "prompt.md 須是自然需求，不可透露這是評測")

    def test_results_dir_is_not_a_case(self):
        self.assertNotIn(os.path.join(EVALS, "results"), case_dirs())


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

    def test_runner_copies_rules_rather_than_embedding(self):
        src = read(RUNNER)
        self.assertNotIn(CLAUDE_MD_FINGERPRINT, src)
        self.assertIn("install_harness.py", src)


def _load_runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("skill_eval", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_check(case, fixture, result_obj, workdir):
    """以合成 result.json 執行情境 check.py（零費用）；回傳 (exit, stdout)。"""
    import json
    rp = os.path.join(workdir, "result.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(result_obj, f, ensure_ascii=False)
    case_dir = os.path.join(EVALS, case)
    proc = subprocess.run([sys.executable, os.path.join(case_dir, "check.py"), fixture, rp],
                          cwd=case_dir, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


class CheckerContractTest(unittest.TestCase):
    """契約 row（item 11.2）：各 check.py 對合成產物的判定。fixture 由 runner 的 build_fixture 真建（git init＋cp），
    模型回應以合成 result.json 取代——測的是斷言邏輯，不是模型。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def _fixture(self, case):
        wd = tempfile.mkdtemp(prefix="skill-eval-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(wd, ignore_errors=True))
        return wd, self.se.build_fixture(os.path.join(EVALS, case), wd)

    def test_s3_setup_builds_interrupted_scene(self):
        import json
        wd, fx = self._fixture("resume-interrupted")
        st = json.load(open(os.path.join(fx, "eval_state.json"), encoding="utf-8"))
        self.assertEqual(st["sub_tasks"][1]["step"], "reviewing")
        self.assertEqual(st["sub_tasks"][0]["status"], "passed")
        staged = subprocess.run(["git", "diff", "--cached", "--stat"], cwd=fx, capture_output=True, text=True).stdout
        self.assertIn("test_greeting_farewell.py", staged, "task 2 的測試檔須在 staging")
        head = subprocess.run(["git", "show", "HEAD:lib/greeting.py"], cwd=fx, capture_output=True, text=True).stdout
        self.assertNotIn("farewell", head, "commit 1 不得含 task 2 的實作（現場要真）")
        self.assertTrue(os.path.isfile(os.path.join(fx, ".gitignore")), "fixture 須含 .gitignore（否則 run/ 進程式樹快照）")

    def test_s3_good_resume_response_passes(self):
        wd, fx = self._fixture("resume-interrupted")
        code, out = _run_check("resume-interrupted", fx,
                               {"result": "run 2026-10-01-greeting-module：task 2 卡在 reviewing，重派 checker、從循環步驟 3 續跑。"}, wd)
        self.assertEqual(code, 0, out)
        self.assertIn("[check] FAIL 0 條", out)

    def test_s3_wrong_response_fails_without_exception(self):
        wd, fx = self._fixture("resume-interrupted")
        code, out = _run_check("resume-interrupted", fx, {"result": "我不知道要做什麼。"}, wd)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL 回應含正確 run_id", out)
        self.assertNotIn("Traceback", out)

    def test_s3_missing_result_key_fails_without_exception(self):
        wd, fx = self._fixture("resume-interrupted")
        code, out = _run_check("resume-interrupted", fx, {"is_error": True}, wd)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL 輸出含 result", out)
        self.assertNotIn("Traceback", out)

    def test_s3_rerun_of_task1_detected_via_events(self):
        """終態相同也要抓到重跑：events.jsonl 出現 id 1 的事件 → FAIL（🟡-4）。"""
        wd, fx = self._fixture("resume-interrupted")
        os.makedirs(os.path.join(fx, "run"), exist_ok=True)
        with open(os.path.join(fx, "run", "2026-10-01-greeting-module.events.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"ts": "t", "cmd": "set-step", "args": {"id": 1, "step": "writing"}}\n')
        code, out = _run_check("resume-interrupted", fx,
                               {"result": "run 2026-10-01-greeting-module：重派 checker、從步驟 3 續跑。"}, wd)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL task 1 未被重跑", out)

    def test_s1_bare_fixture_fails_without_exception(self):
        wd, fx = self._fixture("tier1-routing")
        code, out = _run_check("tier1-routing", fx, {"result": "我已載入 eval-flow skill。"}, wd)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL manifest 已建立", out)
        self.assertNotIn("Traceback", out)

    def test_s1_manifest_and_init_event_pass(self):
        import json
        wd, fx = self._fixture("tier1-routing")
        os.makedirs(os.path.join(fx, "run"))
        rid = "2026-10-03-stats-json"
        json.dump({"run_id": rid, "tier": 1, "tier_rationale": "理由碼空集合"},
                  open(os.path.join(fx, "run", f"{rid}.json"), "w", encoding="utf-8"))
        open(os.path.join(fx, "run", f"{rid}.events.jsonl"), "w", encoding="utf-8").write(
            '{"ts": "t", "cmd": "init", "args": {}}\n')
        code, out = _run_check("tier1-routing", fx, {"result": "判 Tier 1，請確認計畫。"}, wd)
        self.assertEqual(code, 0, out)

    def test_s1_tier_two_fails(self):
        import json
        wd, fx = self._fixture("tier1-routing")
        os.makedirs(os.path.join(fx, "run"))
        json.dump({"run_id": "r", "tier": 2, "tier_rationale": "x"}, open(os.path.join(fx, "run", "r.json"), "w"))
        code, out = _run_check("tier1-routing", fx, {"result": "判 Tier 2"}, wd)
        self.assertEqual(code, 1)
        self.assertIn("FAIL tier 判為 1", out)

    def test_s2_task_file_and_untouched_py_pass(self):
        wd, fx = self._fixture("tier1-hitl-stop")
        os.makedirs(os.path.join(fx, "task"))
        open(os.path.join(fx, "task", "2026-10-03.md"), "w", encoding="utf-8").write("- [ ] 1.1 x\n")
        code, out = _run_check("tier1-hitl-stop", fx, {"result": "請確認 1 task／1 item 的計畫。"}, wd)
        self.assertEqual(code, 0, out)

    def test_s2_touched_py_before_hitl_fails(self):
        wd, fx = self._fixture("tier1-hitl-stop")
        os.makedirs(os.path.join(fx, "task"))
        open(os.path.join(fx, "task", "2026-10-03.md"), "w", encoding="utf-8").write("- [ ] 1.1 x\n")
        with open(os.path.join(fx, ".claude", "hooks", "stats.py"), "a", encoding="utf-8") as f:
            f.write("\n# touched\n")
        code, out = _run_check("tier1-hitl-stop", fx, {"result": "已完成，請確認。"}, wd)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL HITL 前未改任何 .py", out)
        self.assertIn("stats.py", out)


class RunnerErrorPathTest(unittest.TestCase):
    """契約 row（item 11.1 [邊界]＋claude 缺席）：以假 claude／會拋例外的 check.py 觸發，不呼叫真 claude。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def test_check_script_exception_is_checker_error_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            case = os.path.join(td, "case")
            os.makedirs(case)
            with open(os.path.join(case, "check.py"), "w", encoding="utf-8") as f:
                f.write("raise RuntimeError('boom')\n")
            verdict, out = self.se.run_check(case, td, os.path.join(td, "nonexistent.json"))
        self.assertEqual(verdict, "checker_error")
        self.assertIn("boom", out)
        self.assertEqual(self.se.VERDICT_LABEL["checker_error"], "檢查器錯誤")

    def test_missing_check_script_is_checker_error(self):
        with tempfile.TemporaryDirectory() as td:
            verdict, out = self.se.run_check(td, td, os.path.join(td, "r.json"))
        self.assertEqual(verdict, "checker_error")
        self.assertIn("缺 check.py", out)

    def test_non_json_claude_output_is_unparsable_not_pass(self):
        """PATH 前置一個假 claude（印非 JSON）→ run_claude 回 (None, raw, 「輸出不可解析」)。"""
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "claude")
            with open(fake, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho 'this is not json'\n")
            os.chmod(fake, 0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = td + os.pathsep + old_path
            try:
                data, raw, note = self.se.run_claude(td, "ping", 1.0, 30)
            finally:
                os.environ["PATH"] = old_path
        self.assertIsNone(data)
        self.assertIn("not json", raw)
        self.assertIn("輸出不可解析", note)

    def test_claude_missing_from_path_is_exit_one(self):
        """非 dry-run 且 PATH 無 claude → exit 1 印「找不到 claude CLI」，不建 fixture。"""
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, PATH=td)  # 只有空目錄：claude 不在 PATH
            proc = subprocess.run([sys.executable, RUNNER, "--case", "tier1-routing"],
                                  capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("找不到 claude CLI", proc.stderr)


class BudgetAccountingTest(unittest.TestCase):
    """🟡-1／🟡-2：預算切斷的 session 記 budget_exhausted 不記 FAIL；拿不到成本時保守記滿。"""

    @classmethod
    def setUpClass(cls):
        cls.se = _load_runner()

    def _fake_claude(self, td, body):
        fake = os.path.join(td, "claude")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(fake, 0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = td + os.pathsep + old_path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old_path))

    def test_budget_cut_session_is_budget_exhausted_not_fail(self):
        with tempfile.TemporaryDirectory() as td:
            self._fake_claude(td, "echo '{\"is_error\": true, \"subtype\": \"error_max_budget_usd\", \"num_turns\": 1, \"total_cost_usd\": 0.4}'")
            data, raw, note = self.se.run_claude(td, "ping", 0.4, 30)
        self.assertEqual(note, "budget_exhausted")
        self.assertEqual(self.se.VERDICT_LABEL["budget_exhausted"], "預算切斷（不計行為）")

    def test_min_case_budget_covers_measured_cost(self):
        """門檻須 ≥ 2.0：實測單情境 1.6–2.6 美元，1.0 會開一個必被切斷的 session。"""
        self.assertGreaterEqual(self.se.MIN_CASE_BUDGET_USD, 2.0)

    def test_exit_code_fail_dominates_ceiling(self):
        src = read(RUNNER)
        self.assertIn("if any_fail:\n        return 1\n    return 2 if ceiling_hit else 0", src,
                      "有 FAIL 時 exit 1 須優先於成本上限的 exit 2")

    def test_unknown_cost_is_charged_conservatively(self):
        src = read(RUNNER)
        self.assertIn('rec["cost_usd"] = remaining', src, "拿不到 total_cost_usd 時須以該 session 預算保守記帳")


class CheckerZeroAssertionTest(unittest.TestCase):
    def test_finish_with_no_assertions_is_not_pass(self):
        sys.path.insert(0, EVALS)
        try:
            import importlib
            common = importlib.import_module("_common")
        finally:
            sys.path.pop(0)
        self.assertEqual(common.Checker().finish(), 3)


class VersionControlHygieneTest(unittest.TestCase):
    def test_results_dir_ignored(self):
        self.assertIn("evals/results/", read(GITIGNORE).splitlines())

    def test_this_file_never_runs_claude(self):
        src = read(os.path.abspath(__file__))
        # 允許出現在註解／字串說明；不允許作為 subprocess 的可執行檔
        self.assertNotRegex(src, r"\[\s*['\"]claude['\"]", "本測試檔不得以 subprocess 執行 claude")


if __name__ == "__main__":
    unittest.main()
