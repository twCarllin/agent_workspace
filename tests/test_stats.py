"""stats.py 遙測彙總的計算邏輯測試。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import stats  # noqa: E402


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class StatsCollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")

    def tearDown(self):
        self.tmp.cleanup()

    def make_fixture(self):
        write(os.path.join(self.run_dir, "r1.json"), {
            "run_id": "r1", "tier": 2, "status": "completed",
            "hitl_confirmed_at": "2026-07-15 10:00 — usage v1", "hitl_rejections": 1,
        })
        write(os.path.join(self.run_dir, "r1.eval.json"), {
            "run_id": "r1", "threshold": 6, "sub_tasks": [
                {"id": 1, "rounds": [
                    {"round": 1, "quality_score": 5, "review_reds": 0,
                     "deduction_reasons": [{"points_lost": 5, "dimension": "Completeness"}]},
                    {"round": 2, "quality_score": 8, "review_reds": 0,
                     "deduction_reasons": [{"points_lost": 2, "dimension": "Clarity"}]},
                ]},
                {"id": 2, "rounds": [
                    {"round": 1, "quality_score": 9, "review_reds": 2,
                     "deduction_reasons": [{"points_lost": 1, "dimension": "Clarity"}]},
                ]},
            ],
        })
        write(os.path.join(self.run_dir, "r1.test_baseline.json"), {
            "run_id": "r1", "stable_failures": ["a", "b"], "flaky": ["c"],
        })
        write(os.path.join(self.run_dir, "r2.json"), {
            "run_id": "r2", "tier": 1, "status": "completed",
            "test_policy": "waived_by_user",
        })
        with open(os.path.join(self.run_dir, "gate_hits.log"), "w", encoding="utf-8") as f:
            f.write("2026-07-15 10:00:00\teval_state.json 仍存在。須先歸檔\n")
            f.write("2026-07-15 11:00:00\teval_state.json 仍存在。須先歸檔\n")
            f.write("2026-07-15 12:00:00\t假測試 lint 未過（修測試）\n")

    def test_derived_files_not_counted_as_runs(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(sorted(data["runs"]), ["r1", "r2"])  # .eval / .test_baseline 不算

    def test_core_metrics(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(data["waived"], 1)
        self.assertEqual(data["hitl_confirmed"], 1)
        self.assertEqual(data["hitl_rejections"], 1)
        self.assertEqual(data["sub_tasks"], 2)
        self.assertEqual(data["rework"], 1)          # sub_task 1 有 2 rounds
        self.assertEqual(data["rounds_total"], 3)
        self.assertEqual(data["deduction_dims"]["Clarity"], 3)  # 2 + 1

    def test_scorer_unique_catch(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(data["scorer_rounds_with_review_data"], 3)
        # 只有 round(score=5, review_reds=0) 是 scorer 獨立抓到的
        self.assertEqual(data["scorer_unique_catch"], 1)

    def test_gate_hits_grouped(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(sum(data["gate_hits"].values()), 3)
        self.assertEqual(max(data["gate_hits"].values()), 2)  # 歸檔 gate 兩次

    def test_baseline_trend(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(data["baseline"], [("r1", 2, 1)])

    def test_report_renders_without_data(self):
        os.makedirs(self.run_dir, exist_ok=True)
        text = stats.report(stats.collect(self.run_dir))
        self.assertIn("尚無 run 資料", text)

    def test_gate_hits_shown_even_with_zero_runs(self):
        os.makedirs(self.run_dir, exist_ok=True)
        with open(os.path.join(self.run_dir, "gate_hits.log"), "w", encoding="utf-8") as f:
            f.write("2026-07-15 10:00:00\tphase 狀態機：呼叫 code-writer 被擋\n")
        text = stats.report(stats.collect(self.run_dir))
        self.assertIn("phase 狀態機", text)  # gate 攔截可能先於第一個完成的 run

    def test_report_renders_with_data(self):
        self.make_fixture()
        text = stats.report(stats.collect(self.run_dir))
        self.assertIn("waive 率", text)
        self.assertIn("scorer 獨立貢獻", text)


if __name__ == "__main__":
    unittest.main()
