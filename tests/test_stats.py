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
        # 新格式：頂層 review_reds（sub_task 1 有 review_reds=1 → rework；sub_task 2 無 reds=0）
        write(os.path.join(self.run_dir, "r1.eval.json"), {
            "run_id": "r1", "sub_tasks": [
                {
                    "id": 1,
                    "review_reds": 1,
                    "review_dimensions": {"Clarity": 2, "Completeness": 1},
                },
                {
                    "id": 2,
                    "review_reds": 0,
                    "review_dimensions": {"Clarity": 1},
                },
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
        self.assertEqual(data["rework"], 1)          # sub_task 1 有 review_reds=1
        # dim_counter（新欄位名稱）
        self.assertEqual(data["dim_counter"]["Clarity"], 3)   # 2 + 1
        self.assertEqual(data["dim_counter"]["Completeness"], 1)

    def test_gate_hits_grouped(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertEqual(sum(data["gate_hits"].values()), 3)
        self.assertEqual(max(data["gate_hits"].values()), 2)  # 歸檔 gate 兩次

    def test_baseline_trend(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        # 舊 baseline 檔的 flaky 欄位被忽略，只計 stable（向後相容）
        self.assertEqual(data["baseline"], [("r1", 2)])

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
        self.assertIn("rework 率", text)
        self.assertNotIn("scorer 獨立貢獻", text)

    # 新格式 rework：review_reds >= 1
    def test_rework_new_format_review_reds_gte1(self):
        write(os.path.join(self.run_dir, "rx.json"), {"run_id": "rx", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "rx.eval.json"), {
            "run_id": "rx",
            "sub_tasks": [
                {"id": 1, "review_reds": 1},   # rework
                {"id": 2, "review_reds": 0},   # 不算
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["sub_tasks"], 2)
        self.assertEqual(data["rework"], 1)

    # legacy 格式 rework：rounds >= 2（無頂層 review_reds）
    def test_rework_legacy_format_rounds_gte2(self):
        write(os.path.join(self.run_dir, "ry.json"), {"run_id": "ry", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "ry.eval.json"), {
            "run_id": "ry",
            "sub_tasks": [
                {"id": 1, "rounds": [{"round": 1}, {"round": 2}]},  # 2 rounds → rework
                {"id": 2, "rounds": [{"round": 1}]},                 # 1 round → 不算
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["sub_tasks"], 2)
        self.assertEqual(data["rework"], 1)

    # review_dimensions 統計
    def test_review_dimensions_counted_in_dim_counter(self):
        write(os.path.join(self.run_dir, "rz.json"), {"run_id": "rz", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "rz.eval.json"), {
            "run_id": "rz",
            "sub_tasks": [
                {"id": 1, "review_dimensions": {"Clarity": 3, "Testability": 1}},
                {"id": 2, "review_dimensions": {"Clarity": 2}},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["dim_counter"]["Clarity"], 5)
        self.assertEqual(data["dim_counter"]["Testability"], 1)
        self.assertFalse(data["has_legacy_dims"])

    # 新舊混合：維度分佈含 legacy 標註
    def test_mixed_new_and_legacy_dims(self):
        write(os.path.join(self.run_dir, "rm.json"), {"run_id": "rm", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "rm.eval.json"), {
            "run_id": "rm",
            "sub_tasks": [
                # 新格式
                {"id": 1, "review_reds": 1, "review_dimensions": {"Clarity": 2}},
                # legacy 格式（無 review_dimensions，用 rounds 的 deduction_reasons）
                {"id": 2, "rounds": [
                    {"round": 1, "deduction_reasons": [
                        {"points_lost": 3, "dimension": "Completeness"},
                    ]},
                ]},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["dim_counter"]["Clarity"], 2)
        self.assertEqual(data["dim_counter"]["Completeness"], 3)
        self.assertTrue(data["has_legacy_dims"])
        text = stats.report(data)
        self.assertIn("含 legacy 扣分權重", text)


if __name__ == "__main__":
    unittest.main()
