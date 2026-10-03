"""retro_select.py（知識前置的 retro 條目篩選）契約測試。

對映 run 2026-10-03-deterministic-scripts 的 item 9.1 契約 row C1–C5。
一律以子程序黑箱執行真實 CLI 路徑（R-005：跨進程契約不以直接 import 內部函式繞過）。

執行：python3 -m pytest tests/test_retro_select.py -q
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".claude", "hooks", "retro_select.py")

# fixture RETRO.md：含檔頭格式範例（不可被當成條目）、兩條 eval_gates 標籤、一條 retired、
# 一條錨點已失效、一條無關標籤。
FIXTURE_RETRO = """# RETRO

> **ID 規則**：格式：條目行首 `- R-NNN 2026-...`
> **retired 生命週期**：於 ID 後標 `［retired YYYY-MM-DD <run_id>］`（例：`- R-00X ［retired 2026-09-11 2026-09-11-foo］ 2026-...`）
> 範例錨點寫法：`［錨點: X］`

- R-101 2026-08-20［.claude/hooks／eval_gates／時序耦合／2026-08-20-obs］放行型與攔截型 gate 的順序。**約束：攔截型必須排在放行型之前。**
- R-102 2026-08-20［.claude/hooks／eval_gates／判定基準混用／2026-08-20-obs］狀態查詢基準不一致。**約束：必須沿用同一基準。**［錨點: _resolve_root］
- R-103 ［retired 2026-09-11 2026-09-11-foo］ 2026-07-01［.claude/hooks／eval_gates／已退役／2026-07-01-x］舊機制。**約束：不該再被貼。**
- R-104 2026-07-17［.claude/hooks／eval_gates／錨點失效／2026-07-17-y］依賴一個已消失的 helper。**約束：必須沿用它。**［錨點: 這個符號不存在於任何檔案］
- R-105 2026-09-01［api／settlement／金流／2026-09-01-z］與本次無關的模組。**約束：不相干。**
- R-106 2026-07-02［.claude/hooks／eval_gates／檔名型錨點／2026-07-02-w］依賴一個 script 檔。**約束：沿用它。**［錨點: legacy_helper.py］
- R-107 ［retired ］ 2026-07-03［.claude/hooks／eval_gates／空原因退役／2026-07-03-v］退役但原因欄為空。**約束：不該被貼。**
- R-108 2026-07-04［.claude/hooks／eval_gates／regex 字元錨點／2026-07-04-u］錨點含 regex 有意義的字元。**約束：沿用它。**［錨點: a.*b[0]$］
- R-109 2026-09-02［frontend／widget／無關模組／2026-09-02-retro-select-tests］標籤模組無關，但 run_id 段含 retro_select。**約束：不該因 run_id 被選中。**
"""


class RetroSelectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.retro = os.path.join(self.dir, "RETRO.md")
        with open(self.retro, "w", encoding="utf-8") as f:
            f.write(FIXTURE_RETRO)
        # codebase：讓 R-102 的錨點 _resolve_root 存在、R-104 的錨點不存在
        with open(os.path.join(self.dir, "eval_gates.py"), "w", encoding="utf-8") as f:
            f.write("def _resolve_root(payload):\n    return payload['cwd']\n")
        # 檔名型錨點：檔案存在，但**沒有任何檔案提及它的名字**（只搜內容會誤判已消失）
        with open(os.path.join(self.dir, "legacy_helper.py"), "w", encoding="utf-8") as f:
            f.write("def helper():\n    pass\n")
        # regex 字元錨點：以字面出現在某檔內容中
        with open(os.path.join(self.dir, "patterns.txt"), "w", encoding="utf-8") as f:
            f.write("pattern a.*b[0]$ is literal here\n")
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                    ["git", "config", "user.name", "T"]):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=self.dir, check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_select(self, *files, root=None, retro=None):
        argv = [sys.executable, SCRIPT, "--files", *files,
                "--retro", retro or self.retro, "--root", root or self.dir]
        return subprocess.run(argv, capture_output=True, text=True)

    def chosen_section(self, stdout):
        """取「選中條目」節的內文（到下一個 ## 為止）。"""
        body = stdout.split("## 選中條目", 1)[1]
        return body.split("## retire 候選", 1)[0]

    def retire_section(self, stdout):
        return stdout.split("## retire 候選", 1)[1]

    def test_c1_matching_tag_selected_unrelated_not(self):
        """C1：--files 指向 eval_gates.py → 選中標籤含 eval_gates 的條目，無關模組不選。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        chosen = self.chosen_section(proc.stdout)
        self.assertIn("R-101", chosen)
        self.assertIn("R-102", chosen)
        self.assertNotIn("R-105", chosen)
        self.assertIn("eval_gates", proc.stdout)

    def test_c2_retired_entry_never_selected(self):
        """C2：標 ［retired …］ 的條目一律不進選中節（也不算 retire 候選——它已經退役了）。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("R-103", self.chosen_section(proc.stdout))
        self.assertNotIn("R-103", self.retire_section(proc.stdout))

    def test_c3_dead_anchor_moves_to_retire_candidates(self):
        """C3：帶 ［錨點: …］ 但錨點查無 → 移入 retire 候選、不在選中節；錨點仍在者照常選中。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("R-104", self.chosen_section(proc.stdout))
        self.assertIn("R-104", self.retire_section(proc.stdout))
        self.assertIn("R-102", self.chosen_section(proc.stdout))

    def test_c4_no_match_prints_placeholder_and_exits_zero(self):
        """C4：零命中 → 選中節印留痕句、exit 0（選擇器不是 gate）。"""
        proc = self.run_select("backend/payments/Ledger.tsx")  # 片段與任何 fixture 標籤皆不相交
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("retro 源無相關條目", self.chosen_section(proc.stdout))
        self.assertNotIn("R-101", self.chosen_section(proc.stdout))

    def test_c5_paths_with_spaces_and_special_chars(self):
        """C5 [邊界]：含空白與 $ 的路徑 → 正常推導片段、不拋例外、不經 shell。"""
        proc = self.run_select("src/my module/eval_gates.py", "src/a$b/other.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("eval_gates", proc.stdout)
        self.assertIn("R-101", self.chosen_section(proc.stdout))

    def test_comma_separated_files_accepted(self):
        """--files 接受逗號分隔（manifest／task 檔的 files 欄慣用寫法）。"""
        proc = self.run_select(".claude/hooks/eval_gates.py,tests/test_eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-101", self.chosen_section(proc.stdout))

    def test_header_format_examples_are_not_parsed_as_entries(self):
        """檔頭的格式範例（R-00X、［錨點: X］）不得被當成條目選入。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("R-00X", proc.stdout)
        self.assertIn("條目 9 條", proc.stdout)

    def test_unreadable_retro_is_usage_error(self):
        """RETRO.md 讀不到 → exit 1（使用錯誤），不靜默回零命中。"""
        proc = self.run_select("a/eval_gates.py", retro=os.path.join(self.dir, "missing.md"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("讀不到", proc.stderr)

    def test_fragments_undeducible_is_usage_error(self):
        """--files 只給通用名（推不出片段）→ exit 1，不默默掃出全部條目。"""
        proc = self.run_select("skills/SKILL.md")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("推導不出", proc.stderr)

    def test_dead_anchor_recorded_only_in_history_still_counts_as_dead(self):
        """記錄性檔案不算 codebase：錨點只出現在 HISTORY.md 時仍判已消失。

        這條讓 EXCLUDED_FROM_ANCHOR_SCAN 成為承重常數——HISTORY.md 的存在目的正是記載已
        消失的機制，把它算進 codebase 會讓每個退役錨點都「仍存在」、鮮度檢查整條失效。
        """
        with open(os.path.join(self.dir, "HISTORY.md"), "w", encoding="utf-8") as f:
            f.write("- 2026-07-01｜x｜舊機制留痕：這個符號不存在於任何檔案 已於某 run 移除\n")
        subprocess.run(["git", "add", "HISTORY.md"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-104", self.retire_section(proc.stdout))
        self.assertNotIn("R-104", self.chosen_section(proc.stdout))

    def test_anchor_check_falls_back_outside_git_repo(self):
        """非 git repo（git grep 不可用）→ 退回 os.walk 掃描，錨點判定仍成立。"""
        plain = tempfile.TemporaryDirectory()
        self.addCleanup(plain.cleanup)
        with open(os.path.join(plain.name, "eval_gates.py"), "w", encoding="utf-8") as f:
            f.write("def _resolve_root(payload):\n    pass\n")
        proc = self.run_select(".claude/hooks/eval_gates.py", root=plain.name)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-102", self.chosen_section(proc.stdout))
        self.assertIn("R-104", self.retire_section(proc.stdout))


    # --- reviewer 手動觸發輪（🟡-1、🟡-4、🟡-5、🟡-6、🟡-7、🟡-9）的回歸鎖 ---

    def test_pathlike_anchor_existing_as_file_is_alive(self):
        """🟡-1 回歸鎖：檔名型錨點的檔案存在 → 選中（即使沒有任何檔案提及它的名字）。

        prose 明列錨點可以是「檔案」；只搜內容會把存在的 script 判成已消失。
        """
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-106", self.chosen_section(proc.stdout))
        self.assertNotIn("R-106", self.retire_section(proc.stdout))

    def test_pathlike_anchor_missing_file_is_dead(self):
        """🟡-1 反向：檔名型錨點的檔案已刪且無人提及 → retire 候選。"""
        os.remove(os.path.join(self.dir, "legacy_helper.py"))
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-106", self.retire_section(proc.stdout))
        self.assertNotIn("R-106", self.chosen_section(proc.stdout))

    def test_retired_with_empty_reason_still_excluded(self):
        """🟡-7 回歸鎖：`［retired ］`（原因欄為空）仍算退役，不得被選中。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("R-107", self.chosen_section(proc.stdout))
        self.assertNotIn("R-107", self.retire_section(proc.stdout))

    def test_anchor_with_regex_metacharacters_matched_literally(self):
        """🟡-6 回歸鎖：錨點含 `. * [ $` → 以字面搜內容命中（當 regex 會錯判）。"""
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-108", self.chosen_section(proc.stdout))

    def test_runid_segment_in_tag_does_not_match(self):
        """🟡-5 回歸鎖：片段只命中標籤尾端的 run_id 段 → 不選（prose：標籤第一段＝模組路徑）。"""
        proc = self.run_select("tests/test_retro_select.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("R-109", self.chosen_section(proc.stdout))

    def test_dead_anchor_recorded_only_in_usage_dir_still_dead(self):
        """🟡-4 回歸鎖：錨點只出現在 usage/（CLAUDE.md 明列的冷溯源）→ 仍判已消失。"""
        os.makedirs(os.path.join(self.dir, "usage"), exist_ok=True)
        with open(os.path.join(self.dir, "usage", "2026-07-17-y.md"), "w", encoding="utf-8") as f:
            f.write("舊情境報告提到 這個符號不存在於任何檔案 這個機制\n")
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-104", self.retire_section(proc.stdout))
        self.assertNotIn("R-104", self.chosen_section(proc.stdout))

    def test_retro_path_with_space_and_glob_chars(self):
        """🟡-6／N2 回歸鎖：`--retro` 路徑含空白與 `[`／`*` → pathspec 須用 literal。

        怪路徑的 retro 檔是**唯一**提及該錨點的檔案：
          排除生效（`:(exclude,literal)`）→ 錨點在 codebase 查無 → 條目落入 retire 候選
          排除失效（`:!` 被當 glob）→ git grep 在該檔自身命中 → 誤判「仍存在」而選中
        原版只斷言無錨點的 R-101 被選中，與排除是否生效無關，是假的回歸鎖（r2 🟡-N2）。
        """
        unique = "僅此怪檔提及的錨點符號"
        self.assertNotIn(unique, FIXTURE_RETRO)      # 前提：預設 fixture 不含該字串
        weird_dir = os.path.join(self.dir, "my [odd] dir")
        os.makedirs(weird_dir, exist_ok=True)
        weird = os.path.join(weird_dir, "RETRO *copy.md")
        with open(weird, "w", encoding="utf-8") as f:
            f.write("- R-301 2026-07-05［.claude/hooks／eval_gates／怪路徑／2026-07-05-t］"
                    f"背景。**約束：沿用它。**［錨點: {unique}］\n")
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py", retro=weird)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-301", self.retire_section(proc.stdout))
        self.assertNotIn("R-301", self.chosen_section(proc.stdout))

    def test_glob_sibling_file_is_not_over_excluded(self):
        """N2 回歸鎖：pathspec 須用 `:(exclude,literal)`，不可用 `:!`（會當 glob 過度排除）。

        佈局：`--retro` 路徑含 `*`，旁邊有一個符合該 glob 的兄弟檔，錨點**只在兄弟檔中**。
          literal（正確）→ 只排除條目檔自身 → 兄弟檔命中 → 錨點仍存在 → 條目選中
          `:!`（錯誤）  → 兄弟檔一併被排除 → 零命中 → 錨點誤判已消失 → 落入 retire 候選
        """
        unique = "兄弟檔才有的錨點符號"
        self.assertNotIn(unique, FIXTURE_RETRO)      # 前提：預設 fixture 不含該字串
        d = os.path.join(self.dir, "d")
        os.makedirs(d, exist_ok=True)
        weird = os.path.join(d, "RETRO *copy.md")
        with open(weird, "w", encoding="utf-8") as f:
            f.write("- R-302 2026-07-06［.claude/hooks／eval_gates／兄弟檔錨點／2026-07-06-s］"
                    f"背景。**約束：沿用它。**［錨點: {unique}］\n")
        with open(os.path.join(d, "RETRO xcopy.md"), "w", encoding="utf-8") as f:
            f.write(f"此檔字面提及 {unique}，且符合 `RETRO *copy.md` 這個 glob。\n")
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py", retro=weird)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-302", self.chosen_section(proc.stdout))
        self.assertNotIn("R-302", self.retire_section(proc.stdout))

    def test_symlinked_retro_path_still_excludes_the_entry_file(self):
        """N3 回歸鎖：`--retro` 是 symlink 時，排除須解到目標檔（否則條目檔自身被掃到）。

        錨點只出現在條目檔自己 → 正確行為是判「已消失」、落入 retire 候選。
        只排除 link 名稱（abspath 不解 symlink）→ 目標檔命中 → 誤判仍存在而被選中。
        """
        unique = "只有條目檔自己提及的錨點符號"
        self.assertNotIn(unique, FIXTURE_RETRO)
        real = os.path.join(self.dir, "real_retro.md")
        with open(real, "w", encoding="utf-8") as f:
            f.write("- R-303 2026-07-07［.claude/hooks／eval_gates／symlink 排除／2026-07-07-r］"
                    f"背景。**約束：沿用它。**［錨點: {unique}］\n")
        link = os.path.join(self.dir, "link_retro.md")
        os.symlink("real_retro.md", link)
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_select(".claude/hooks/eval_gates.py", retro=link)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-303", self.retire_section(proc.stdout))
        self.assertNotIn("R-303", self.chosen_section(proc.stdout))

    def test_retro_path_via_symlinked_ancestor_dir_still_excluded(self):
        """N4 回歸鎖：`--retro` 與 `--root` 拼法不同（祖先目錄是 symlink）時排除仍須生效。

        與上一條的機制不同：那條是 `--retro` 自己是 link，這條是**路徑中的目錄**是 link
        （macOS `/tmp` → `/private/tmp` 即此類）。abspath 只做字串正規化 → relpath 得到
        `../...` → 被當 repo 外而不排除 → 條目檔自身被掃到 → 錨點誤判仍存在。
        """
        unique = "經別名目錄才讀到的錨點符號"
        self.assertNotIn(unique, FIXTURE_RETRO)
        inner = os.path.join(self.dir, "RETRO_N4.md")
        with open(inner, "w", encoding="utf-8") as f:
            f.write("- R-304 2026-07-08［.claude/hooks／eval_gates／別名目錄／2026-07-08-q］"
                    f"背景。**約束：沿用它。**［錨點: {unique}］\n")
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        alias = os.path.join(self.tmp.name + "_alias")
        os.symlink(self.dir, alias)
        self.addCleanup(os.unlink, alias)
        proc = self.run_select(".claude/hooks/eval_gates.py",
                               retro=os.path.join(alias, "RETRO_N4.md"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("R-304", self.retire_section(proc.stdout))
        self.assertNotIn("R-304", self.chosen_section(proc.stdout))

    def test_argparse_error_is_exit_one(self):
        """🟡-N1 回歸鎖：參數錯誤 → exit 1（argparse 預設 2，DoD 寫使用錯誤 exit 1）。"""
        proc = subprocess.run([sys.executable, SCRIPT, "--bogus"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("參數錯誤", proc.stderr)

    def test_empty_files_argument_is_usage_error(self):
        """🟡-9：`--files ""` → exit 1（不靜默選出全部條目）。"""
        proc = self.run_select("")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("為空", proc.stderr)

    def test_unparsable_entry_line_warns(self):
        """🟡-7 第二部分：以 `- R-` 開頭但不符格式的行 → stderr 警告，不靜默略過。"""
        broken = os.path.join(self.dir, "broken.md")
        with open(broken, "w", encoding="utf-8") as f:
            f.write(FIXTURE_RETRO + "- R-999 格式壞掉沒有日期與標籤\n")
        proc = self.run_select(".claude/hooks/eval_gates.py", retro=broken)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("不符條目格式", proc.stderr)
        self.assertIn("R-999", proc.stderr)


if __name__ == "__main__":
    unittest.main()
