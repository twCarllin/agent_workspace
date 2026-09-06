"""test_baseline.py 的端到端測試：在暫存目錄以假測試指令驗證
baseline 建立、新失敗攔截與 failure_log 留痕、非確定性失敗放行、manifest test_command 回退、related 對映。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "test_baseline.py"

# 匯入受測模組的純函式以便直接單元測
sys.path.insert(0, str(SCRIPT.parent))
from test_baseline import build_mine_argv, is_test_file  # noqa: E402

# test_a 永遠失敗（既有壞測試，會進 stable_failures）
CMD_STABLE = (
    'echo "FAILED tests/test_broken.py::test_a"; exit 1'
)
CMD_NEW_FAILURE = (
    'echo "FAILED tests/test_broken.py::test_a"; '
    'echo "FAILED tests/test_new.py::test_c"; exit 1'
)
# test_d 只在第一次呼叫失敗（非確定性失敗，靠計數檔 m）：
# check 首跑 a+d，重跑只剩 a → d 不可重現 → 放行不擋
CMD_NEW_NONREPRODUCIBLE = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; '
    'echo "FAILED tests/test_broken.py::test_a"; '
    '[ $m -eq 1 ] && echo "FAILED tests/test_d.py::test_d"; exit 1'
)
# __suite__ 重跑確認分支用的計數檔 stub（B1）：m 記錄呼叫次數，控制首跑 vs 重跑的行為差異。
# 首跑整個 suite 崩潰（無可解析輸出）、重跑變乾淨 → row1
CMD_SUITE_THEN_CLEAN = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; '
    '[ $m -eq 1 ] && exit 1; exit 0'
)
# 首跑、重跑都整個 suite 崩潰（無可解析輸出）→ row2
CMD_SUITE_ALWAYS = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; exit 1'
)
# 首跑即可解析出個別失敗（非 __suite__）→ row3，不應重跑
CMD_INDIVIDUAL_FIRST = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; '
    'echo "FAILED tests/test_broken.py::test_a"; exit 1'
)
# 首跑整個 suite 崩潰、重跑解析出個別失敗 → row4
CMD_SUITE_THEN_INDIVIDUAL = (
    'm=$(cat m 2>/dev/null || echo 0); m=$((m+1)); echo $m > m; '
    '[ $m -eq 1 ] && exit 1; '
    'echo "FAILED tests/test_broken.py::test_a"; exit 1'
)


class BaselineScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.dir, capture_output=True, text=True,
        )

    def read_baseline(self):
        return json.loads((self.dir / "run" / "t.test_baseline.json").read_text(encoding="utf-8"))

    def build_baseline(self):
        result = self.run_script("baseline", "--cmd", CMD_STABLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read_baseline()

    def read_counter(self):
        """讀計數檔 stub 的呼叫次數（== 全套實際執行次數）。"""
        p = self.dir / "m"
        return int(p.read_text().strip()) if p.exists() else 0

    def test_baseline_records_all_failures_as_stable(self):
        data = self.build_baseline()
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertNotIn("flaky", data)  # 單次跑：不再產生 flaky 名單
        self.assertNotIn("strikes", data)

    def test_check_passes_when_only_known_failures(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_STABLE, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_check_blocks_reproducible_new_failure_and_logs(self):
        self.build_baseline()
        first = self.run_script("check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1")
        self.assertEqual(first.returncode, 2)
        self.assertIn("tests/test_new.py::test_c", first.stderr)
        self.assertIn("回報使用者裁決", first.stderr)
        self.assertNotIn("第 1 次", first.stderr)  # 無 strike 計數
        log = self.read_baseline()["failure_log"]
        self.assertEqual(log, [{"key": "s1", "tests": ["tests/test_new.py::test_c"]}])

        # failure_log 累積留痕：第二次再 append 一筆（人是計數器，script 不設上限）
        second = self.run_script("check", "--cmd", CMD_NEW_FAILURE, "--strike-key", "s1")
        self.assertEqual(second.returncode, 2)
        self.assertNotIn("2 次上限", second.stderr)
        self.assertEqual(len(self.read_baseline()["failure_log"]), 2)

    def test_non_reproducible_new_failure_passes_without_persisting(self):
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_NEW_NONREPRODUCIBLE, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("非確定性失敗", result.stdout)
        data = self.read_baseline()
        self.assertNotIn("flaky", data)  # 非確定性失敗不持久化
        self.assertNotIn("failure_log", data)

    def write_baseline_with_stable(self, stable_failures):
        """直接寫 baseline JSON（仿 write_prev_baseline 慣例），供 B2 測試控制 known 內容。"""
        (self.dir / "run").mkdir(exist_ok=True)
        (self.dir / "run" / "t.test_baseline.json").write_text(
            json.dumps({
                "run_id": "t", "cmd": "x", "head_sha": None,
                "stable_failures": stable_failures,
            }), encoding="utf-8",
        )

    def test_check_warns_when_baseline_blind_to_suite_and_no_new_failure(self):
        """row1: baseline stable_failures 含 __suite__＋本次無新失敗 → stderr 含失明警告、exit 0。"""
        self.write_baseline_with_stable(["__suite__"])
        result = self.run_script("check", "--cmd", "exit 0", "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("失明", result.stderr)

    def test_check_no_b2_warning_when_baseline_has_no_suite_sentinel(self):
        """row2: baseline 不含 __suite__ → 無 B2 警告、既有 PASS 行不變。"""
        self.build_baseline()
        result = self.run_script("check", "--cmd", CMD_STABLE, "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("失明", result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_check_warns_and_still_passes_when_suite_crashes_again(self):
        """row3[邊界/組合]: baseline known 含 __suite__＋本次全套崩潰 fails=={__suite__}
        → new 為空、判定 PASS exit 0（原失明行為不改）＋同時印 B2 警告（失明現形）。"""
        self.write_baseline_with_stable(["__suite__"])
        result = self.run_script("check", "--cmd", "exit 1", "--strike-key", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("失明", result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_check_without_baseline_fails_with_instruction(self):
        result = self.run_script("check", "--cmd", "exit 0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("先跑 baseline", result.stderr)

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

    def test_missing_cmd_and_manifest_field_errors(self):
        result = self.run_script("baseline")
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_command", result.stderr)

    def init_git(self):
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "x"],
            cwd=self.dir, check=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.dir,
            capture_output=True, text=True,
        ).stdout.strip()

    def write_prev_baseline(self, head_sha, cmd):
        (self.dir / "run").mkdir(exist_ok=True)
        (self.dir / "run" / "prev.test_baseline.json").write_text(
            json.dumps({
                "run_id": "prev", "cmd": cmd, "head_sha": head_sha,
                "stable_failures": ["tests/test_old.py::test_z"],
                "flaky": [], "strikes": {"s9": 1},
            }), encoding="utf-8",
        )

    # 沿用側效檔：baseline 若真的執行測試指令會留下 ran 檔
    CMD_TOUCH = 'touch ran; exit 0'

    def test_baseline_reuses_same_head_and_cmd(self):
        head = self.init_git()
        self.write_prev_baseline(head, self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("沿用 prev", result.stdout)
        self.assertFalse((self.dir / "ran").exists())  # 沒有真的跑測試
        data = self.read_baseline()
        self.assertEqual(data["reused_from"], "prev")
        self.assertEqual(data["stable_failures"], ["tests/test_old.py::test_z"])
        self.assertNotIn("strikes", data)  # 舊檔的 strikes/flaky 欄位不沿用回填
        self.assertNotIn("flaky", data)

    def test_baseline_no_reuse_when_head_differs(self):
        self.init_git()
        self.write_prev_baseline("deadbeef", self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())  # 真的重跑了
        self.assertNotIn("reused_from", self.read_baseline())

    def test_baseline_no_reuse_when_cmd_differs(self):
        head = self.init_git()
        self.write_prev_baseline(head, "exit 0")
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())
        self.assertNotIn("reused_from", self.read_baseline())

    def test_fresh_flag_forces_rebuild(self):
        head = self.init_git()
        self.write_prev_baseline(head, self.CMD_TOUCH)
        result = self.run_script("baseline", "--cmd", self.CMD_TOUCH, "--fresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.dir / "ran").exists())
        self.assertNotIn("reused_from", self.read_baseline())

    def test_suite_crash_then_clean_rerun_drops_suite_sentinel(self):
        """row1: 首跑 __suite__、重跑乾淨 → stable 不含 __suite__、stdout 印未重現關鍵字、全套執行 2 次。"""
        result = self.run_script("baseline", "--cmd", CMD_SUITE_THEN_CLEAN)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("未重現以重跑為準", result.stdout)
        data = self.read_baseline()
        self.assertNotIn("__suite__", data["stable_failures"])
        self.assertEqual(data["stable_failures"], [])
        self.assertEqual(self.read_counter(), 2)

    def test_suite_crash_twice_keeps_suite_sentinel_with_warning(self):
        """row2: 首跑、重跑皆 __suite__ → stable 含 __suite__、stderr 含失明警告與 --fresh 建議。"""
        result = self.run_script("baseline", "--cmd", CMD_SUITE_ALWAYS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("失明", result.stderr)
        self.assertIn("--fresh", result.stderr)
        data = self.read_baseline()
        self.assertIn("__suite__", data["stable_failures"])
        self.assertEqual(self.read_counter(), 2)

    def test_individual_failure_first_run_does_not_rerun(self):
        """row3[邊界]: 首跑即可解析個別失敗（非 __suite__）→ 不重跑、全套執行 1 次、照記為 stable。"""
        result = self.run_script("baseline", "--cmd", CMD_INDIVIDUAL_FIRST)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.read_baseline()
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertEqual(self.read_counter(), 1)

    def test_suite_crash_then_individual_rerun_uses_second_result(self):
        """row4[組合]: 首跑 __suite__、重跑解析出個別失敗 → stable 為第二次個別失敗、不含 __suite__、全套執行 2 次。"""
        result = self.run_script("baseline", "--cmd", CMD_SUITE_THEN_INDIVIDUAL)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.read_baseline()
        self.assertEqual(data["stable_failures"], ["tests/test_broken.py::test_a"])
        self.assertNotIn("__suite__", data["stable_failures"])
        self.assertEqual(self.read_counter(), 2)

    def test_related_maps_by_name_and_content(self):
        (self.dir / "src").mkdir()
        (self.dir / "tests").mkdir()
        (self.dir / "src" / "foo.py").write_text("def foo(): pass\n", encoding="utf-8")
        (self.dir / "tests" / "test_foo.py").write_text("from src.foo import foo\n", encoding="utf-8")
        (self.dir / "tests" / "test_service.py").write_text("import src.foo\n", encoding="utf-8")
        (self.dir / "tests" / "test_unrelated.py").write_text("def test_x(): pass\n", encoding="utf-8")
        result = self.run_script("related", "--files", "src/foo.py")
        paths = set(result.stdout.split())
        self.assertIn("tests/test_foo.py", paths)
        self.assertIn("tests/test_service.py", paths)
        self.assertNotIn("tests/test_unrelated.py", paths)


class SuiteSentinelIntegrationTest(unittest.TestCase):
    """B1（cmd_baseline __suite__ 重跑分支）→ B2（cmd_check 失明警告）跨 item 串接驗證。
    只驗證兩個 item 串起來的行為，不重覆 4.1／4.2 已各自涵蓋的單元案。
    複用既有計數檔 stub（CMD_SUITE_ALWAYS／CMD_SUITE_THEN_CLEAN），不另存副本；
    setUp／run_script／read_baseline／read_counter 沿用 BaselineScriptTest 的既有慣例，
    不繼承其 test_* 方法（避免整合 class 重跑一遍單元案）。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.dir, capture_output=True, text=True,
        )

    def read_baseline(self):
        return json.loads((self.dir / "run" / "t.test_baseline.json").read_text(encoding="utf-8"))

    def read_counter(self):
        """讀計數檔 stub 的呼叫次數（== 全套實際執行次數）。"""
        p = self.dir / "m"
        return int(p.read_text().strip()) if p.exists() else 0

    def test_reproducible_suite_crash_baseline_then_check_warns(self):
        """情境①：baseline 遇可重現 __suite__（B1 照記＋stderr 警告）
        → 對同 run baseline 跑 check，B2 亦印失明警告。"""
        base_result = self.run_script("baseline", "--cmd", CMD_SUITE_ALWAYS)
        self.assertEqual(base_result.returncode, 0, base_result.stderr)
        self.assertIn("失明", base_result.stderr)  # B1 警告
        data = self.read_baseline()
        self.assertIn("__suite__", data["stable_failures"])
        self.assertEqual(self.read_counter(), 2)  # 確認 stub 真的被 B1 重跑呼叫過

        check_result = self.run_script("check", "--cmd", "exit 0", "--strike-key", "s1")
        self.assertEqual(check_result.returncode, 0, check_result.stderr)
        self.assertIn("失明", check_result.stderr)  # B2 警告

    def test_transient_suite_crash_baseline_then_check_no_warning(self):
        """情境②：暫時性路徑（B1 首崩重跑不崩 → 不記 __suite__）
        → 對同 run baseline 跑 check，B2 無失明警告。"""
        base_result = self.run_script("baseline", "--cmd", CMD_SUITE_THEN_CLEAN)
        self.assertEqual(base_result.returncode, 0, base_result.stderr)
        self.assertIn("未重現以重跑為準", base_result.stdout)
        data = self.read_baseline()
        self.assertNotIn("__suite__", data["stable_failures"])
        self.assertEqual(self.read_counter(), 2)  # 確認 stub 真的被 B1 重跑呼叫過

        check_result = self.run_script("check", "--cmd", "exit 0", "--strike-key", "s1")
        self.assertEqual(check_result.returncode, 0, check_result.stderr)
        self.assertNotIn("失明", check_result.stderr)


