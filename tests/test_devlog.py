"""devlog.py 唯讀敘事 render 的行為測試。

執行：python3 -m unittest tests.test_devlog -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS_DIR = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks")
DEVLOG_PATH = os.path.join(HOOKS_DIR, "devlog.py")


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def write_raw(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class DevlogRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tier2_run_renders_four_sections_with_subtask_fields(self):
        """(a) 完整 Tier 2 產物 → stdout 含四節、sub_task 欄位正確；
        events 混入壞行 → 跳過該行、其餘照渲染。"""
        run_id = "t2-full"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 2, "created_at": "2026-09-01 09:00",
            "status": "completed", "phase": "completed",
            "tier_rationale": "多角色觸及金流",
            "spec_path": "spec/t2-full.md",
            "risk_report_path": "risk/t2-full.md",
            "usage_report_path": "usage/t2-full.md",
            "impact_report_path": "impact/t2-full.md",
            "task_file": "task/2026-09-01.md",
            "hitl_confirmed_at": "2026-09-01 10:00 — 確認 usage v1",
            "hitl_rejections": 2,
        })
        write(os.path.join(self.run_dir, f"{run_id}.eval.json"), {
            "run_id": run_id, "sub_tasks": [
                {
                    "id": 1, "name": "MARKER-SUBTASK-ALPHA", "status": "passed",
                    "review_reds": 1, "rounds": [{"round": 1}, {"round": 2}],
                    "local_test_evidence": "MARKER-EVIDENCE-ALPHA",
                    "verification_commands": [
                        {"command": "pytest -q", "exit_code": 0},
                        {"command": "ruff check .", "exit_code": 0},
                    ],
                },
            ],
        })
        raw_events = (
            '{"ts": "2026-09-01T09:00:00+00:00", "cmd": "init", "args": {}}\n'
            "{not valid json}\n"
            '{"ts": "2026-09-01T09:05:00+00:00", "cmd": "MARKER-EVENT-CMD", "args": {}}\n'
        )
        write_raw(os.path.join(self.run_dir, f"{run_id}.events.jsonl"), raw_events)

        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, run_id, "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        # 四節齊
        self.assertIn("①run 概要", out)
        self.assertIn("②前置軌跡", out)
        self.assertIn("③sub_task", out)
        self.assertIn("④時間線", out)
        # ①②：manifest 欄位（含前置軌跡四路徑＋hitl）
        self.assertIn("t2-full", out)
        self.assertIn("多角色觸及金流", out)
        self.assertIn("risk/t2-full.md", out)
        self.assertIn("usage/t2-full.md", out)
        self.assertIn("impact/t2-full.md", out)
        self.assertIn("task/2026-09-01.md", out)
        self.assertIn("確認 usage v1", out)
        self.assertIn("hitl_rejections: 2", out)
        # ③：sub_task 欄位正確（來自 eval.json fixture）
        self.assertIn("MARKER-SUBTASK-ALPHA", out)
        self.assertIn("review_reds=1", out)
        self.assertIn("rounds=2", out)
        self.assertIn("MARKER-EVIDENCE-ALPHA", out)
        self.assertIn("verification_commands=2", out)
        # ④：壞行跳過、其餘照渲染
        self.assertIn("MARKER-EVENT-CMD", out)
        self.assertNotIn("not valid json", out)

    def test_tier1_run_without_eval_json_falls_back_to_manifest_credentials(self):
        """(b) Tier 1（無 eval.json）→ 第③節 fallback 到 manifest 四憑據欄。"""
        run_id = "t1-fallback"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "status": "completed", "phase": "decomposed",
            "spec_inline": "MARKER-SPEC-INLINE",
            "local_test_passed": True,
            "local_test_evidence": "MARKER-TIER1-EVIDENCE",
            "review_reds": 0,
            "verify_passed": True,
        })
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, run_id, "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        self.assertIn("MARKER-SPEC-INLINE", out)
        self.assertIn("Tier 1：無 eval.json", out)
        self.assertIn("local_test_passed=True", out)
        self.assertIn("MARKER-TIER1-EVIDENCE", out)
        self.assertIn("verify_passed=True", out)
        self.assertIn("無事件記錄", out)  # 無 events 檔

    def test_no_events_file_shows_no_record_without_crash(self):
        """(c) 無 events 檔 → 顯示「無事件記錄」，不 crash。"""
        run_id = "no-events"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "status": "completed",
        })
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, run_id, "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("無事件記錄", result.stdout)

    def test_list_mode_finds_manifests_under_non_default_dir(self):
        """清單模式（無 run_id）在非字面 "run" 的 --dir（此處為 tmp 下的絕對路徑）下
        仍須找到合法 manifest，且排除 `.eval.json` 干擾檔（MANIFEST_RE 排除生效）。"""
        write(os.path.join(self.run_dir, "list-a.json"), {"run_id": "list-a", "tier": 1})
        write(os.path.join(self.run_dir, "list-b.json"), {"run_id": "list-b", "tier": 2})
        write(os.path.join(self.run_dir, "list-a.eval.json"), {"run_id": "list-EVAL-LEAK", "sub_tasks": []})
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("list-a", result.stdout)
        self.assertIn("list-b", result.stdout)
        self.assertNotIn("list-EVAL-LEAK", result.stdout)

    def test_nonexistent_run_id_exits_nonzero_with_stderr_and_no_stdout(self):
        """[邊界] run_id 不存在 → exit code 非 0、stderr 提示、stdout 無輸出。"""
        os.makedirs(self.run_dir, exist_ok=True)
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, "nonexistent-run-id", "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
