"""doctor.py 的 check_skills_sync 與 --brief（report）測試。

執行：python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