class BuildMineCmdTest(unittest.TestCase):
    """build_mine_argv 純函式的單元測試（無 subprocess）。"""

    def test_pytest_appends_file_paths(self):
        argv = build_mine_argv("pytest -q", ["tests/test_foo.py", "tests/test_bar.py"])
        self.assertEqual(argv, ["pytest", "-q", "tests/test_foo.py", "tests/test_bar.py"])

    def test_unittest_discover_converts_to_modules(self):
        argv = build_mine_argv(
            "python3 -m unittest discover -s tests",
            ["tests/test_foo.py"],
        )
        self.assertEqual(argv, ["python3", "-m", "unittest", "tests.test_foo"])

    def test_unittest_plain_also_converts_to_modules(self):
        # "python3 -m unittest" 不含 discover 也要走 module 路徑
        argv = build_mine_argv(
            "python3 -m unittest",
            ["tests/test_foo.py", "tests/test_bar.py"],
        )
        self.assertEqual(argv, ["python3", "-m", "unittest", "tests.test_foo", "tests.test_bar"])

    def test_is_test_file_detects_test_prefix(self):
        self.assertTrue(is_test_file("tests/test_foo.py"))
        self.assertTrue(is_test_file("test_bar.py"))
        self.assertFalse(is_test_file("src/foo.py"))

    def test_is_test_file_skips_skip_dirs(self):
        self.assertFalse(is_test_file(".venv/tests/test_foo.py"))

    def test_is_test_file_excludes_flow_spec_dir(self):
        # spec/ 是 eval-flow 自產的產出物目錄，不是測試目錄（L8 教訓：曾被當測試檔餵 pytest）
        self.assertFalse(is_test_file("spec/2026-07-21-phase-c.md"))
        self.assertFalse(is_test_file("spec/bootstrap.md"))

    def test_is_test_file_excludes_non_code_extensions(self):
        # 測試目錄裡的 fixture／文件不餵 runner
        self.assertFalse(is_test_file("tests/fixture.json"))
        self.assertFalse(is_test_file("tests/README.md"))
        self.assertFalse(is_test_file("test_plan.md"))  # TEST_FILE_RE 前綴命中但非 code 檔

    def test_is_test_file_keeps_multi_framework_conventions(self):
        # 多框架慣例不得因副檔名守門而誤傷
        self.assertTrue(is_test_file("src/foo.test.ts"))
        self.assertTrue(is_test_file("src/bar.spec.js"))
        self.assertTrue(is_test_file("__tests__/baz.jsx"))


