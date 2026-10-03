"""doctor.py 的 check_skills_sync 與 --brief（report）測試。

執行：python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import doctor  # noqa: E402


def make_skill(base_dir, skill_name, files=None):
    """在 base_dir 下建立一個 skill 目錄（含可選的檔案 {rel_path: content}）。"""
    skill_dir = os.path.join(base_dir, skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    if files:
        for rel_path, content in files.items():
            full_path = os.path.join(skill_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)


class CheckSkillsSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo_skills")
        self.deploy = os.path.join(self.tmp.name, "deploy_skills")
        os.makedirs(self.repo)
        os.makedirs(self.deploy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_issues_empty_ok_has_count(self):
        """完全一致：issues 空；ok 含「一致」與數量。"""
        make_skill(self.repo, "foo", {"SKILL.md": "content"})
        make_skill(self.deploy, "foo", {"SKILL.md": "content"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(issues, [])
        ok_text = " ".join(ok)
        self.assertIn("一致", ok_text)
        self.assertIn("1", ok_text)

    def test_repo_only_skill_reported_as_undeployed(self):
        """repo 有、部署層無：issues 恰 1 條，含 skill 名與「未部署」語義。"""
        make_skill(self.repo, "foo", {"SKILL.md": "content"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(len(issues), 1)
        self.assertIn("foo", issues[0])
        self.assertIn("未部署", issues[0])

    def test_deploy_only_skill_reported_as_unversioned(self):
        """部署層有、repo 無：issues 恰 1 條，含 skill 名與「未納入版控」語義。"""
        make_skill(self.deploy, "bar", {"SKILL.md": "content"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(len(issues), 1)
        self.assertIn("bar", issues[0])
        self.assertIn("未納入版控", issues[0])

    def test_content_mismatch_reported(self):
        """兩邊都有、內容不同：issues 恰 1 條，含 skill 名與「不同步」語義。"""
        make_skill(self.repo, "mypkg", {"SKILL.md": "version1"})
        make_skill(self.deploy, "mypkg", {"SKILL.md": "version2"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(len(issues), 1)
        self.assertIn("mypkg", issues[0])
        self.assertIn("不同步", issues[0])

    def test_nested_content_mismatch_detected(self):
        """內容差異在巢狀子目錄：遞迴比對須偵測到，issues 恰 1 條含 skill 名。"""
        make_skill(self.repo, "mypkg", {"SKILL.md": "same", "references/x.md": "v1"})
        make_skill(self.deploy, "mypkg", {"SKILL.md": "same", "references/x.md": "v2"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(len(issues), 1)
        self.assertIn("mypkg", issues[0])

    def test_deploy_dir_missing_skipped_gracefully(self):
        """部署層目錄不存在：issues 空；ok 含「略過」說明，不拋例外。"""
        deploy_nonexistent = os.path.join(self.tmp.name, "nonexistent_deploy")
        ok, issues = doctor.check_skills_sync(self.repo, deploy_nonexistent)
        self.assertEqual(issues, [])
        self.assertTrue(any("略過" in m for m in ok))

    def test_repo_skills_missing_skipped_gracefully(self):
        """repo 無 skills/：issues 空；ok 含「略過」說明，不拋例外。"""
        repo_nonexistent = os.path.join(self.tmp.name, "nonexistent_repo")
        ok, issues = doctor.check_skills_sync(repo_nonexistent, self.deploy)
        self.assertEqual(issues, [])
        self.assertTrue(any("略過" in m for m in ok))

    def test_dotfile_not_treated_as_drift(self):
        """邊界：一邊多一個 .DS_Store，不視為漂移（issues 空）。"""
        make_skill(self.repo, "foo", {"SKILL.md": "content"})
        make_skill(self.deploy, "foo", {"SKILL.md": "content"})
        with open(os.path.join(self.deploy, ".DS_Store"), "w", encoding="utf-8") as f:
            f.write("junk")
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(issues, [])

    # --- 3c：_deprecated 排除（僅 repo 有 _deprecated，部署層沒有——不誤報 repo_only）---

    def test_deprecated_dir_not_reported_as_repo_only(self):
        """[邊界] repo 含 _deprecated、部署層不含（正常情境：已排除同步）→ 不報 repo_only。"""
        make_skill(self.repo, "_deprecated", {"eval-scoring/SKILL.md": "old"})
        make_skill(self.repo, "foo", {"SKILL.md": "content"})
        make_skill(self.deploy, "foo", {"SKILL.md": "content"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(issues, [])

    def test_deprecated_dir_not_counted_in_sync_total(self):
        """健檢不計 _deprecated：兩邊都有時，同步計數只算非 _deprecated 的 skill 數。"""
        make_skill(self.repo, "_deprecated", {"eval-scoring/SKILL.md": "old"})
        make_skill(self.repo, "foo", {"SKILL.md": "content"})
        make_skill(self.deploy, "_deprecated", {"eval-scoring/SKILL.md": "old"})
        make_skill(self.deploy, "foo", {"SKILL.md": "content"})
        ok, issues = doctor.check_skills_sync(self.repo, self.deploy)
        self.assertEqual(issues, [])
        ok_text = " ".join(ok)
        self.assertIn("1", ok_text)  # 只計 foo，不含 _deprecated


class ReportBriefTest(unittest.TestCase):
    """4.1：doctor.py `report()`（--brief 旗標的輸出格式邏輯）。"""

    def _run(self, ok, issues, brief):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.report(ok, issues, brief=brief)
        return code, out.getvalue(), err.getvalue()

    def test_brief_with_issues_prints_only_issue_lines(self):
        """--brief 有異常 → 僅印異常行（無 OK、無「N 個問題」摘要）；exit code 維持既有非零約定。"""
        code, out, err = self._run(["ok1"], ["bad1", "bad2"], brief=True)
        self.assertEqual(out, "")
        self.assertEqual(err, "[doctor] ISSUE: bad1\n[doctor] ISSUE: bad2\n")
        self.assertEqual(code, 1)

    def test_brief_all_clean_no_output(self):
        """--brief 全綠 → 無任何輸出（stdout 與 stderr 皆空）。"""
        code, out, err = self._run(["ok1", "ok2"], [], brief=True)
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(code, 0)

    def test_default_mode_with_issues_unchanged(self):
        """無 --brief（有異常）→ 行為不變：OK 行照印、ISSUE 行照印、附「N 個問題」摘要。"""
        code, out, err = self._run(["ok1"], ["bad1"], brief=False)
        self.assertEqual(out, "[doctor] OK: ok1\n")
        self.assertIn("[doctor] ISSUE: bad1\n", err)
        self.assertIn("1 個問題", err)
        self.assertEqual(code, 1)

    def test_default_mode_all_clean_unchanged(self):
        """無 --brief（全綠）→ 行為不變：OK 行＋「健檢通過」，無 stderr 輸出。"""
        code, out, err = self._run(["ok1"], [], brief=False)
        self.assertEqual(out, "[doctor] OK: ok1\n[doctor] 健檢通過\n")
        self.assertEqual(err, "")
        self.assertEqual(code, 0)


class HooksListTest(unittest.TestCase):
    """item 1.4（task/2026-09-29.md）契約 T5：健檢清單含 dispatch.py。"""

    def test_t5_missing_dispatch_reported(self):
        """T5：hooks 目錄缺 dispatch.py → issues 含「hooks 缺 dispatch.py」（以複製到暫存目錄的
        doctor.py 執行，其他 script 齊全、只缺 dispatch.py）。"""
        hooks_dir = Path(doctor.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            fake_hooks = os.path.join(tmp, ".claude", "hooks")
            os.makedirs(fake_hooks)
            for name in doctor.HOOKS + ["VERSION", "doctor.py"]:
                if name != "dispatch.py":
                    shutil.copy2(hooks_dir / name, fake_hooks)
            proc = subprocess.run(
                [sys.executable, os.path.join(fake_hooks, "doctor.py"), "--brief"],
                capture_output=True, text=True,
            )
        self.assertIn("hooks 缺 dispatch.py", proc.stderr)
        self.assertIn("dispatch.py", doctor.HOOKS)


class HarnessDoctorTest(unittest.TestCase):
    def test_codex_only_project_and_legacy_entry_use_same_core(self):
        root = Path(__file__).resolve().parents[1]
        legacy = root / ".claude/hooks/doctor.py"
        core = root / ".agent-flow/scripts/doctor.py"
        self.assertTrue(legacy.is_symlink())
        self.assertEqual(legacy.resolve(), core.resolve())
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".codex/agents").mkdir(parents=True)
            (project / ".codex/config.toml").write_text(
                '[agents.code-writer]\nconfig_file = "agents/code-writer.toml"\n')
            (project / ".codex/agents/code-writer.toml").write_text('name = "code-writer"\n')
            (project / ".codex/hooks.json").write_text('{"hooks":{"PreToolUse":[{"hooks":[{"command":"python3 .agent-flow/scripts/eval_gates.py --hook"}]}]}}')
            (project / "AGENTS.md").write_text("Flow instructions\n")
            (project / "retro").mkdir()
            (project / "retro/RETRO.md").write_text("Seed\n")
            shutil.copytree(root / "skills", project / ".agents/skills",
                            ignore=shutil.ignore_patterns("_deprecated", ".*"))
            for entry in (legacy, core):
                proc = subprocess.run([sys.executable, str(entry), "--harness", "codex"],
                                      cwd=project, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("Codex 角色設定已部署", proc.stdout)
            proc = subprocess.run([sys.executable, str(core), "--harness", "both"],
                                  cwd=project, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("settings.json", proc.stderr)


if __name__ == "__main__":
    unittest.main()
