"""report_envelope_check.py 的黑箱行為測試。

依 R-005：跨進程執行契約（PostToolUse hook 投放路徑）以 subprocess 執行
script、餵 stdin、驗 exit code 與 stderr——不 import script 內部函式。
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "report_envelope_check.py")

STAMP = "* _2026-09-07 21:40 (claude-sonnet-5)_"


def compliant_report(subagent_type="task-verifier", with_keywords=True, self_check_count=1,
                      trailing_after_self_check=False, stamp_line=STAMP):
    """建 golden 合規（或依旗標破壞）報告文字，供各 row 共用，單一出處。"""
    lines = [stamp_line, ""]
    if subagent_type == "task-verifier" and with_keywords:
        lines += ["## 完成度", "全部完成", "## 憑據", "測試通過"]
    else:
        lines += ["## 內容", "一些報告內容"]
    for _ in range(self_check_count):
        lines.append("Self-check: 全部通過")
    if trailing_after_self_check:
        lines.append("多餘的一行")
    return "\n".join(lines)


def make_payload(subagent_type="task-verifier", report_text=None, tool_name="Agent",
                  status="completed", run_in_background=None):
    if report_text is None:
        report_text = compliant_report(subagent_type)
    tool_input = {"subagent_type": subagent_type}
    if run_in_background is not None:
        tool_input["run_in_background"] = run_in_background
    tool_response = {"content": [{"type": "text", "text": report_text}]}
    if status is not None:
        tool_response["status"] = status
    return {"tool_name": tool_name, "tool_input": tool_input, "tool_response": tool_response}


def run_hook(stdin_text):
    return subprocess.run(
        [sys.executable, SCRIPT], input=stdin_text, capture_output=True, text=True
    )


class ReportEnvelopeCheckTest(unittest.TestCase):
    # row 1: 合規報告 -> exit 0 無輸出
    def test_row1_compliant_task_verifier_passes(self):
        proc = run_hook(json.dumps(make_payload()))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")

    # row 2: 首行非戳記行 -> exit 2, stderr 含「戳記」
    def test_row2_missing_stamp_line_rejects(self):
        report = compliant_report(stamp_line="這不是戳記行")
        proc = run_hook(json.dumps(make_payload(report_text=report)))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("戳記", proc.stderr)

    # row 3: 無 Self-check 行 -> exit 2, stderr 含「Self-check」
    def test_row3_missing_self_check_rejects(self):
        report = "\n".join([STAMP, "", "## 完成度", "全部完成", "## 憑據", "測試通過"])
        proc = run_hook(json.dumps(make_payload(report_text=report)))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Self-check", proc.stderr)

    # row 4: Self-check 後仍有非空內容 -> exit 2, stderr 含「Self-check」
    def test_row4_content_after_self_check_rejects(self):
        report = compliant_report(trailing_after_self_check=True)
        proc = run_hook(json.dumps(make_payload(report_text=report)))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Self-check", proc.stderr)

    # row 5: Self-check 出現 2 次 -> exit 2
    def test_row5_duplicate_self_check_rejects(self):
        report = compliant_report(self_check_count=2)
        proc = run_hook(json.dumps(make_payload(report_text=report)))
        self.assertEqual(proc.returncode, 2)

    # row 6: task-verifier 合規信封但無「憑據」 -> exit 2, stderr 含「兩節」或「憑據」
    def test_row6_task_verifier_missing_keyword_rejects(self):
        report = compliant_report(subagent_type="task-verifier", with_keywords=False)
        proc = run_hook(json.dumps(make_payload(subagent_type="task-verifier", report_text=report)))
        self.assertEqual(proc.returncode, 2)
        self.assertTrue("兩節" in proc.stderr or "憑據" in proc.stderr)

    # row 7: subagent_type 不在信封名單 -> exit 0 不驗（故意用破損報告仍應放行）
    def test_row7_unlisted_subagent_skips_validation(self):
        broken_report = compliant_report(stamp_line="這不是戳記行")
        proc = run_hook(json.dumps(make_payload(subagent_type="Explore", report_text=broken_report)))
        self.assertEqual(proc.returncode, 0)

    # row 8: stdin 非 JSON / 缺 tool_response / tool_name 非 Task、Agent -> exit 0 (fail-open)
    def test_row8_invalid_json_fails_open(self):
        proc = run_hook("not a json string {{{")
        self.assertEqual(proc.returncode, 0)

    def test_row8_missing_tool_response_fails_open(self):
        payload = make_payload()
        del payload["tool_response"]
        proc = run_hook(json.dumps(payload))
        self.assertEqual(proc.returncode, 0)

    def test_row8_wrong_tool_name_fails_open(self):
        proc = run_hook(json.dumps(make_payload(tool_name="Bash")))
        self.assertEqual(proc.returncode, 0)

    # row 9: run_in_background 為 true -> exit 0 不驗
    def test_row9_background_launch_skips_validation(self):
        broken_report = compliant_report(stamp_line="這不是戳記行")
        proc = run_hook(json.dumps(
            make_payload(report_text=broken_report, run_in_background=True)
        ))
        self.assertEqual(proc.returncode, 0)

    # row 10: status 為 "failed" -> exit 0 不驗
    def test_row10_non_completed_status_skips_validation(self):
        broken_report = compliant_report(stamp_line="這不是戳記行")
        proc = run_hook(json.dumps(
            make_payload(report_text=broken_report, status="failed")
        ))
        self.assertEqual(proc.returncode, 0)

    # row 11: code-writer 合規信封（無兩節關鍵詞要求）-> exit 0
    def test_row11_code_writer_no_keyword_requirement_passes(self):
        report = compliant_report(subagent_type="code-writer")
        proc = run_hook(json.dumps(make_payload(subagent_type="code-writer", report_text=report)))
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