class MineSubcommandTest(unittest.TestCase):
    """mine 子命令的 subprocess 整合測試（需 git repo）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")
        # 建立 git repo
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=self.dir, check=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.dir, capture_output=True, text=True,
        )

    def write_baseline(self):
        (self.dir / "run").mkdir(exist_ok=True)
        data = {
            "run_id": "t", "cmd": "exit 0", "head_sha": "abc",
            "stable_failures": [],
        }
        (self.dir / "run" / "t.test_baseline.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_mine_with_test_file_runs_only_that_file(self):
        """untracked 測試檔存在時，mine 只跑該測試檔（runner 收到的路徑正確）。"""
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "test_foo.py").write_text("", encoding="utf-8")
        (self.dir / "src").mkdir()
        (self.dir / "src" / "main.py").write_text("", encoding="utf-8")
        sentinel = self.dir / "ran.txt"
        # 寫一個 shell script 接收參數並記錄到檔案
        runner = self.dir / "fake_runner.sh"
        runner.write_text(f'#!/bin/sh\necho "$@" > {sentinel}\n', encoding="utf-8")
        runner.chmod(0o755)
        result = self.run_script("mine", "--cmd", str(runner))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(sentinel.exists(), "假 runner 應有執行")
        got = sentinel.read_text(encoding="utf-8").strip()
        self.assertIn("tests/test_foo.py", got)

    def test_mine_appends_run_log_each_execution(self):
        """每次 mine 執行 append 一筆留痕：seq 遞增、失敗集合與測試檔 hash 都記錄。"""
        (self.dir / "tests").mkdir()
        tf = self.dir / "tests" / "test_foo.py"
        tf.write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self): self.fail()\n",
            encoding="utf-8",
        )
        r1 = self.run_script("mine", "--cmd", "python3 -m unittest discover -s tests",
                             "--strike-key", "sub_task_1")
        self.assertEqual(r1.returncode, 2)
        # 修好測試再跑一次 → 第二筆，hash 應改變、fails 清空
        tf.write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n",
            encoding="utf-8",
        )
        r2 = self.run_script("mine", "--cmd", "python3 -m unittest discover -s tests",
                             "--strike-key", "sub_task_1")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("第 2 次執行", r2.stdout)
        log = json.loads((self.dir / "run" / "t.mine_log.json").read_text(encoding="utf-8"))
        self.assertEqual([r["seq"] for r in log["runs"]], [1, 2])
        self.assertEqual(log["runs"][0]["strike_key"], "sub_task_1")
        self.assertTrue(log["runs"][0]["fails"])   # 第一次有失敗
        self.assertEqual(log["runs"][1]["fails"], [])  # 修好後清空
        h1 = log["runs"][0]["test_hashes"]["tests/test_foo.py"]
        h2 = log["runs"][1]["test_hashes"]["tests/test_foo.py"]
        self.assertNotEqual(h1, h2)  # 測試檔在兩次之間被改過 → 稽核可見

    def test_mine_no_test_files_exits_0_with_message(self):
        """變更中無測試檔 → exit 0、stdout 含「無測試檔」。"""
        (self.dir / "src").mkdir()
        (self.dir / "src" / "foo.py").write_text("", encoding="utf-8")
        result = self.run_script("mine", "--cmd", "exit 0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("無測試檔", result.stdout)

    def test_mine_test_failure_exits_2(self):
        """mine 範圍內的測試失敗 → exit 2。"""
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "test_foo.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self): self.fail()\n",
            encoding="utf-8",
        )
        result = self.run_script("mine", "--cmd", "python3 -m unittest discover -s tests")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_mine_failure_with_strike_key_does_not_count(self):
        """失敗且有 --strike-key ＋既有 baseline 檔 → exit 2，但不寫入計數（strike 已移除）。"""
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "test_foo.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self): self.fail()\n",
            encoding="utf-8",
        )
        self.write_baseline()
        result = self.run_script(
            "mine", "--cmd", "python3 -m unittest discover -s tests", "--strike-key", "sk1"
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("2 次上限", result.stderr)
        self.assertNotIn("連續失敗", result.stderr)
        self.assertNotIn("strikes", self.read_baseline())

    def read_baseline(self):
        return json.loads((self.dir / "run" / "t.test_baseline.json").read_text(encoding="utf-8"))

    def test_mine_no_baseline_does_not_create_baseline(self):
        """baseline 不存在時，mine 不建立 baseline 檔。"""
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "test_foo.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n",
            encoding="utf-8",
        )
        self.run_script("mine", "--cmd", "python3 -m unittest discover -s tests", "--strike-key", "sk1")
        self.assertFalse((self.dir / "run" / "t.test_baseline.json").exists())

    def test_mine_discover_cmd_does_not_pass_discover_flag(self):
        """unittest discover 型 cmd → mine 實際執行的 argv 不含 discover。
        用 python3 -m unittest 直接跑 sentinel 測試檔確認真正執行、且沒有 discover。"""
        (self.dir / "tests").mkdir()
        # 寫一個真實可執行的 unittest 測試，通過即可
        (self.dir / "tests" / "test_sentinel.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n",
            encoding="utf-8",
        )
        result = self.run_script(
            "mine", "--cmd", "python3 -m unittest discover -s tests",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # 確認沒有 discover 相關警告或錯誤（discover 若被傳入 unittest module 模式會出現 error）
        self.assertNotIn("discover", result.stderr)


class GitChangedFilesTest(unittest.TestCase):
    """git_changed_files 的整合測試（需真實 git repo）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=self.dir, check=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def git_changed(self):
        """在 self.dir 內呼叫 git_changed_files（透過子程序以免 cwd 干擾）。"""
        hooks_dir = str(SCRIPT.parent)
        code = (
            f"import sys; sys.path.insert(0, {hooks_dir!r}); "
            "from test_baseline import git_changed_files; "
            "print('\\n'.join(git_changed_files()))"
        )
        p = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.dir, capture_output=True, text=True,
        )
        lines = [l for l in p.stdout.splitlines() if l]
        return lines

    def git(self, *args):
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=self.dir, check=True,
        )

    def test_rename_takes_new_path(self):
        """git mv 重命名：只取 new 路徑，不含 old。"""
        (self.dir / "old.py").write_text("x", encoding="utf-8")
        self.git("add", "old.py")
        self.git("commit", "-q", "-m", "add")
        self.git("mv", "old.py", "new.py")
        files = self.git_changed()
        self.assertIn("new.py", files)
        self.assertNotIn("old.py", files)

    def test_deleted_file_excluded(self):
        """deleted 檔不出現在結果中。"""
        (self.dir / "del.py").write_text("x", encoding="utf-8")
        self.git("add", "del.py")
        self.git("commit", "-q", "-m", "add")
        self.git("rm", "-q", "del.py")
        files = self.git_changed()
        self.assertNotIn("del.py", files)

    def test_filename_with_space(self):
        """含空白的未追蹤檔名正確解析（不帶引號）。"""
        (self.dir / "test_a b.py").write_text("", encoding="utf-8")
        files = self.git_changed()
        self.assertIn("test_a b.py", files)

    def test_filename_with_dollar_sign(self):
        """含 $ 的未追蹤檔名正確解析（不被 shell 展開）。"""
        (self.dir / "test_$x.py").write_text("", encoding="utf-8")
        files = self.git_changed()
        self.assertIn("test_$x.py", files)

    def test_untracked_directory_expands(self):
        """未追蹤目錄展開為子檔案。"""
        subdir = self.dir / "newpkg"
        subdir.mkdir()
        (subdir / "test_one.py").write_text("", encoding="utf-8")
        (subdir / "test_two.py").write_text("", encoding="utf-8")
        files = self.git_changed()
        self.assertIn("newpkg/test_one.py", files)
        self.assertIn("newpkg/test_two.py", files)


class MineWithSpaceFilenameTest(unittest.TestCase):
    """含空白檔名的測試檔能被 mine 正確執行（端到端）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "eval_state.json").write_text('{"run_id": "t"}', encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=self.dir, check=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.dir, capture_output=True, text=True,
        )

    def test_mine_space_in_filename(self):
        """含空白的測試檔名不造成 shell 注入，mine 正確執行並通過。"""
        (self.dir / "tests").mkdir()
        # 含空白的測試檔：真實 unittest
        (self.dir / "tests" / "test_a b.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n",
            encoding="utf-8",
        )
        result = self.run_script(
            "mine", "--cmd", "python3 -m unittest discover -s tests",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
