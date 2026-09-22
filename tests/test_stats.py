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

    def _write_tier0_lines(self, lines):
        os.makedirs(self.run_dir, exist_ok=True)
        with open(os.path.join(self.run_dir, "tier0.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_tier0_absent_file_is_unrecorded(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        self.assertIsNone(data["tier0"])
        self.assertIn("Tier 0 留痕：無記錄", stats.report(data))

    def test_tier0_entries_counted_with_lines_and_last_ts(self):
        self.make_fixture()
        self._write_tier0_lines([
            json.dumps({"ts": "2026-09-06T01:00:00+00:00", "summary": "s1",
                        "files": ["a.py"], "lines": 10}),
            json.dumps({"ts": "2026-09-06T02:00:00+00:00", "summary": "s2",
                        "files": ["b.py"], "lines": 5}),
        ])
        data = stats.collect(self.run_dir)
        self.assertEqual(data["tier0"], {
            "count": 2, "lines": 15, "last_ts": "2026-09-06T02:00:00+00:00",
        })
        self.assertIn("Tier 0 留痕：2 筆／合計 15 行", stats.report(data))

    def test_tier0_bad_lines_skipped_without_crash(self):
        self.make_fixture()
        self._write_tier0_lines([
            "not-json{{{",
            json.dumps({"ts": "2026-09-06T01:00:00+00:00", "summary": "ok",
                        "files": ["a.py"], "lines": 3}),
            json.dumps({"ts": None, "summary": "lines 非 int", "files": [], "lines": "x"}),
        ])
        data = stats.collect(self.run_dir)
        self.assertEqual(data["tier0"]["count"], 2)  # 壞 JSON 行不計；合法 JSON 但欄位型別錯仍計筆數
        self.assertEqual(data["tier0"]["lines"], 3)  # lines 只加總 int
        self.assertEqual(data["tier0"]["last_ts"], "2026-09-06T01:00:00+00:00")

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

    def test_events_full_suite_count_from_verify_command(self):
        """全套測試次數（2026-09-21）：verify_cmd／add-verification 事件的 args.verify_command
        含 `--strike-key full_suite` 者計數；不含者不計。"""
        write(os.path.join(self.run_dir, "fs.json"), {"run_id": "fs", "tier": 1, "status": "completed"})
        self.write_events("fs", [
            {"ts": "2026-09-21T10:00:00+00:00", "cmd": "verify_cmd",
             "args": {"verify_command": "python3 .claude/hooks/test_baseline.py check --strike-key full_suite", "exit_code": 0}},
            {"ts": "2026-09-21T10:00:05+00:00", "cmd": "add-verification",
             "args": {"id": 1, "verify_command": "python3 .claude/hooks/test_baseline.py check --strike-key full_suite --run-id fs", "exit_code": 0}},
            {"ts": "2026-09-21T10:00:10+00:00", "cmd": "verify_cmd",
             "args": {"verify_command": "diff -q a b", "exit_code": 0}},
        ])
        data = stats.collect(self.run_dir)
        self.assertEqual(dict(data["events"])["fs"]["full_suite"], 2)
        self.assertIn("全套 2", stats.report(data))

    def test_events_full_suite_zero_when_legacy_events_lack_verify_command(self):
        """邊界：舊事件 args 無 verify_command 鍵 → full_suite=0、不 crash。"""
        write(os.path.join(self.run_dir, "old.json"), {"run_id": "old", "tier": 1, "status": "completed"})
        self.write_events("old", [
            {"ts": "2026-09-19T08:02:39+00:00", "cmd": "verify_cmd", "args": {"exit_code": 0}},
            {"ts": "2026-09-19T08:02:40+00:00", "cmd": "add-verification", "args": {"id": 1, "exit_code": 0}},
        ])
        data = stats.collect(self.run_dir)
        self.assertEqual(dict(data["events"])["old"]["full_suite"], 0)
        self.assertIn("全套 0", stats.report(data))

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
        self.assertNotIn("邊界直派", text)  # 零 boundary 不印

    def test_checker_escalation_boundary_dispatch_not_counted_as_escalation(self):
        """邊界直派（2026-09-21）：reviewer:boundary 另計，不入升級率分母與 reviewer 分佈。"""
        write(os.path.join(self.run_dir, "bd.json"), {"run_id": "bd", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "bd.eval.json"), {
            "run_id": "bd", "sub_tasks": [
                {"id": 1, "checked_by": "checker"},
                {"id": 2, "checked_by": "reviewer:boundary"},
                {"id": 3, "checked_by": "reviewer:①"},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["checked_by_direct"], 1)
        self.assertEqual(data["checked_by_escalated"], 1)
        self.assertEqual(data["checked_by_boundary"], 1)
        self.assertNotIn("reviewer:boundary", data["checked_by_dist"])
        text = stats.report(data)
        self.assertIn("checker 升級率：50%（1/2）", text)
        self.assertIn("邊界直派：1 個 sub_task", text)

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
            "subagent_usage": {"prep": 100, "loop": 400}, "token_usage": {},
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
        self.assertIn("前置/循環成本比：無實測記錄（需要 token_usage.py --write）", text)

    def test_subagent_usage_mixed_new_and_old_runs(self):
        write(os.path.join(self.run_dir, "new.json"), {
            "run_id": "new", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 50, "loop": 50}, "token_usage": {},
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
        self.assertIn("前置/循環成本比：無實測記錄", text)

    def test_subagent_usage_main_key_reported(self):
        """契約 row 1：含 main 的 run，輸出行含 main 數字與 main 合計。"""
        write(os.path.join(self.run_dir, "m1.json"), {
            "run_id": "m1", "tier": 2, "status": "completed",
            "subagent_usage": {"prep": 100, "loop": 400, "main": 300}, "token_usage": {},
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage_main"], [("m1", 300)])
        text = stats.report(data)
        self.assertIn("m1: prep 100／loop 400／main 300", text)
        self.assertIn("main 合計 300（1 個 run 有記錄）", text)

    def test_subagent_usage_without_main_unchanged(self):
        """契約 row 2：無 main 的 run 照舊輸出 prep/loop，不顯示 main、不報錯。"""
        write(os.path.join(self.run_dir, "nm.json"), {
            "run_id": "nm", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 50, "loop": 50}, "token_usage": {},
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage_main"], [])
        text = stats.report(data)
        self.assertIn("nm: prep 50／loop 50", text)
        self.assertNotIn("main", text.split("前置/循環成本比")[1].split("\n")[0])

    # --- token_usage 分流：只有實測 run 進成本比，舊制自報另計不併計 ---

    def test_legacy_self_reported_run_excluded_from_ratio(self):
        """契約 row 舊制：有 subagent_usage 無 token_usage → 不進清單、legacy=1、輸出含不併計句。"""
        write(os.path.join(self.run_dir, "lg.json"), {
            "run_id": "lg", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 0, "loop": 68161, "main": 50000},
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [])
        self.assertEqual(data["subagent_usage_main"], [])
        self.assertEqual(data["subagent_usage_legacy"], 1)
        self.assertEqual(data["subagent_usage_missing"], 0)
        text = stats.report(data)
        self.assertIn("前置/循環成本比：無實測記錄（需要 token_usage.py --write）", text)
        self.assertIn("舊制自報不併計：1 個 run", text)
        self.assertIn("無記錄：0 個 run", text)

    def test_measured_legacy_and_missing_runs_reported_in_three_segments(self):
        """契約 row 組合：實測＋舊制＋無記錄各一 → 清單 1、legacy 1、missing 1，三段皆出現，比值只算實測。"""
        write(os.path.join(self.run_dir, "ms.json"), {
            "run_id": "ms", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 1000, "loop": 4000, "main": 7000},
            "token_usage": {"session_id": "s", "window": None, "main": {}, "subagents": []},
        })
        write(os.path.join(self.run_dir, "lg.json"), {
            "run_id": "lg", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 999, "loop": 1},
        })
        write(os.path.join(self.run_dir, "none.json"), {"run_id": "none", "tier": 1, "status": "completed"})
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [("ms", 1000, 4000)])
        self.assertEqual(data["subagent_usage_legacy"], 1)
        self.assertEqual(data["subagent_usage_missing"], 1)
        text = stats.report(data)
        self.assertIn("前置/循環成本比（實測）：ms: prep 1000／loop 4000／main 7000", text)
        self.assertIn("prep:loop = 0.25", text)  # 舊制的 999/1 未混入
        self.assertIn("main 合計 7000（1 個 run 有記錄）", text)
        self.assertIn("舊制自報不併計：1 個 run", text)
        self.assertIn("無記錄：1 個 run", text)

    def test_token_usage_non_dict_treated_as_legacy(self):
        """契約 row 邊界：token_usage 非 dict → 視同舊制。"""
        write(os.path.join(self.run_dir, "nd.json"), {
            "run_id": "nd", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 1, "loop": 2}, "token_usage": "x",
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [])
        self.assertEqual(data["subagent_usage_legacy"], 1)

    def test_subagent_usage_main_non_int_skipped(self):
        """契約 row 3：main 非 int → main 寬容跳過，prep/loop 照常收。"""
        write(os.path.join(self.run_dir, "mb.json"), {
            "run_id": "mb", "tier": 1, "status": "completed",
            "subagent_usage": {"prep": 10, "loop": 20, "main": "300"}, "token_usage": {},
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["subagent_usage"], [("mb", 10, 20)])
        self.assertEqual(data["subagent_usage_main"], [])
        text = stats.report(data)
        self.assertIn("mb: prep 10／loop 20", text)

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
        self.assertIn("前置/循環成本比：無實測記錄（需要 token_usage.py --write）", text)

    # --- item 5.1：PER_TASK_CUTOFF 分母語義斷點（Q2/Q9，2026-09-22 起一筆＝task）---

    def test_period_helper_classifies_by_run_id_date_prefix(self):
        """_period()：日期 >= cutoff 歸新期，< cutoff 或無法解析歸舊期（保守，R-010）。"""
        self.assertEqual(stats._period("2026-09-22-tier2-slimming"), "new")
        self.assertEqual(stats._period("2026-09-23-some-slug"), "new")
        self.assertEqual(stats._period("2026-09-21-some-slug"), "old")
        self.assertEqual(stats._period("no-date-slug"), "old")
        self.assertEqual(stats._period("bogus-date-2026"), "old")
        self.assertEqual(stats._period(""), "old")

    def test_new_period_archive_counts_review_reds_and_checked_by_correctly(self):
        """新 per-task 歸檔（review_reds 在 task 層）→ rework／checked_by 正確累計進 `_new` 桶。"""
        write(os.path.join(self.run_dir, "2026-09-22-newtask.json"),
              {"run_id": "2026-09-22-newtask", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "2026-09-22-newtask.eval.json"), {
            "run_id": "2026-09-22-newtask", "sub_tasks": [
                {"id": 1, "review_reds": 1, "checked_by": "checker"},   # rework、直過
                {"id": 2, "review_reds": 0, "checked_by": "reviewer:①"},  # 不算 rework、升級
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["sub_tasks_new"], 2)
        self.assertEqual(data["rework_new"], 1)
        self.assertEqual(data["checked_by_direct_new"], 1)
        self.assertEqual(data["checked_by_escalated_new"], 1)
        self.assertEqual(data["checked_by_dist_new"]["reviewer:①"], 1)
        # 舊期分母完全不受影響（沒有任何舊歸檔）
        self.assertEqual(data["sub_tasks"], 0)
        self.assertEqual(data["rework"], 0)

    def test_new_period_missing_review_reds_and_checked_by_counted_as_no_record(self):
        """[邊界] 新形狀缺 review_reds／checked_by 鍵 → 計「無記錄」（checked_by_none_new），
        不誤判為 rework 或升級。"""
        write(os.path.join(self.run_dir, "2026-09-22-bare.json"),
              {"run_id": "2026-09-22-bare", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "2026-09-22-bare.eval.json"), {
            "run_id": "2026-09-22-bare", "sub_tasks": [{"id": 1}],  # 無 review_reds、無 checked_by
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["sub_tasks_new"], 1)
        self.assertEqual(data["rework_new"], 0)  # 無 review_reds、rounds 也空 → 不算 rework
        self.assertEqual(data["checked_by_none_new"], 1)
        self.assertEqual(data["checked_by_direct_new"], 0)
        self.assertEqual(data["checked_by_escalated_new"], 0)

    def test_mixed_old_and_new_archives_both_counted_and_breakpoint_labeled(self):
        """[組合] 新舊混合 run/ 目錄 → both 統計、分母語義照各自的 task/item 數；
        collect 不崩、report() 明確標示斷點（DoD④：fixture 坐實斷點標示出現在輸出中）。
        舊期與新期刻意取不同 rework 率（100% vs 50%），坐實兩期未被合併成單一趨勢——
        若程式誤合併分子分母，輸出會出現 2/3（67%）而非分別的 1/1 與 1/2。"""
        # 舊期：19 份真實歸檔的典型 flat 形狀（無頂層 review_reds → fallback rounds 數）；1/1 rework
        write(os.path.join(self.run_dir, "2026-07-16-old-item.json"),
              {"run_id": "2026-07-16-old-item", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "2026-07-16-old-item.eval.json"), {
            "run_id": "2026-07-16-old-item", "sub_tasks": [
                {"id": 1, "rounds": [{"round": 1}, {"round": 2}], "checked_by": "checker"},
            ],
        })
        # 新期：per-task 歸檔，2 個 task 只 1 個 rework → 1/2
        write(os.path.join(self.run_dir, "2026-09-22-new-task.json"),
              {"run_id": "2026-09-22-new-task", "tier": 2, "status": "completed"})
        write(os.path.join(self.run_dir, "2026-09-22-new-task.eval.json"), {
            "run_id": "2026-09-22-new-task", "sub_tasks": [
                {"id": 1, "review_reds": 1, "checked_by": "reviewer:②"},
                {"id": 2, "review_reds": 0, "checked_by": "checker"},
            ],
        })
        data = stats.collect(self.run_dir)
        self.assertEqual(data["sub_tasks"], 1)       # 舊期分母＝item 數
        self.assertEqual(data["rework"], 1)
        self.assertEqual(data["sub_tasks_new"], 2)   # 新期分母＝task 數
        self.assertEqual(data["rework_new"], 1)

        text = stats.report(data)
        self.assertIn(stats.PER_TASK_CUTOFF, text)  # 斷點日期出現在輸出中
        self.assertIn("此前分母＝item 數", text)
        self.assertIn("分母＝task 數", text)
        # 不得混算成單一趨勢：舊期 1/1（100%）與新期 1/2（50%）須分別可見，
        # 且不得出現誤合併的 2/3（67%）
        self.assertIn(stats.pct(1, 1), text)   # 舊期 rework：1/1
        self.assertIn(stats.pct(1, 2), text)   # 新期 rework：1/2
        self.assertNotIn(stats.pct(2, 3), text)  # 誤合併的錯誤值不得出現


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
