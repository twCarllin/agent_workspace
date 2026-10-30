"""test_baseline.py 的端到端測試：在暫存目錄以假測試指令驗證
baseline 建立、新失敗攔截與 failure_log 留痕、非確定性失敗放行、manifest test_command 回退、related 對映。

執行：python3 -m unittest discover -s tests -v
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "test_baseline.py"

# 匯入受測模組的純函式以便直接單元測
sys.path.insert(0, str(SCRIPT.parent))
from test_baseline import build_mine_argv, is_test_file, venv_mismatch  # noqa: E402

# test_a 永遠失敗（既有壞測試，會進 stable_failures）
CMD_STABLE = 'echo "FAILED tests/test_broken.py::test_a"; exit 1'
CMD_NEW_FAILURE = (
    'echo "FAILED tests/test_broken.py::test_a"; '
    'echo "FAILED tests/test_new.py::test_c"; exit 1'
)
# test_d 只在第一次呼叫失敗（非確定性失敗，靠計數檔 m）：
# check 首跑 a+d，重跑只剩 a → d 不可重現 → 放行不擋
CMD_NEW_NONREPRODUCIBLE = (
    "m=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; "
    'echo "FAILED tests/test_broken.py::test_a"; '
    '[ $m -eq 1 ] && echo "FAILED tests/test_d.py::test_d"; exit 1'
)
# __suite__ 重跑確認分支用的計數檔 stub（B1）：m 記錄呼叫次數，控制首跑 vs 重跑的行為差異。
COUNT = "m=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; "
# 首跑整個 suite 崩潰（無可解析輸出）、重跑變乾淨 → row1
CMD_SUITE_THEN_CLEAN = COUNT + "[ $m -eq 1 ] && exit 1; exit 0"
# 首跑、重跑都整個 suite 崩潰（無可解析輸出）→ row2
CMD_SUITE_ALWAYS = COUNT + "exit 1"
# 首跑即可解析出個別失敗，須重跑確認同一 ID
CMD_INDIVIDUAL_FIRST = COUNT + 'echo "FAILED tests/test_broken.py::test_a"; exit 1'
# 首跑整個 suite 崩潰、重跑解析出個別失敗 → row4
CMD_SUITE_THEN_INDIVIDUAL = (
    COUNT + '[ $m -eq 1 ] && exit 1; echo "FAILED tests/test_broken.py::test_a"; exit 1'
)

UNIT_FAIL = "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self): self.fail()\n"
UNIT_OK = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n"
UNITTEST_DISCOVER = "python3 -m unittest discover -s tests"


def kill_escaped(pid_path):
    """清掉逃離行程群組的測試後代。"""
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


class RepoCase(unittest.TestCase):
    """暫存 git repo（含已提交的 .gitignore 與 eval_state.json），供各 e2e 類別共用。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")
        # runner 的已知副作用不是產品輸入；不要用流程目錄掩蓋產品變更。
        (self.dir / ".gitignore").write_text(
            "m\nran\n.venv/\n__pycache__/\n", encoding="utf-8"
        )
        self.git("init", "-q")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "initial")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=self.dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def run_script(self, *args, env=None, script=SCRIPT):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

    def read_baseline(self):
        path = self.dir / "run" / "t.test_baseline.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def read_execution(self):
        path = self.dir / "run" / "t.baseline_execution.json"
        return json.loads(path.read_text(encoding="utf-8"))


