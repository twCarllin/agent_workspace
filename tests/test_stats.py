"""stats.py 遙測彙總的計算邏輯測試。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import stats  # noqa: E402

HOOKS_DIR = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks")


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

    # --- verification_commands 彙總 ---

    def test_verification_absent_key_is_unrecorded(self):
        """既有 run 皆無此欄位（後加的可選欄位）→ 不可拋例外，且明確報「無記錄」。"""
        write(os.path.join(self.run_dir, "old.json"),
              {"run_id": "old", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["verif_runs"], 0)
        self.assertEqual(data["verif_cmds"], 0)
        self.assertIn("驗證指令數：無記錄", stats.report(data))

    def test_verification_empty_list_is_recorded_zero(self):
        """空陣列＝有記錄但 0 條，與「無記錄」必須可區分（記錄了卻沒跑 vs 根本沒這欄位）。"""
        write(os.path.join(self.run_dir, "t1.json"), {
            "run_id": "t1", "tier": 1, "status": "completed",
            "verification_commands": [],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["verif_runs"], 1)
        self.assertEqual(data["verif_cmds"], 0)
        text = stats.report(data)
        self.assertIn("共 0 條／1 個有記錄的 run", text)
        self.assertNotIn("驗證指令數：無記錄", text)

    def test_verification_tier1_manifest_and_tier2_subtasks_mixed(self):
        """Tier 1 記在 manifest、Tier 2 記在各 sub_task、另有一個舊 run 無記錄。"""
        write(os.path.join(self.run_dir, "t1.json"), {
            "run_id": "t1", "tier": 1, "status": "completed",
            "verification_commands": [
                {"command": "pytest -q", "exit_code": 0},
                {"command": "ruff check .", "exit_code": 0},
            ],
        })
        write(os.path.join(self.run_dir, "t2.json"),
              {"run_id": "t2", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "t2.eval.json"), {
            "run_id": "t2", "sub_tasks": [
                {"id": 1, "review_reds": 0,
                 "verification_commands": [{"command": "pytest tests/a.py", "exit_code": 0}]},
                {"id": 2, "review_reds": 0,
                 "verification_commands": [
                     {"command": "pytest tests/b.py", "exit_code": 1},
                     {"command": "pytest tests/b.py", "exit_code": 0},
                 ]},
            ],
        })
        write(os.path.join(self.run_dir, "old.json"),
              {"run_id": "old", "tier": 1, "status": "completed"})

        data = stats.collect(self.run_dir)
        self.assertEqual(data["verif_runs"], 2)      # t1 + t2，old 不計入分母
        self.assertEqual(data["verif_cmds"], 5)      # 2 + 1 + 2
        text = stats.report(data)
        self.assertIn("共 5 條／2 個有記錄的 run", text)
        self.assertIn("平均 2.5 條", text)
        self.assertIn("無記錄：1 個 run", text)

    # --- 1c：aborted 計入 status 分佈（Counter 無寫死枚舉，加斷言即可，不改碼）---

    def test_aborted_status_counted_in_distribution(self):
        write(os.path.join(self.run_dir, "ab.json"),
              {"run_id": "ab", "tier": 1, "status": "aborted", "failed_reason": "使用者放棄"})
        write(os.path.join(self.run_dir, "ok.json"),
              {"run_id": "ok", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["statuses"]["aborted"], 1)
        self.assertEqual(data["statuses"]["completed"], 1)
        text = stats.report(data)
        self.assertIn("aborted", text)

    # --- 2c：events.jsonl 消費（事件數／時距／set-step 重入）---

    def write_events(self, run_id, lines):
        path = os.path.join(self.run_dir, f"{run_id}.events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def test_run_with_events_reports_count_span_and_reentry(self):
        write(os.path.join(self.run_dir, "ev.json"), {"run_id": "ev", "tier": 1, "status": "completed"})
        self.write_events("ev", [
            {"ts": "2026-08-20T10:00:00+00:00", "cmd": "init", "args": {"run_id": "ev"}},
            {"ts": "2026-08-20T10:00:05+00:00", "cmd": "add-subtask", "args": {"id": 1, "name": "x"}},
            {"ts": "2026-08-20T10:00:10+00:00", "cmd": "set-step", "args": {"id": 1, "step": "writing"}},
            {"ts": "2026-08-20T10:05:10+00:00", "cmd": "set-step", "args": {"id": 1, "step": "writing"}},
        ])
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertEqual(events["ev"]["count"], 4)
        self.assertEqual(events["ev"]["span_seconds"], 310.0)
        self.assertEqual(events["ev"]["reentry"], 1)  # 同 sub_task 同 step 出現 2 次 → 重入計 1
        text = stats.report(data)
        self.assertIn("事件記錄", text)
        self.assertIn("4 事件", text)

    def test_run_without_events_file_shows_no_record(self):
        write(os.path.join(self.run_dir, "noev.json"), {"run_id": "noev", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertIsNone(events["noev"])
        text = stats.report(data)
        self.assertIn("noev: 無記錄", text)

    def test_events_line_order_shuffled_does_not_change_span_or_reentry(self):
        """[邊界] events 行序被打亂 → 時距/重入不變（依 ts＋cmd+step，不依賴物理行序）。"""
        write(os.path.join(self.run_dir, "sh.json"), {"run_id": "sh", "tier": 1, "status": "completed"})
        in_order = [
            {"ts": "2026-08-20T10:00:00+00:00", "cmd": "set-step", "args": {"id": 1, "step": "writing"}},
            {"ts": "2026-08-20T10:00:20+00:00", "cmd": "set-step", "args": {"id": 1, "step": "fixing"}},
            {"ts": "2026-08-20T10:00:10+00:00", "cmd": "set-step", "args": {"id": 1, "step": "writing"}},
        ]
        shuffled = [in_order[1], in_order[2], in_order[0]]
        self.write_events("sh", shuffled)
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertEqual(events["sh"]["span_seconds"], 20.0)
        self.assertEqual(events["sh"]["reentry"], 1)  # (1,"writing") 出現 2 次

    def test_events_file_not_counted_as_run_manifest(self):
        """retro 約束（新衍生檔命名前置檢查）：events.jsonl 的 basename 不匹配 stats.py 的
        MANIFEST_RE（`.jsonl` 副檔名不匹配 `\\.json$`），不得被 run 計數誤判為 manifest。"""
        write(os.path.join(self.run_dir, "cnt.json"), {"run_id": "cnt", "tier": 1, "status": "completed"})
        self.write_events("cnt", [{"ts": "2026-08-20T10:00:00+00:00", "cmd": "init", "args": {}}])
        data = stats.collect(self.run_dir)
        self.assertEqual(sorted(data["runs"]), ["cnt"])  # events.jsonl 不算一個 run
        self.assertIsNone(stats.MANIFEST_RE.match("cnt.events.jsonl"))

    # events.jsonl 解析邊界覆蓋（retro：正常／含空白／含特殊字元／邊界各一條）

    def write_raw_events(self, run_id, raw_text):
        path = os.path.join(self.run_dir, f"{run_id}.events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_text)

    def test_events_file_skips_blank_lines_and_malformed_json(self):
        """含空白／邊界：空白行與壞掉的 JSON 行寬容跳過，不 crash、不誤計數。"""
        write(os.path.join(self.run_dir, "blank.json"), {"run_id": "blank", "tier": 1, "status": "completed"})
        raw = (
            '{"ts": "2026-08-20T10:00:00+00:00", "cmd": "init", "args": {}}\n'
            "\n"
            "   \n"
            "{not valid json}\n"
            '{"ts": "2026-08-20T10:00:05+00:00", "cmd": "set-step", "args": {"id": 1, "step": "writing"}}\n'
        )
        self.write_raw_events("blank", raw)
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertEqual(events["blank"]["count"], 2)  # 空白行與壞行不計入
        self.assertEqual(events["blank"]["span_seconds"], 5.0)

    def test_events_args_with_special_characters_preserved(self):
        """含特殊字元：中文、引號、換行字元的 arg 值原樣往返（json.dumps/loads 皆過 unicode escape）。"""
        write(os.path.join(self.run_dir, "spec.json"), {"run_id": "spec", "tier": 1, "status": "completed"})
        self.write_events("spec", [
            {"ts": "2026-08-20T10:00:00+00:00", "cmd": "set-test",
             "args": {"evidence": 'pytest -q -> 3 passed，含「引號」與換行\n特殊字元 🎉'}},
        ])
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertEqual(events["spec"]["count"], 1)
        with open(os.path.join(self.run_dir, "spec.events.jsonl"), encoding="utf-8") as f:
            raw_event = json.loads(f.readline())
        self.assertIn("🎉", raw_event["args"]["evidence"])

    def test_events_file_empty_reports_zero_count_and_no_span(self):
        """邊界：events.jsonl 存在但 0 行（無事件）→ count=0、span_seconds=None，不 crash。"""
        write(os.path.join(self.run_dir, "empty.json"), {"run_id": "empty", "tier": 1, "status": "completed"})
        self.write_raw_events("empty", "")
        data = stats.collect(self.run_dir)
        events = dict(data["events"])
        self.assertEqual(events["empty"]["count"], 0)
        self.assertIsNone(events["empty"]["span_seconds"])
        self.assertEqual(events["empty"]["reentry"], 0)

    # --- a. HITL 裁示數 ---

    def test_hitl_rulings_reported_with_distribution_and_average(self):
        write(os.path.join(self.run_dir, "hr1.json"),
              {"run_id": "hr1", "tier": 1, "status": "completed", "hitl_rulings": 3})
        write(os.path.join(self.run_dir, "hr2.json"),
              {"run_id": "hr2", "tier": 1, "status": "completed", "hitl_rulings": 1})
        data = stats.collect(self.run_dir)
        self.assertEqual(sorted(data["hitl_rulings"]), [1, 3])
        self.assertEqual(data["hitl_rulings_missing"], 0)
        text = stats.report(data)
        self.assertIn("HITL 裁示數", text)
        self.assertIn("平均 2.0", text)

    def test_hitl_rulings_missing_key_shows_no_record(self):
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["hitl_rulings"], [])
        self.assertEqual(data["hitl_rulings_missing"], 1)
        text = stats.report(data)
        self.assertIn("HITL 裁示數：無記錄（需要 hitl_rulings）", text)

    def test_hitl_rulings_mixed_new_and_old_runs(self):
        write(os.path.join(self.run_dir, "new.json"),
              {"run_id": "new", "tier": 1, "status": "completed", "hitl_rulings": 5})
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["hitl_rulings"], [5])
        self.assertEqual(data["hitl_rulings_missing"], 1)
        text = stats.report(data)
        self.assertIn("平均 5.0", text)
        self.assertIn("無記錄：1 個 run", text)

    # --- b. checker 升級率 ---

    def test_checker_escalation_rate_with_reviewer_distribution(self):
        write(os.path.join(self.run_dir, "ck.json"), {"run_id": "ck", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "ck.eval.json"), {
            "run_id": "ck", "sub_tasks": [
                {"id": 1, "checked_by": "checker"},
                {"id": 2, "checked_by": "checker"},
                {"id": 3, "checked_by": "reviewer:①"},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["checked_by_direct"], 2)
        self.assertEqual(data["checked_by_escalated"], 1)
        self.assertEqual(data["checked_by_dist"]["reviewer:①"], 1)
        text = stats.report(data)
        self.assertIn("checker 升級率：33%（1/3）", text)  # 2 直過 1 升級 → 33%

    def test_checker_escalation_null_checked_by_is_no_record(self):
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "old.eval.json"), {
            "run_id": "old", "sub_tasks": [
                {"id": 1, "checked_by": None},
                {"id": 2},  # 缺鍵
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["checked_by_direct"], 0)
        self.assertEqual(data["checked_by_escalated"], 0)
        self.assertEqual(data["checked_by_none"], 2)
        text = stats.report(data)
        self.assertIn("checker 升級率：無記錄（需要 checked_by）", text)

    def test_checker_escalation_mixed_recorded_and_unrecorded_sub_tasks(self):
        write(os.path.join(self.run_dir, "mix.json"), {"run_id": "mix", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "mix.eval.json"), {
            "run_id": "mix", "sub_tasks": [
                {"id": 1, "checked_by": "checker"},
                {"id": 2, "checked_by": None},  # 舊 sub_task 無記錄，不計分母
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["checked_by_direct"], 1)
        self.assertEqual(data["checked_by_none"], 1)
        text = stats.report(data)
        self.assertIn("checker 升級率：0%（0/1）", text)

    def test_checker_escalation_unknown_value_falls_into_dist_without_validation(self):
        """R-007：stats 不重列合法值清單，未知值原樣歸「其他」桶（升級側）計數顯示，不驗證。"""
        write(os.path.join(self.run_dir, "unk.json"), {"run_id": "unk", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "unk.eval.json"), {
            "run_id": "unk", "sub_tasks": [
                {"id": 1, "checked_by": "some_未知值"},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["checked_by_escalated"], 1)
        self.assertEqual(data["checked_by_dist"]["some_未知值"], 1)

    # --- c. 前置/循環成本比 ---

    def test_subagent_usage_reported_per_run_and_ratio(self):
        write(os.path.join(self.run_dir, "su.json"), {
            "run_id": "su", "tier": 2, "status": "completed",
            "subagent_usage": {"prep": 100, "loop": 400},
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [("su", 100, 400)])
        text = stats.report(data)
        self.assertIn("前置/循環成本比", text)
        self.assertIn("su: prep 100／loop 400", text)
        self.assertIn("prep:loop = 0.25", text)

    def test_subagent_usage_missing_key_shows_no_record(self):
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [])
        self.assertEqual(data["subagent_usage_missing"], 1)
        text = stats.report(data)
        self.assertIn("前置/循環成本比：無記錄（需要 subagent_usage）", text)

    def test_subagent_usage_mixed_new_and_old_runs(self):
        write(os.path.join(self.run_dir, "new.json"), {
            "run_id": "new", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 50, "loop": 50},
        })
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(len(data["subagent_usage"]), 1)
        self.assertEqual(data["subagent_usage_missing"], 1)
        text = stats.report(data)
        self.assertIn("無記錄：1 個 run", text)

    def test_subagent_usage_malformed_shapes_skipped_without_crash(self):
        """壞形狀：缺鍵、值非 dict、prep/loop 非 int——寬容跳過，不 crash。"""
        write(os.path.join(self.run_dir, "bad1.json"),
              {"run_id": "bad1", "tier": 1, "status": "completed", "subagent_usage": "not_a_dict"})
        write(os.path.join(self.run_dir, "bad2.json"), {
            "run_id": "bad2", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": "100", "loop": 400},
        })
        write(os.path.join(self.run_dir, "bad3.json"), {
            "run_id": "bad3", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 100},  # 缺 loop
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [])
        self.assertEqual(data["subagent_usage_missing"], 3)
        text = stats.report(data)  # 不 crash
        self.assertIn("前置/循環成本比：無記錄", text)

    # --- [邊界] 全部舊 run 無任何新欄 → 三節顯示無記錄、exit 0 不 crash ---

    def test_all_legacy_runs_show_no_record_for_all_three_new_metrics(self):
        write(os.path.join(self.run_dir, "legacy1.json"), {"run_id": "legacy1", "tier": 1, "status": "completed"})
        write(os.path.join(self.run_dir, "legacy2.json"), {"run_id": "legacy2", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "legacy2.eval.json"), {
            "run_id": "legacy2", "sub_tasks": [{"id": 1, "review_reds": 0}],
        })
        data = stats.collect(self.run_dir)
        text = stats.report(data)
        self.assertIn("HITL 裁示數：無記錄（需要 hitl_rulings）", text)
        self.assertIn("checker 升級率：無記錄（需要 checked_by）", text)
        self.assertIn("前置/循環成本比：無記錄（需要 subagent_usage）", text)


# --- 2.4：整合測試（跨 item）——真實 eval_state.py 子命令序列 → events.jsonl → stats 消費 ---

class EventsIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def run_eval_state(self, *argv):
        subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "eval_state.py"), *argv],
            check=True, capture_output=True, text=True,
        )

    def test_real_subcommand_sequence_consumed_correctly(self):
        run_id = "2026-08-20-int-test"
        self.run_eval_state("init", "--run-id", run_id)
        self.run_eval_state("add-subtask", "--id", "1", "--name", "demo")
        self.run_eval_state("set-step", "1", "writing")
        self.run_eval_state("set-step", "1", "writing")  # 重入：同 sub_task 同 step 第 2 次（重試信號）
        self.run_eval_state("set-files", "1", "src/a.py")
        self.run_eval_state("set-test", "1", "--passed", "--evidence", "pytest -> ok")
        self.run_eval_state("set-review", "1", "0")
        self.run_eval_state("set-verify", "1")
        self.run_eval_state("set-status", "1", "passed")
        self.run_eval_state("list-files")  # 唯讀，不應 append
        self.run_eval_state("archive")

        events_path = os.path.join("run", f"{run_id}.events.jsonl")
        self.assertTrue(os.path.exists(events_path))
        with open(events_path, encoding="utf-8") as f:
            n_lines = sum(1 for line in f if line.strip())
        # init／add-subtask／set-step×2／set-files／set-test／set-review／set-verify／set-status／archive = 10
        self.assertEqual(n_lines, 10)

        write(os.path.join("run", f"{run_id}.json"), {"run_id": run_id, "tier": 2, "status": "completed"})

        data = stats.collect("run")
        info = dict(data["events"])[run_id]
        self.assertEqual(info["count"], 10)
        self.assertEqual(info["reentry"], 1)
        self.assertIsNotNone(info["span_seconds"])
        self.assertGreaterEqual(info["span_seconds"], 0)

        text = stats.report(data)
        self.assertIn(f"{run_id}:", text)
        self.assertIn("重入 1", text)


if __name__ == "__main__":
    unittest.main()
