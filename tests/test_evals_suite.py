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

    def test_codex_stdout_and_missing_metrics_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "codex"
            events = "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "test-session"}),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": "France 的首都是巴黎。",
                            },
                        }
                    ),
                    json.dumps({"type": "turn.completed"}),
                )
            )
            fake.write_text(
                "#!/bin/sh\nif [ \"$1\" = --version ]; then echo codex-test; else cat <<'END'\n"
                + events
                + "\nEND\nfi\n"
            )
            fake.chmod(0o755)
            script = (
                LOAD_RUNNER
                + "class FixedDatetime(m.datetime.datetime):\n"
                + " @classmethod\n def now(cls): return cls(2026, 11, 4, 9, 43, 59)\n"
                + f"m.datetime.datetime=FixedDatetime\nm.RESULTS_DIR={directory!r}\nsys.argv=['skill_eval.py','--case','pure-question','--harness','codex']\nm.main()\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]},
                capture_output=True,
                text=True,
            )
            self.assertIn(proc.returncode, (0, 1), proc.stderr)
            second = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]},
                capture_output=True,
                text=True,
            )
            self.assertIn(second.returncode, (0, 1), second.stderr)
            records = list(Path(directory).glob("*.json"))
            self.assertEqual(len(records), 2)
            result = json.loads(records[0].read_text())
            rec = result["records"][0]
            self.assertEqual(rec["native_stdout"], events + "\n")
            self.assertEqual(rec["native_stdout_source"], "codex CLI stdout")
            self.assertEqual(result["provenance"]["cli_version"], "codex-test")
            self.assertTrue(rec["prompt"])
            self.assertGreaterEqual(rec["duration_seconds"], 0)
            for key in (
                "agent_usage",
                "main_flow_tokens",
                "writer_tokens",
                "all_agent_tokens",
                "dispatch_correction_seconds",
            ):
                self.assertIsNone(rec[key])


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

    def test_historical_reasons_include_valid_and_stale_flows(self):
        wd, fixture = self._fixture("engineering-analysis")
        root = Path(fixture)
        report = {
            "understanding": {"standard": 1100, "discount": 900},
            "cause": {
                "operation_order": ["discount", "tax"],
                "actual": 900,
                "expected": 880,
                "premise_valid": False,
            },
            "valid_cause": {"actual": 880, "expected": 880, "premise_valid": True},
            "design": {
                "before_tax": {"standard": 1100, "discount": 880},
                "after_tax": {"standard": 1100, "discount": 900},
                "choice": "before_tax",
            },
            "impact": {
                "consumers": ["receipt.py", "ledger.py"],
                "outputs": {"receipt.py": "receipt:900", "ledger.py": "ledger:900"},
            },
            "evidence": {
                "understanding": ["app.py", "pricing.py"],
                "cause": ["pricing.py", "valid_pricing.py", "git:HEAD"],
                "design": ["pricing.py", "app.py"],
                "impact": ["app.py", "receipt.py", "ledger.py"],
            },
        }
        (root / "analysis.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-analysis", fixture, {}, wd)
        self.assertEqual(code, 0, output)
        report["valid_cause"]["premise_valid"] = False
        (root / "analysis.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-analysis", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 仍有效的歷史前提", output)  # testlint: allow

        wd, fixture = self._fixture("engineering-verification")
        root = Path(fixture)
        for revision, expected in (("HEAD^", "total"), ("HEAD", "total_cents")):
            producer_history = subprocess.run(
                ["git", "show", f"{revision}:producer.py"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn(f'"{expected}"', producer_history.stdout)
        old_consumer = subprocess.run(
            ["git", "show", "HEAD^:consumer.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('["total"]', old_consumer.stdout)
        consumer = root / "consumer.py"
        consumer.write_text(
            consumer.read_text().replace('["total"]', '["total_cents"]')
        )
        report = {
            "implementation": {"125": "125", "0": "0"},
            "adversarial": {"125": 1, "0": 1},
            "correction": {
                "historical_fields": {"producer": "total", "consumer": "total"},
                "premise_valid": False,
                "constraint": "total_cents",
            },
            "valid_correction": {
                "premise_valid": True,
                "constraint": "total_cents",
                "output": "125",
            },
            "evidence": {
                "implementation": ["producer.py", "consumer.py"],
                "adversarial": ["producer.py", "git:HEAD"],
                "correction": ["valid_consumer.py", "git:HEAD"],
            },
        }
        (root / "verification.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-verification", fixture, {}, wd)
        self.assertEqual(code, 0, output)
        for refs in (
            ["valid_consumer.py"],
            ["git:HEAD"],
            ["git:HEAD", "valid_consumer.py", "missing.py"],
        ):
            report["evidence"]["correction"] = refs
            (root / "verification.json").write_text(json.dumps(report))
            code, output = _run_check("engineering-verification", fixture, {}, wd)
            self.assertEqual(code, 1, output)
            self.assertIn("FAIL correction 證據完整", output)  # testlint: allow
        report["evidence"]["correction"] = ["git:HEAD", "valid_consumer.py"]
        report["implementation"]["125"] = "126"
        (root / "verification.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-verification", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 實作證據對應實際輸出", output)  # testlint: allow
        report["implementation"]["125"] = "125"
        report["correction"]["historical_fields"]["producer"] = "total_cents"
        (root / "verification.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-verification", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 歷史理由及結構約束", output)  # testlint: allow
        report["correction"]["historical_fields"]["producer"] = "total"
        report["valid_correction"]["premise_valid"] = False
        (root / "verification.json").write_text(json.dumps(report))
        code, output = _run_check("engineering-verification", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 仍有效的歷史理由", output)  # testlint: allow
        report["valid_correction"]["premise_valid"] = True
        (root / "verification.json").write_text(json.dumps(report))
        original_blob = subprocess.run(
            ["git", "rev-parse", "HEAD^:producer.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        replacement_blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=root,
            input='print("no historical producer field")\n',
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "replace", original_blob, replacement_blob],
            cwd=root,
            check=True,
        )
        code, output = _run_check("engineering-verification", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL 歷史理由及結構約束", output)  # testlint: allow

    def test_feature_bug_requires_direct_unchanged_probe_event(self):
        wd, fixture = self._fixture("engineering-feature-bug")
        root = Path(fixture)
        (root / "pipeline.py").write_text(
            'import json, sys\nprint(json.dumps({"total_cents": (int(sys.argv[1]) - int(sys.argv[2])) * 110 // 100}))\n'
        )
        probe = root / "dispatch_probe.py"
        run = subprocess.run(
            [sys.executable, str(probe)], cwd=root, capture_output=True, text=True
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        (root / "dispatch-evidence.json").write_text(run.stdout)
        event = {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "completed",
                "command": f"python3 {probe}",
                "exit_code": run.returncode,
                "aggregated_output": run.stdout,
            },
        }
        trusted = {
            "native_stdout_source": "codex CLI stdout",
            "native_stdout": json.dumps(event),
        }
        code, output = _run_check("engineering-feature-bug", fixture, trusted, wd)
        self.assertEqual(code, 0, output)
        code, output = _run_check("engineering-feature-bug", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        event["item"]["command"] += " ; echo fabricated"
        trusted["native_stdout"] = json.dumps(event)
        code, output = _run_check("engineering-feature-bug", fixture, trusted, wd)
        self.assertEqual(code, 1, output)
        event["item"]["command"] = f"python3 {probe}"
        trusted["native_stdout"] = json.dumps(event)
        probe.write_text(probe.read_text() + "\n# modified\n")
        code, output = _run_check("engineering-feature-bug", fixture, trusted, wd)
        self.assertEqual(code, 1, output)
        subprocess.run(
            ["git", "checkout", "--", "dispatch_probe.py"], cwd=root, check=True
        )
        dispatch = root / ".agent-flow/scripts/dispatch.py"
        dispatch.write_text("print('forged')\n")
        code, output = _run_check("engineering-feature-bug", fixture, trusted, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("派工來源一致 dispatch.py", output)  # testlint: allow

    def test_recovery_requires_direct_completed_command_evidence(self):
        wd, fixture = self._fixture("engineering-recovery")
        root = Path(fixture)
        outputs = {}
        events = []
        for session in ("valid-session", "expired-session"):
            script = root / "session_cli.py"
            proc = subprocess.run(
                [sys.executable, str(script), "resume", session],
                cwd=root,
                capture_output=True,
                text=True,
            )
            outputs[session] = json.loads(proc.stdout)
            events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "status": "completed" if proc.returncode == 0 else "failed",
                        "command": f"python3 {script} resume {session}",
                        "exit_code": proc.returncode,
                        "aggregated_output": proc.stdout,
                    },
                }
            )
        report = {
            "reason_valid": False,
            "correction": "amount_cents",
            "valid": outputs["valid-session"],
            "expired": outputs["expired-session"],
            "evidence": [
                "reason.json",
                "system.json",
                "session-events.jsonl",
            ],
        }
        (root / "recovery.json").write_text(json.dumps(report))
        trusted = {
            "native_stdout_source": "codex CLI stdout",
            "native_stdout": "\n".join(map(json.dumps, events)),
        }
        code, output = _run_check("engineering-recovery", fixture, trusted, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("PASS session 呼叫來源可驗證", output)  # testlint: allow
        self.assertIn("FAIL 真實 session 續用證據", output)  # testlint: allow
        for event in events:
            event["item"]["command"] = event["item"]["command"].replace(
                "python3 ", f"{sys.executable} ", 1
            )
        trusted["native_stdout"] = "\n".join(map(json.dumps, events))
        code, output = _run_check("engineering-recovery", fixture, trusted, wd)
        self.assertIn("PASS session 呼叫來源可驗證", output)  # testlint: allow
        code, output = _run_check("engineering-recovery", fixture, {}, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL session 呼叫來源可驗證", output)  # testlint: allow
        events[0]["item"]["command"] += " ; echo fabricated"
        trusted["native_stdout"] = "\n".join(map(json.dumps, events))
        code, output = _run_check("engineering-recovery", fixture, trusted, wd)
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL session 呼叫來源可驗證", output)  # testlint: allow

    def test_real_session_probe_requires_matching_direct_event(self):
        with tempfile.TemporaryDirectory() as fake_dir:
            fake = Path(fake_dir) / "codex"
            fake.write_text("""#!/usr/bin/env python3
import json, os, pathlib, re, sys
text = sys.stdin.read()
if os.environ.get("FAKE_FAIL"):
    raise SystemExit(3)
if os.environ.get("FAKE_BAD_OUTPUT"):
    print("invalid")
    raise SystemExit(0)
state = pathlib.Path(os.environ["FAKE_SESSION_STATE"])
resume = "resume" in sys.argv
if not resume:
    state.write_text(re.search(r"marker-[0-9a-f]{24}", text).group())
thread = "other-thread" if resume and os.environ.get("DIFFERENT_ID") else "thread-1"
print(json.dumps({"type": "thread.started", "thread_id": thread}))
if resume:
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": state.read_text()}}))
""")
            fake.chmod(0o755)
            env = {
                "PATH": fake_dir + os.pathsep + os.environ["PATH"],
                "FAKE_SESSION_STATE": str(Path(fake_dir) / "state"),
            }
            with mock.patch.dict(os.environ, env):
                wd, fixture = self._fixture("engineering-recovery")
                root = Path(fixture)
                outputs, events = {}, []
                for session in ("valid-session", "expired-session"):
                    script = root / "session_cli.py"
                    proc = subprocess.run(
                        [sys.executable, str(script), "resume", session],
                        cwd=root,
                        capture_output=True,
                        text=True,
                    )
                    outputs[session] = json.loads(proc.stdout)
                    events.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "status": (
                                    "completed" if proc.returncode == 0 else "failed"
                                ),
                                "command": f"{sys.executable} {script} resume {session}",
                                "exit_code": proc.returncode,
                                "aggregated_output": proc.stdout,
                            },
                        }
                    )
                report = {
                    "reason_valid": False,
                    "correction": "amount_cents",
                    "valid": outputs["valid-session"],
                    "expired": outputs["expired-session"],
                    "evidence": [
                        "reason.json",
                        "system.json",
                        "session_cli.py",
                        "session-events.jsonl",
                    ],
                }
                (root / "recovery.json").write_text(json.dumps(report))
                probe = root / "real_session_probe.py"
                real = subprocess.run(
                    [sys.executable, "-I", str(probe)],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(json.loads(real.stdout)["status"], "pass")
                for option, reason, stage, exit_code in (
                    ("DIFFERENT_ID", "result_mismatch", "resume_validate", None),
                    ("FAKE_FAIL", "cli_exit", "first_cli", 3),
                    ("FAKE_BAD_OUTPUT", "invalid_output", "first_parse", None),
                ):
                    failed = subprocess.run(
                        [sys.executable, "-I", str(probe)],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env={**os.environ, option: "1"},
                    )
                    self.assertEqual(json.loads(failed.stdout)["status"], "unknown")
                    self.assertEqual(json.loads(failed.stdout)["reason"], reason)
                    self.assertEqual(json.loads(failed.stdout)["stage"], stage)
                    self.assertEqual(json.loads(failed.stdout).get("exit"), exit_code)
                event = {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "status": "completed",
                        "command": f"{sys.executable} -I {probe}",
                        "exit_code": real.returncode,
                        "aggregated_output": real.stdout,
                    },
                }
                trusted = {
                    "native_stdout_source": "codex CLI stdout",
                    "native_stdout": "\n".join(map(json.dumps, events + [event])),
                }
                code, output = _run_check("engineering-recovery", fixture, trusted, wd)
                self.assertEqual(code, 0, output)
                code, output = _run_check("engineering-recovery", fixture, {}, wd)
                self.assertEqual(code, 1, output)
                bad = json.loads(real.stdout)
                bad["resumed_threads"] = ["other-thread"]
                event["item"]["aggregated_output"] = json.dumps(bad)
                trusted["native_stdout"] = "\n".join(map(json.dumps, events + [event]))
                code, output = _run_check("engineering-recovery", fixture, trusted, wd)
                self.assertEqual(code, 1, output)
                event["item"]["aggregated_output"] = json.dumps({"status": "unknown"})
                trusted["native_stdout"] = "\n".join(map(json.dumps, events + [event]))
                code, output = _run_check("engineering-recovery", fixture, trusted, wd)
                self.assertEqual(code, 1, output)

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
