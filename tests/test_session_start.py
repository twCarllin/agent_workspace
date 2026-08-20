"""session_start.py 的假 payload 端到端測試（SessionStart hook）。

依 retro 約束（跨進程執行契約）：測試一律用 subprocess 跑真實
`python3 .claude/hooks/session_start.py`，不 import 直呼 main()——以直接呼叫內部
函式繞過該契約實際執行路徑的單元測試，不構成驗收證據。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "hooks" / "session_start.py"

VALID_PAYLOAD = json.dumps({
    "session_id": "s1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "SessionStart",
})


def run_session_start(payload_str, cwd, env=None):
    """以 subprocess 跑真實 session_start.py（不 import），回傳 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload_str,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=30,
    )


def make_manifest(run_dir, run_id, status="in_progress", phase="decomposed"):
    path = os.path.join(run_dir, f"{run_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "status": status, "phase": phase}, f)
    return path


def make_green_doctor_home(tmp_root):
    """建一個乾淨的假 HOME，讓 doctor.py 的 skills 同步／核心 skill 檢查全綠
    （鏡射真實 repo skills/，排除 _deprecated；手法同 test_doctor.py 的
    DeprecatedSkillsIntegrationTest）。回傳假 HOME 路徑。"""
    fake_home = os.path.join(tmp_root, "fake_home")
    deploy_skills = os.path.join(fake_home, ".claude", "skills")
    os.makedirs(deploy_skills)
    repo_skills = ROOT / "skills"
    for name in os.listdir(repo_skills):
        if name == "_deprecated" or name.startswith("."):
            continue
        src = repo_skills / name
        if src.is_dir():
            shutil.copytree(src, os.path.join(deploy_skills, name))
    return fake_home


class ResidualRunPromptTest(unittest.TestCase):
    """情境 K：殘留 in_progress manifest → 輸出提示（含 run_id／phase）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        os.makedirs(os.path.join(self.cwd, "run"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_residual_in_progress_manifest_reported(self):
        make_manifest(os.path.join(self.cwd, "run"), "test-run-1",
                       status="in_progress", phase="decomposed")
        p = run_session_start(VALID_PAYLOAD, cwd=self.cwd)
        self.assertEqual(p.returncode, 0)
        self.assertIn(
            "有未收尾的 run：test-run-1（phase=decomposed），"
            "依 eval-flow-resume skill 從檔案恢復，不靠記憶；或標 aborted 收尾",
            p.stdout,
        )

    def test_completed_manifest_not_reported(self):
        """[寬鬆] status 非 in_progress（如 completed）的 manifest 不觸發殘留提示。"""
        make_manifest(os.path.join(self.cwd, "run"), "test-run-2",
                       status="completed", phase="completed")
        p = run_session_start(VALID_PAYLOAD, cwd=self.cwd)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("有未收尾的 run", p.stdout)


class NoResidualCleanDoctorTest(unittest.TestCase):
    """情境 K-edge1：無殘留且 doctor --brief 全綠 → 輸出空。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.path.join(self.tmp.name, "cwd")
        os.makedirs(os.path.join(self.cwd, "run"))
        os.makedirs(os.path.join(self.cwd, "retro"))
        with open(os.path.join(self.cwd, "retro", "RETRO.md"), "w", encoding="utf-8") as f:
            f.write("# retro\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_residual_and_doctor_clean_outputs_empty(self):
        fake_home = make_green_doctor_home(self.tmp.name)
        env = {**os.environ, "HOME": fake_home}
        p = run_session_start(VALID_PAYLOAD, cwd=self.cwd, env=env)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")


class PayloadParseFailureTest(unittest.TestCase):
    """情境 K-err1：stdin payload 解析失敗 → 靜默 exit 0（無任何輸出）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        os.makedirs(os.path.join(self.cwd, "run"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_payload_exits_silently(self):
        p = run_session_start("not valid json {{{", cwd=self.cwd)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr, "")

    def test_empty_stdin_exits_silently(self):
        p = run_session_start("", cwd=self.cwd)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr, "")


class OutputLineLimitTest(unittest.TestCase):
    """情境 M：stdout 輸出上限 ≤10 行。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.path.join(self.tmp.name, "cwd")
        os.makedirs(os.path.join(self.cwd, "run"))
        os.makedirs(os.path.join(self.cwd, "retro"))
        with open(os.path.join(self.cwd, "retro", "RETRO.md"), "w", encoding="utf-8") as f:
            f.write("# retro\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_output_truncated_to_at_most_ten_lines(self):
        """假 HOME 灌入 15 個未納入版控的 skill 目錄，doctor --brief 會產出 >10 條
        ISSUE 行；session_start.py 的輸出仍須截到 ≤10 行。"""
        fake_home = os.path.join(self.tmp.name, "fake_home_many_issues")
        deploy_skills = os.path.join(fake_home, ".claude", "skills")
        os.makedirs(deploy_skills)
        for i in range(15):
            os.makedirs(os.path.join(deploy_skills, f"bogus-skill-{i}"))
        env = {**os.environ, "HOME": fake_home}
        p = run_session_start(VALID_PAYLOAD, cwd=self.cwd, env=env)
        self.assertEqual(p.returncode, 0)
        lines = p.stdout.splitlines()
        self.assertGreater(len(lines), 0)
        self.assertLessEqual(len(lines), 10)


class ResidualAndDoctorIssuesCombinedTest(unittest.TestCase):
    """4.4 整合：殘留 in_progress manifest ＋ doctor 異常行同時輸出（合流），
    仍受 ≤10 行上限節制（情境 K＋M 的跨 item 組合）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.path.join(self.tmp.name, "cwd")
        os.makedirs(os.path.join(self.cwd, "run"))
        os.makedirs(os.path.join(self.cwd, "retro"))
        with open(os.path.join(self.cwd, "retro", "RETRO.md"), "w", encoding="utf-8") as f:
            f.write("# retro\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_residual_and_doctor_issue_both_present(self):
        make_manifest(os.path.join(self.cwd, "run"), "combo-run",
                       status="in_progress", phase="risk_done")
        # 假 HOME 只放一個假 skill，觸發真實 doctor 的 skills 同步／缺核心 skill 異常
        fake_home = os.path.join(self.tmp.name, "fake_home_one_issue")
        deploy_skills = os.path.join(fake_home, ".claude", "skills")
        os.makedirs(deploy_skills)
        os.makedirs(os.path.join(deploy_skills, "bogus-skill"))
        env = {**os.environ, "HOME": fake_home}
        p = run_session_start(VALID_PAYLOAD, cwd=self.cwd, env=env)
        self.assertEqual(p.returncode, 0)
        lines = p.stdout.splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(lines), 10)
        self.assertIn("有未收尾的 run：combo-run", lines[0])
        self.assertTrue(any("[doctor] ISSUE" in line for line in lines[1:]))


class WorktreeCwdHonoredTest(unittest.TestCase):
    """🟡 修正驗證（code-review）：session_start.py 須與姊妹 hook
    （`eval_gates.run_hook()`）一致，以 `payload.cwd` 解析 worktree 根後才掃描，
    不可信任 `os.getcwd()`（BUGLOG 2026-07-28 worktree-root gate 靜默失效同源問題）。
    真實 git worktree（手法同 `tests/test_eval_gates.py:513` `RunHookWorktreeRootTest`）：
    `CLAUDE_PROJECT_DIR` 與 subprocess 實際 cwd 皆指向 main（無殘留）；
    `payload.cwd` 指向 worktree（有殘留 in_progress manifest）→ 輸出仍須含該提示，
    釘住 payload.cwd 生效、而非誤讀 main。"""

    def setUp(self):
        self.tmp_base = tempfile.TemporaryDirectory()
        base = self.tmp_base.name
        self.main = os.path.join(base, "main")
        os.makedirs(self.main)
        subprocess.run(["git", "init", self.main], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "config", "user.email", "t@t.com"],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "config", "user.name", "T"],
                        check=True, capture_output=True)
        open(os.path.join(self.main, ".gitkeep"), "w").close()
        subprocess.run(["git", "-C", self.main, "add", ".gitkeep"],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", self.main, "commit", "-m", "init"],
                        check=True, capture_output=True)

        # worktree add 前 path 不可預先存在
        self.worktree = os.path.join(base, "worktree")
        subprocess.run(
            ["git", "-C", self.main, "worktree", "add", "--detach", self.worktree],
            check=True, capture_output=True,
        )
        os.makedirs(os.path.join(self.worktree, "run"))
        make_manifest(os.path.join(self.worktree, "run"), "worktree-run",
                       status="in_progress", phase="risk_done")

    def tearDown(self):
        self.tmp_base.cleanup()

    def test_payload_cwd_used_over_claude_project_dir(self):
        payload = json.dumps({
            "session_id": "s1",
            "transcript_path": "/tmp/x",
            "cwd": self.worktree,
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
        })
        env = {**os.environ, "CLAUDE_PROJECT_DIR": self.main}
        p = run_session_start(payload, cwd=self.main, env=env)
        self.assertEqual(p.returncode, 0)
        self.assertIn("有未收尾的 run：worktree-run", p.stdout)


class SettingsJsonWiringTest(unittest.TestCase):
    """4.4：repo 自身 `.claude/settings.json` 含 PreToolUse／SessionStart 兩事件內容。
    settings 接線本 session 無法端到端驗證 hook 真的被 runtime 觸發（風險部署#1）；
    本測試驗內容正確，與上方假 payload 端到端測試（script 層）合為雙層替代驗證。"""

    def test_settings_json_has_both_hook_events(self):
        with open(ROOT / ".claude" / "settings.json", encoding="utf-8") as f:
            settings = json.load(f)
        pre = settings["hooks"]["PreToolUse"]
        self.assertTrue(
            any("gate-check.sh" in h["command"] for entry in pre for h in entry["hooks"])
        )
        session_start = settings["hooks"]["SessionStart"]
        self.assertEqual(session_start[0]["matcher"], "startup|resume|compact")
        self.assertTrue(
            any(
                "session_start.py" in h["command"]
                for entry in session_start
                for h in entry["hooks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
