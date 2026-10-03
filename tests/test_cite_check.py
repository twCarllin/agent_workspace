"""cite_check.py（審查引文核實）契約測試。

對映 run 2026-10-03-deterministic-scripts 的 item 9.2 契約 row K1–K7。
一律以子程序黑箱執行真實 CLI 路徑（R-005）；staged 內容以真實 git index 建立，
不 mock `git show`——核實的對象就是 index，mock 掉等於沒測到契約。

執行：python3 -m pytest tests/test_cite_check.py -q
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".claude", "hooks", "cite_check.py")

STAGED = """def alpha(x):
    return x + 1


def beta(y):
    total = y * 2
    return total


def gamma(z):
    # 含 regex 有意義的字元：a.*b[0]$
    return z
"""


class CiteCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                    ["git", "config", "user.name", "T"]):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)
        self.write("src.py", STAGED)
        subprocess.run(["git", "add", "src.py"], cwd=self.dir, check=True, capture_output=True)
        # 刻意不 add：用於「檔案不在 staging」契約
        self.write("unstaged.py", "def delta():\n    pass\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_check(self, lines, cwd=None):
        argv = [sys.executable, SCRIPT, "--citations", "-"]
        return subprocess.run(argv, cwd=cwd or self.dir, input="\n".join(lines) + "\n",
                              capture_output=True, text=True)

    def test_k1_fragment_at_reported_line_is_ok(self):
        """K1：引文存在且行號相符 → ok、exit 0。"""
        proc = self.run_check(["src.py\t6\ttotal = y * 2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("src.py:6\tok", proc.stdout)
        self.assertIn("本批可用", proc.stdout)

    def test_k2_absent_fragment_is_rejected(self):
        """K2：引文不存在於 staged 內容 → 駁回（照修等於為幻覺改 code，R-012）。"""
        proc = self.run_check(["src.py\t6\treturn x * 999"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("駁回（引文不存在）", proc.stdout)
        self.assertIn("不得進 fixing", proc.stdout)

    def test_k3_line_drift_is_rewrite_not_rejection(self):
        """K3：文字為真、僅行號漂移 → 不駁回，輸出實得行號供改寫。"""
        proc = self.run_check(["src.py\t2\ttotal = y * 2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("src.py:2\t行號修正: 2→6", proc.stdout)
        # 「不是駁回」的精確判準：沒有駁回節、且摘要計數為 0
        # （不可斷言 stdout 無「駁回」二字——摘要行與節標題「不駁回」本就含它）
        self.assertNotIn("## 駁回（不得進 fixing", proc.stdout)
        self.assertIn("駁回 0", proc.stdout)

    def test_k4_three_rewrites_reject_whole_report(self):
        """K4：同一批行號修正達門檻 3 → exit 2、整份退回 reviewer 重審。"""
        proc = self.run_check([
            "src.py\t1\ttotal = y * 2",
            "src.py\t1\tdef beta(y):",
            "src.py\t1\tdef gamma(z):",
        ])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("整份退回 reviewer 重審", proc.stdout)
        self.assertIn("行號修正 3 條", proc.stdout)

    def test_k4b_two_rewrites_below_threshold_stay_usable(self):
        """K4 反向：2 條行號修正 < 門檻 → exit 0、本批可用（門檻不可提前觸發）。"""
        proc = self.run_check([
            "src.py\t1\ttotal = y * 2",
            "src.py\t1\tdef beta(y):",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("本批可用", proc.stdout)

    def test_k5_unstaged_file_is_rejected_not_crash(self):
        """K5：檔案不在 index → 駁回（檔案不在 staging），不拋例外。"""
        proc = self.run_check(["unstaged.py\t1\tdef delta():"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("駁回（檔案不在 staging）", proc.stdout)

    def test_k6_regex_metacharacters_matched_literally(self):
        """K6 [邊界]：引文含 . * [ $ → 字面比對命中（當 regex 會錯判）。"""
        proc = self.run_check(["src.py\t11\ta.*b[0]$"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("src.py:11\tok", proc.stdout)

    def test_k7_multiple_hits_lists_all_line_numbers(self):
        """K7 [邊界]：同一片段多行命中且報告行號不在其中 → 列出全部實得行號。"""
        self.write("multi.py", "x = 1\ny = 2\nx = 1\n")
        subprocess.run(["git", "add", "multi.py"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_check(["multi.py\t9\tx = 1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("行號修正: 9→1／3", proc.stdout)

    def test_multiple_hits_including_reported_line_is_ok(self):
        """多行命中但報告行號在其中 → ok（不必修正）。"""
        self.write("multi.py", "x = 1\ny = 2\nx = 1\n")
        subprocess.run(["git", "add", "multi.py"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_check(["multi.py\t3\tx = 1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("multi.py:3\tok", proc.stdout)

    def test_malformed_input_is_usage_error(self):
        """缺欄位的輸入 → exit 1（使用錯誤），不默默跳過該行。"""
        proc = self.run_check(["src.py\t6"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("格式錯誤", proc.stderr)

    def test_non_integer_line_is_usage_error(self):
        """行號不是整數 → exit 1。"""
        proc = self.run_check(["src.py\tsix\ttotal = y * 2"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("行號不是整數", proc.stderr)

    def test_empty_input_is_usage_error(self):
        """空輸入 → exit 1（避免「零引文」被誤讀為全部核實通過）。"""
        proc = subprocess.run([sys.executable, SCRIPT, "--citations", "-"], cwd=self.dir,
                              input="# 只有註解\n\n", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("沒有任何引文", proc.stderr)

    def test_comments_and_blank_lines_skipped(self):
        """`#` 註解與空行跳過，其餘照常核實。"""
        proc = self.run_check(["# 來自 reviewer r1 的引文", "", "src.py\t6\ttotal = y * 2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("引文 1 條", proc.stdout)
        self.assertIn("src.py:6\tok", proc.stdout)

    def test_fragment_containing_tab_preserved(self):
        """[邊界] 引文本身含 TAB → 第三欄之後全部視為片段，不被切斷。"""
        self.write("tabbed.py", "if x:\n\tif y:\n\t\treturn 1\n")
        subprocess.run(["git", "add", "tabbed.py"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_check(["tabbed.py\t3\t\t\treturn 1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tabbed.py:3\tok", proc.stdout)


    # --- reviewer 手動觸發輪（🔴-1、🟡-2、🟡-3、🟡-9）的回歸鎖 ---

    def test_line_numbers_match_grep_n_with_form_feed(self):
        """🔴-1 回歸鎖：含 \x0c 的檔，行號須與 `grep -n` 相同。

        str.splitlines() 會在 \x0c 額外斷行（實測 grep -n 得 3、splitlines 得 4），
        導致 script 輸出錯誤的「行號修正」而主 flow 照著改。
        """
        self.write("ff.txt", "a\nb\x0cc\nneedle here\nz\n")
        subprocess.run(["git", "add", "ff.txt"], cwd=self.dir, check=True, capture_output=True)
        grep = subprocess.run("git show :ff.txt | grep -n -F 'needle here'", cwd=self.dir,
                              shell=True, capture_output=True, text=True)
        grep_line = int(grep.stdout.split(":", 1)[0])
        proc = self.run_check([f"ff.txt\t{grep_line}\tneedle here"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"ff.txt:{grep_line}\tok", proc.stdout)

    def test_non_utf8_staged_file_does_not_raise(self):
        """🟡-2b 回歸鎖：staged 檔不是 UTF-8 時不得拋 UnicodeDecodeError traceback。"""
        path = os.path.join(self.dir, "bad.txt")
        with open(path, "wb") as f:
            f.write(b"\xe9\xff latin1 bytes\n")
        subprocess.run(["git", "add", "bad.txt"], cwd=self.dir, check=True, capture_output=True)
        proc = self.run_check(["bad.txt\t1\tlatin1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("bad.txt:1\tok", proc.stdout)

    def test_outside_git_repo_is_usage_error(self):
        """🟡-2a 回歸鎖：不在 git 工作區 → exit 1，不可把環境錯誤降級成逐條駁回。"""
        plain = tempfile.TemporaryDirectory()
        self.addCleanup(plain.cleanup)
        proc = self.run_check(["x.py\t1\tfoo"], cwd=plain.name)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("不在 git 工作區", proc.stderr)

    def test_threshold_flag_is_not_accepted(self):
        """🟡-3 回歸鎖：門檻不提供旗標（R-012：可調的門檻等於可關掉的 gate）。

        須斷言 **exit 1**，不可只斷言非 0——argparse 預設的參數錯誤碼是 2，與本 script
        的「整份退回 reviewer 重審」撞碼；只驗非 0 會把撞碼當通過（🟡-N1）。
        """
        proc = subprocess.run([sys.executable, SCRIPT, "--citations", "-", "--threshold", "99"],
                              cwd=self.dir, input="src.py\t6\ttotal = y * 2\n",
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--threshold", proc.stderr)

    def test_missing_required_arg_is_exit_one_not_two(self):
        """🟡-N1 回歸鎖：缺必填參數 → exit 1（不可是 argparse 預設的 2＝整份退回）。"""
        proc = subprocess.run([sys.executable, SCRIPT], cwd=self.dir,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("參數錯誤", proc.stderr)

    def test_two_rewrites_plus_one_rejection_stays_usable(self):
        """🟡-9：門檻只數行號修正。2 修正＋1 駁回 → exit 0（防門檻誤用 修正＋駁回 的和）。"""
        proc = self.run_check([
            "src.py\t1\ttotal = y * 2",
            "src.py\t1\tdef beta(y):",
            "src.py\t1\treturn x * 999",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("行號修正 2", proc.stdout)
        self.assertIn("駁回 1", proc.stdout)
        self.assertIn("本批可用", proc.stdout)

    def test_empty_fragment_is_usage_error(self):
        """🟡-9：引文片段為空 → exit 1（空片段會比對到每一行）。"""
        proc = self.run_check(["src.py\t6\t   "])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("片段為空", proc.stderr)

    def test_unreadable_citations_file_is_usage_error(self):
        """🟡-9：引文檔讀不到 → exit 1。"""
        proc = subprocess.run([sys.executable, SCRIPT, "--citations",
                               os.path.join(self.dir, "missing.tsv")],
                              cwd=self.dir, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("讀不到引文檔", proc.stderr)


if __name__ == "__main__":
    unittest.main()