class BaselineScriptTest(RepoCase):
    def build_baseline(self, cmd=CMD_STABLE, *extra):
        result = self.run_script("baseline", "--cmd", cmd, *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read_baseline()

    def read_counter(self):
        path = self.dir / "m"
        return int(path.read_text().strip()) if path.exists() else 0

    def test_baseline_confirms_source_and_same_failure_twice(self):
        data = self.build_baseline(CMD_INDIVIDUAL_FIRST)
        self.assertEqual(data["schema"], 2)
        self.assertEqual(data["run_id"], "t")
        self.assertEqual(data["cmd"], CMD_INDIVIDUAL_FIRST)
        self.assertEqual(
            data["source"],
            {"head_sha": self.git("rev-parse", "HEAD"), "clean_product_inputs": True},
        )
        self.assertEqual(data["source_after"], data["source"])
        self.assertEqual(data["head_sha"], data["source"]["head_sha"])
        self.assertRegex(data["environment"], r"^[0-9a-f]{64}$")
        self.assertEqual(data["timeout_seconds"], 300)
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertEqual(self.read_counter(), 2)
        for result in data["observations"]:
            self.assertEqual(result["classification"], "test_failure")
            self.assertEqual(result["returncode"], 1)
            self.assertEqual(result["failures"], data["stable_failures"])
            self.assertIn("FAILED tests/test_broken.py::test_a", result["stdout"])
            self.assertEqual(result["stderr"], "")
            self.assertGreaterEqual(result["duration_seconds"], 0)
        self.assertNotIn("strikes", data)

    def test_baseline_only_intersects_repeated_failure_ids(self):
        data = self.build_baseline(CMD_NEW_NONREPRODUCIBLE)
        self.assertEqual(self.read_counter(), 2)
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertIn("tests/test_d.py::test_d", data["observations"][0]["failures"])
        self.assertNotIn("tests/test_d.py::test_d", data["observations"][1]["failures"])

    def test_check_passes_when_only_known_failures(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_STABLE, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)
        saved = self.read_baseline()["check_observations"][-1]
        self.assertEqual(saved["key"], "s1")
        self.assertEqual(saved["cmd"], CMD_STABLE)
        self.assertEqual(saved["observations"][0]["failures"], ["tests/test_broken.py::test_a"])

    def test_check_blocks_reproducible_new_failure_and_logs(self):
        self.build_baseline()
        for count in (1, 2):
            result = self.run_script(
                "check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1"
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("tests/test_new.py::test_c", result.stderr)
            self.assertEqual(
                self.read_baseline()["failure_log"],
                [{"key": "s1", "tests": ["tests/test_new.py::test_c"]}] * count,
            )

    def test_non_reproducible_new_failure_passes_without_allowlisting(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_NEW_NONREPRODUCIBLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.read_baseline()
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertNotIn("failure_log", data)
        self.assertNotIn("flaky", data)
        self.assertEqual(self.read_counter(), 2)

    def test_check_rejects_legacy_and_tampered_baselines(self):
        trusted = self.build_baseline()
        path = self.dir / "run" / "t.test_baseline.json"
        variants = [
            {
                "run_id": "t",
                "cmd": CMD_STABLE,
                "head_sha": trusted["head_sha"],
                "stable_failures": ["__suite__"],
            },
            dict(trusted, stable_failures=["__suite__"]),
            dict(trusted, stable_failures=["tests/not_confirmed.py::test_x"]),
            dict(
                trusted,
                source_after={"head_sha": "0" * 40, "clean_product_inputs": True},
            ),
            dict(
                trusted,
                observations=[
                    dict(trusted["observations"][0], classification="timeout")
                ],
            ),
            [],
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                path.write_text(json.dumps(variant), encoding="utf-8")
                result = self.run_script("check", "--cmd", "exit 0")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("不可信", result.stderr)
                self.assertNotIn("PASS", result.stdout)

    def test_baseline_warns_on_venv_mismatch_only_for_stable_failures(self):
        (self.dir / ".venv" / "bin").mkdir(parents=True)
        result = self.run_script("baseline", "--cmd", CMD_STABLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".venv/bin", result.stderr)
        self.assertIn("test_command", result.stderr)
        clean = self.run_script("baseline", "--cmd", "exit 0", "--fresh")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertNotIn(".venv/bin", clean.stderr)

    def test_missing_baseline_or_cmd_exits_1(self):
        for name, args, key in (
            ("check 無 baseline", ("check", "--cmd", "exit 0"), "baseline"),
            ("baseline 無 cmd 無 manifest", ("baseline",), "test_command"),
        ):
            with self.subTest(name):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(key, result.stderr)

    def test_cmd_falls_back_to_manifest_test_command(self):
        (self.dir / "run").mkdir()
        (self.dir / "run" / "t.json").write_text(
            json.dumps({"run_id": "t", "test_command": "exit 0"}), encoding="utf-8"
        )
        result = self.run_script("baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_baseline()["cmd"], "exit 0")
        check = self.run_script("check")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_legacy_baseline_is_not_reused_or_upgraded(self):
        (self.dir / "run").mkdir()
        legacy = {
            "run_id": "prev",
            "head_sha": self.git("rev-parse", "HEAD"),
            "cmd": CMD_INDIVIDUAL_FIRST,
            "stable_failures": ["tests/old.py::test_z"],
        }
        path = self.dir / "run" / "prev.test_baseline.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        data = self.build_baseline(CMD_INDIVIDUAL_FIRST)
        self.assertEqual(self.read_counter(), 2)
        self.assertNotIn("reused_from", data)
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertEqual(json.loads(path.read_text()), legacy)

    def test_trusted_reuse_after_product_modification_and_fresh_rejects(self):
        data = self.build_baseline(CMD_INDIVIDUAL_FIRST)
        (self.dir / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
        result = self.run_script(
            "baseline", "--run-id", "next", "--cmd", CMD_INDIVIDUAL_FIRST
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        reused = json.loads((self.dir / "run" / "next.test_baseline.json").read_text())
        self.assertEqual(reused["reused_from"], "t")
        self.assertEqual(reused["observations"], data["observations"])
        self.assertEqual(reused["source"], data["source"])
        self.assertEqual(self.read_counter(), 2)
        fresh = self.run_script("baseline", "--cmd", CMD_INDIVIDUAL_FIRST, "--fresh")
        self.assertEqual(fresh.returncode, 1)
        self.assertIn("已有修改", fresh.stderr)
        self.assertEqual(self.read_counter(), 2)

    def test_no_reuse_when_fresh_head_command_or_environment_differs(self):
        self.build_baseline(CMD_INDIVIDUAL_FIRST)
        fresh = self.build_baseline(CMD_INDIVIDUAL_FIRST, "--fresh")  # --fresh 強制重建
        self.assertNotIn("reused_from", fresh)
        self.assertEqual(self.read_counter(), 4)
        self.git("commit", "--allow-empty", "-q", "-m", "next")
        rebuilt = self.build_baseline(CMD_INDIVIDUAL_FIRST)
        self.assertNotIn("reused_from", rebuilt)
        self.assertEqual(self.read_counter(), 6)
        command = self.build_baseline("touch ran; exit 0")
        self.assertTrue((self.dir / "ran").exists())
        self.assertNotIn("reused_from", command)
        environment = dict(os.environ, BASELINE_TEST_CHANGE="changed")
        check = self.run_script("check", "--cmd", "exit 0", env=environment)
        self.assertEqual(check.returncode, 1)
        self.assertIn("環境", check.stderr)

    def test_dirty_product_rejected_without_changing_user_files(self):
        product = self.dir / "product a$z.py"
        product.write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", str(product))
        self.git("commit", "-q", "-m", "product")
        for kind in ("unstaged", "staged", "untracked", "deleted", "renamed"):
            with self.subTest(kind=kind):
                if kind in ("unstaged", "staged"):
                    product.write_text("VALUE = 2\n", encoding="utf-8")
                    if kind == "staged":
                        self.git("add", str(product))
                elif kind == "untracked":
                    (self.dir / "new $ file.py").write_text("new", encoding="utf-8")
                elif kind == "deleted":
                    product.unlink()
                else:
                    self.git("mv", "product a$z.py", "renamed.py")
                before = self.git("status", "--porcelain")
                result = self.run_script("baseline", "--cmd", "touch ran; exit 0")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("已有修改", result.stderr)
                self.assertFalse((self.dir / "ran").exists())
                self.assertFalse((self.dir / "run" / "t.test_baseline.json").exists())
                self.assertEqual(self.git("status", "--porcelain"), before)
                # 只還原本案例的暫存 repo，受測工具不得還原使用者現場。
                self.git("reset", "--hard", "HEAD")
                (self.dir / "new $ file.py").unlink(missing_ok=True)

    def test_no_head_rejects_baseline(self):
        with tempfile.TemporaryDirectory() as empty:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "baseline", "--run-id", "t", "--cmd", "exit 0"],
                cwd=empty,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("無 HEAD", result.stderr)
            self.assertFalse((Path(empty) / "run").exists())

    def test_drift_during_run_does_not_publish_baseline(self):
        for name, cmd in (
            ("product", "echo changed > product.py; exit 0"),
            (
                "head",
                "git -c user.email=t@t -c user.name=t commit --allow-empty -q -m drift; exit 0",
            ),
        ):
            with self.subTest(drift=name):
                result = self.run_script("baseline", "--cmd", cmd)
                self.assertEqual(result.returncode, 1)
                self.assertFalse((self.dir / "run" / "t.test_baseline.json").exists())
                if name == "product":
                    self.assertEqual((self.dir / "product.py").read_text(), "changed\n")
                    (self.dir / "product.py").unlink()
                else:
                    self.assertIn("漂移", result.stderr)

    def test_execution_errors_never_become_baseline_or_pass_check(self):
        for cmd in (
            CMD_SUITE_ALWAYS,
            CMD_SUITE_THEN_CLEAN,
            CMD_SUITE_THEN_INDIVIDUAL,
            "exit 124",
        ):
            with self.subTest(cmd=cmd):
                (self.dir / "m").unlink(missing_ok=True)
                result = self.run_script("baseline", "--cmd", cmd)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertFalse((self.dir / "run" / "t.test_baseline.json").exists())
                evidence = self.read_execution()
                self.assertEqual(evidence["cmd"], cmd)
                self.assertEqual(evidence["run_id"], "t")
                self.assertEqual(evidence["timeout_seconds"], 300)
                self.assertEqual(
                    evidence["observations"][0]["classification"],
                    "timeout" if cmd == "exit 124" else "execution_error",
                )
                self.assertEqual(evidence["observations"][0]["failures"], [])
                self.assertEqual(self.read_counter(), 1 if "m=" in cmd else 0)
        self.build_baseline("exit 0")
        result = self.run_script("check", "--cmd", "exit 124")
        self.assertEqual(result.returncode, 2)
        self.assertIn("timeout", result.stderr)
        last = self.read_baseline()["check_observations"][-1]
        self.assertEqual(last["observations"][0]["classification"], "timeout")

    def test_unittest_failures_have_distinct_real_ids_on_both_entrypoints(self):
        test_file = self.dir / "test_sample.py"
        test_file.write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            "    def test_a(self): self.fail()\n"
            "    def test_b(self): pass\n",
            encoding="utf-8",
        )
        self.git("add", "test_sample.py")
        self.git("commit", "-q", "-m", "test")
        cmd = "python3 -m unittest test_sample"
        data = self.build_baseline(cmd)
        self.assertEqual(data["stable_failures"], ["test_sample.T.test_a"])
        test_file.write_text(
            test_file.read_text()
            .replace("test_a(self): self.fail()", "test_a(self): pass")
            .replace("test_b(self): pass", "test_b(self): self.fail()"),
            encoding="utf-8",
        )
        for bytecode in (self.dir / "__pycache__").glob("*"):
            bytecode.unlink()
        common = SCRIPT.parents[2] / ".agent-flow" / "scripts" / "test_baseline.py"
        for entry in (SCRIPT, common):
            with self.subTest(entry=entry):
                result = self.run_script("check", "--cmd", cmd, script=entry)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("test_sample.T.test_b", result.stderr)
                self.assertNotIn("(failures=1)", self.read_baseline()["stable_failures"])

    def test_timeout_cleans_child_and_preserves_external_process(self):
        external = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            cmd = "sleep 10 & echo $! > run/child.log; wait"
            (self.dir / "run").mkdir()
            result = self.run_script("baseline", "--cmd", cmd, "--timeout", "0.15")
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("timeout", result.stderr)
            child = int((self.dir / "run" / "child.log").read_text())
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True
            )
            self.assertTrue(
                not state.stdout.strip() or state.stdout.strip().startswith("Z"),
                state.stdout,
            )
            self.assertIsNone(external.poll())
            evidence = self.read_execution()
            observation = evidence["observations"][0]
            self.assertEqual(evidence["timeout_seconds"], 0.15)
            self.assertEqual(observation["classification"], "timeout")
            self.assertLess(observation["returncode"], 0)
            self.assertEqual(observation["failures"], [])
        finally:
            external.kill()
            external.wait()

    def test_timeout_returns_when_escaped_descendant_holds_output_pipe(self):
        (self.dir / "run").mkdir()
        pid_path = self.dir / "run" / "escaped.log"
        code = (
            "import os, time; pid = os.fork(); "
            "os.setsid() if pid == 0 else None; "
            "open('run/escaped.log', 'w').write(str(os.getpid())) if pid == 0 else None; "
            "print('escaped-ready', flush=True) if pid == 0 else None; "
            "time.sleep(5)"
        )
        cmd = shlex.join([sys.executable, "-c", code])
        start = time.monotonic()
        try:
            result = self.run_script("baseline", "--cmd", cmd, "--timeout", "0.4")
            duration = time.monotonic() - start
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertLess(duration, 2, "逃離群組的 pipe 不可延長到後代自行退出")
            self.assertTrue(pid_path.exists(), "逃離群組的後代必須確實啟動")
            os.kill(int(pid_path.read_text()), 0)
            observation = self.read_execution()["observations"][0]
            self.assertEqual(observation["classification"], "timeout")
            self.assertIn("escaped-ready", observation["stdout"])
            self.assertLess(observation["duration_seconds"], 2)
        finally:
            kill_escaped(pid_path)

    def test_mine_timeout_blocks_even_when_parent_exits_zero(self):
        (self.dir / "run").mkdir()
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "test_fixture.py").write_text("", encoding="utf-8")
        pid_path = self.dir / "run" / "escaped.log"
        code = (
            "import os, time; pid = os.fork(); "
            "os._exit(0) if pid else None; os.setsid(); "
            "open('run/escaped.log', 'w').write(str(os.getpid())); "
            "print('escaped-ready', flush=True); time.sleep(5)"
        )
        try:
            start = time.monotonic()
            result = self.run_script(
                "mine", "--cmd", shlex.join([sys.executable, "-c", code]), "--timeout", "0.4"
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("timeout", result.stderr)
            self.assertNotIn("mine PASS", result.stdout)
            self.assertLess(time.monotonic() - start, 2)
            self.assertTrue(pid_path.exists(), "runner 子程序必須確實啟動")
            os.kill(int(pid_path.read_text()), 0)
        finally:
            kill_escaped(pid_path)

    def test_timeout_option_is_bounded(self):
        for value in ("0", "-1", "86401", "nan", "inf"):
            with self.subTest(value=value):
                result = self.run_script(
                    "baseline", "--cmd", "exit 0", "--timeout", value
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("timeout", result.stderr)

    def test_related_maps_by_name_and_content(self):
        (self.dir / "src").mkdir()
        (self.dir / "tests").mkdir()
        (self.dir / "src" / "foo.py").write_text("def foo(): pass\n", encoding="utf-8")
        for name, body in (
            ("test_foo.py", "from src.foo import foo\n"),
            ("test_service.py", "import src.foo\n"),
            ("test_unrelated.py", "def test_x(): pass\n"),
        ):
            (self.dir / "tests" / name).write_text(body, encoding="utf-8")
        result = self.run_script("related", "--files", "src/foo.py")
        paths = set(result.stdout.split())
        self.assertIn("tests/test_foo.py", paths)
        self.assertIn("tests/test_service.py", paths)
        self.assertNotIn("tests/test_unrelated.py", paths)


class BuildMineCmdTest(unittest.TestCase):
    """build_mine_argv／is_test_file 純函式的單元測試（無 subprocess）。"""

    def test_build_mine_argv_by_runner(self):
        files = ["tests/test_foo.py", "tests/test_bar.py"]
        for name, cmd, expected in (
            ("pytest 直接附路徑", "pytest -q", ["pytest", "-q", *files]),
            (
                "unittest discover 轉 module",
                "python3 -m unittest discover -s tests",
                ["python3", "-m", "unittest", "tests.test_foo", "tests.test_bar"],
            ),
            (
                "unittest 不含 discover 也轉 module",
                "python3 -m unittest",
                ["python3", "-m", "unittest", "tests.test_foo", "tests.test_bar"],
            ),
        ):
            with self.subTest(name):
                self.assertEqual(build_mine_argv(cmd, files), expected)

    def test_is_test_file_classification(self):
        # 2026-09-22 bugfix：點開頭目錄下的 test_*.py 被誤判為測試模組
        # （.claude/hooks/test_*.py 轉出 `.claude.hooks.test_baseline`，unittest 報 Empty module name）；
        # L8 教訓：spec/ 是 eval-flow 產出物目錄，曾被當測試檔餵 pytest。
        for path, expected in (
            ("tests/test_foo.py", True),
            ("test_bar.py", True),
            ("tests/test_stats.py", True),
            ("src/foo_test.py", True),
            ("a/b/tests/helper.py", True),
            ("src/foo.test.ts", True),  # 多框架慣例不得因副檔名守門而誤傷
            ("src/bar.spec.js", True),
            ("__tests__/baz.jsx", True),
            ("src/foo.py", False),
            (".venv/tests/test_foo.py", False),  # skip dirs
            (".claude/hooks/test_baseline.py", False),
            (".claude/hooks/test_lint.py", False),
            (".config/test_anything.py", False),
            ("spec/2026-07-21-phase-c.md", False),
            ("spec/bootstrap.md", False),
            ("tests/fixture.json", False),  # 測試目錄裡的 fixture／文件不餵 runner
            ("tests/README.md", False),
            ("test_plan.md", False),  # TEST_FILE_RE 前綴命中但非 code 檔
        ):
            with self.subTest(path=path):
                self.assertEqual(is_test_file(path), expected)

    def test_build_mine_argv_never_emits_empty_module_segment(self):
        """坐實後果面：經 is_test_file 過濾後的檔案，轉出的 module 路徑無空段（R-004：斷言轉換後內容）。"""
        candidates = [
            ".claude/hooks/test_baseline.py",
            "tests/test_stats.py",
            "src/foo_test.py",
        ]
        kept = [f for f in candidates if is_test_file(f)]
        argv = build_mine_argv("python3 -m unittest discover -s tests", kept)
        modules = argv[3:]
        self.assertNotIn(".claude.hooks.test_baseline", modules)
        for m in modules:
            self.assertFalse(m.startswith(".") or ".." in m, f"module 路徑含空段：{m!r}")


class VenvMismatchTest(unittest.TestCase):
    """venv_mismatch 純函式：偵測「有虛擬環境目錄但 cmd 未用它」的錯配。"""

    def test_venv_mismatch(self):
        for name, venv_dir, cmd, expected in (
            ("dotvenv 存在、cmd 未用 → 回傳名稱", ".venv", "python3 -m pytest -q", ".venv"),
            ("dotvenv 存在、cmd 已用", ".venv", ".venv/bin/python3 -m pytest", None),
            ("無 venv 目錄", None, "python3 -m pytest", None),
            ("一般 venv 目錄", "venv", "pytest -q", "venv"),
        ):
            with self.subTest(name), tempfile.TemporaryDirectory() as root:
                if venv_dir:
                    os.makedirs(os.path.join(root, venv_dir, "bin"))
                self.assertEqual(venv_mismatch(cmd, root=root), expected)


class MineSubcommandTest(RepoCase):
    """mine 子命令的 subprocess 整合測試（需 git repo）。"""

    def write_test(self, name, body):
        (self.dir / "tests").mkdir(exist_ok=True)
        (self.dir / "tests" / name).write_text(body, encoding="utf-8")

    def write_baseline(self):
        (self.dir / "run").mkdir(exist_ok=True)
        data = {"run_id": "t", "cmd": "exit 0", "head_sha": "abc", "stable_failures": []}
        (self.dir / "run" / "t.test_baseline.json").write_text(json.dumps(data))

    def test_mine_with_test_file_runs_only_that_file(self):
        """untracked 測試檔存在時，mine 只跑該測試檔（runner 收到的路徑正確）。"""
        self.write_test("test_foo.py", "")
        (self.dir / "main.py").write_text("", encoding="utf-8")  # 非測試檔不得被餵給 runner
        sentinel = self.dir / "ran.txt"
        runner = self.dir / "fake_runner.sh"
        runner.write_text(f'#!/bin/sh\necho "$@" > {sentinel}\n', encoding="utf-8")
        runner.chmod(0o755)
        result = self.run_script("mine", "--cmd", str(runner))
        self.assertEqual(result.returncode, 0, result.stderr)
        got = sentinel.read_text(encoding="utf-8").split()
        self.assertEqual(got, ["tests/test_foo.py"])

    def test_mine_no_test_files_exits_0(self):
        """變更中無測試檔 → exit 0。"""
        (self.dir / "src").mkdir()
        (self.dir / "src" / "foo.py").write_text("", encoding="utf-8")
        result = self.run_script("mine", "--cmd", "exit 0")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mine_failure_exits_2_and_strike_key_does_not_count(self):
        """D1／strike 已移除：失敗 → exit 2；有 --strike-key ＋既有 baseline 也不寫計數、不落 mine_log。"""
        self.write_test("test_foo.py", UNIT_FAIL)
        self.write_baseline()
        result = self.run_script("mine", "--cmd", UNITTEST_DISCOVER, "--strike-key", "sk1")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("strikes", self.read_baseline())
        self.assertFalse((self.dir / "run" / "t.mine_log.json").exists())

    def test_mine_pass_creates_no_baseline_or_log_and_handles_space_filename(self):
        """通過：不建立 baseline／mine_log；discover 型 cmd 不把 discover 傳給 unittest；
        含空白的測試檔名不造成 shell 注入、能真實執行。"""
        self.write_test("test_a b.py", UNIT_OK)
        result = self.run_script("mine", "--cmd", UNITTEST_DISCOVER, "--strike-key", "sk1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)
        self.assertNotIn("discover", result.stderr)
        self.assertFalse((self.dir / "run" / "t.test_baseline.json").exists())
        self.assertFalse((self.dir / "run" / "t.mine_log.json").exists())


class GitChangedFilesTest(RepoCase):
    """git_changed_files 的整合測試（需真實 git repo；R-003：rename／deleted／空白／特殊字元）。"""

    def git_changed(self):
        """在 self.dir 內呼叫 git_changed_files（透過子程序以免 cwd 干擾）。"""
        code = (
            f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); "
            "from test_baseline import git_changed_files; "
            "print('\\n'.join(git_changed_files()))"
        )
        p = subprocess.run(
            [sys.executable, "-c", code], cwd=self.dir, capture_output=True, text=True
        )
        return [l for l in p.stdout.splitlines() if l]

    def test_rename_takes_new_path_and_deleted_excluded(self):
        for name in ("old.py", "del.py"):
            (self.dir / name).write_text("x", encoding="utf-8")
        self.git("add", "old.py", "del.py")
        self.git("commit", "-q", "-m", "add")
        self.git("mv", "old.py", "new.py")
        self.git("rm", "-q", "del.py")
        files = self.git_changed()
        self.assertIn("new.py", files)
        self.assertNotIn("old.py", files)
        self.assertNotIn("del.py", files)

    def test_untracked_names_parsed_verbatim(self):
        """空白（不帶引號）、$（不被 shell 展開）、未追蹤目錄展開為子檔案。"""
        (self.dir / "test_a b.py").write_text("", encoding="utf-8")
        (self.dir / "test_$x.py").write_text("", encoding="utf-8")
        (self.dir / "newpkg").mkdir()
        for name in ("test_one.py", "test_two.py"):
            (self.dir / "newpkg" / name).write_text("", encoding="utf-8")
        files = self.git_changed()
        for expected in (
            "test_a b.py",
            "test_$x.py",
            "newpkg/test_one.py",
            "newpkg/test_two.py",
        ):
            with self.subTest(expected):
                self.assertIn(expected, files)


if __name__ == "__main__":
    unittest.main()
