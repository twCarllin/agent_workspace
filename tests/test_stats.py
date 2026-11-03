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


def M(rid, **extra):
    """最小 run manifest。"""
    return {"run_id": rid, "tier": 1, "status": "completed", **extra}


def pick(data, key):
    """key 為 tuple 時逐層取值（如 ("dim_counter", "Clarity")）。"""
    if isinstance(key, tuple):
        for k in key:
            data = data[k]
        return data
    return data[key]


class StatsCollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, files):
        for name, obj in files.items():
            write(os.path.join(self.run_dir, name), obj)

    def events_file(self, run_id, raw):
        path = os.path.join(self.run_dir, f"{run_id}.events.jsonl")
        os.makedirs(self.run_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)

    def write_events(self, run_id, rows):
        self.events_file(run_id, "".join(json.dumps(r) + "\n" for r in rows))

    def test_first_round_rework_counts_old_and_new_shapes(self):
        self.put(
            {
                "r.json": {"run_id": "r"},
                "r.eval.json": {
                    "sub_tasks": [
                        {
                            "review_reds": 0,
                            "review_rounds": [{"review_reds": 2}, {"review_reds": 0}],
                        },
                        {"first_review_reds": 0},
                        {"review_reds": 0},
                        {"review_reds": 1},
                        {"rounds": [{"round": 1}, {"round": 2}]},
                    ]
                },
            }
        )
        data = stats.collect(self.run_dir)
        self.assertEqual(
            (data["rework"], data["rework_recorded"], data["rework_missing"]), (1, 2, 3)
        )

    def make_fixture(self):
        self.put(
            {
                "r1.json": {
                    "run_id": "r1",
                    "tier": 2,
                    "status": "completed",
                    "hitl_confirmed_at": "2026-07-15 10:00 — usage v1",
                    "hitl_rejections": 1,
                },
                "r1.eval.json": {
                    "run_id": "r1",
                    "sub_tasks": [
                        {
                            "id": 1,
                            "first_review_reds": 1,
                            "review_reds": 1,
                            "review_dimensions": {"Clarity": 2, "Completeness": 1},
                        },
                        {
                            "id": 2,
                            "first_review_reds": 0,
                            "review_reds": 0,
                            "review_dimensions": {"Clarity": 1},
                        },
                    ],
                },
                "r1.test_baseline.json": {
                    "run_id": "r1",
                    "stable_failures": ["a", "b"],
                    "flaky": ["c"],
                },
                "r2.json": {
                    "run_id": "r2",
                    "tier": 1,
                    "status": "completed",
                    "test_policy": "waived_by_user",
                },
            }
        )
        with open(os.path.join(self.run_dir, "gate_hits.log"), "w", encoding="utf-8") as f:
            f.write("2026-07-15 10:00:00\teval_state.json 仍存在。須先歸檔\n")
            f.write("2026-07-15 11:00:00\teval_state.json 仍存在。須先歸檔\n")
            f.write("2026-07-15 12:00:00\t假測試 lint 未過（修測試）\n")

    def test_fixture_core_metrics_runs_gate_hits_and_baseline(self):
        self.make_fixture()
        data = stats.collect(self.run_dir)
        expect = {
            "waived": 1,
            "hitl_confirmed": 1,
            "hitl_rejections": 1,
            "sub_tasks": 2,
            "rework": 1,
            ("dim_counter", "Clarity"): 3,
            ("dim_counter", "Completeness"): 1,
            "gate_hits": {"legacy": 3},
            # 舊 baseline 檔的 flaky 欄位被忽略，只計 stable（向後相容）
            "baseline": [("r1", 2)],
        }
        for key, value in expect.items():
            self.assertEqual(pick(data, key), value, key)
        self.assertEqual(sorted(data["runs"]), ["r1", "r2"])  # .eval/.test_baseline 不算 run
        text = stats.report(data)
        self.assertIn("waive 率", text)
        self.assertIn("rework 率", text)

    def test_structured_gate_ids_and_legacy_coexist(self):
        os.makedirs(self.run_dir, exist_ok=True)
        rows = [
            {"gate_id": "gate.manifest_missing", "message": f"run/{n}.json 不存在", "outcome": "blocked"}
            for n in ("alpha", "beta")
        ]
        path = Path(self.run_dir) / "gate_hits.log"
        path.write_text(
            "2026-07-15 10:00:00\t舊訊息含路徑 run/old.json\n"
            + "\n".join(json.dumps(row) for row in rows)
            + "\n"
        )
        data = stats.collect(self.run_dir)
        self.assertEqual(data["gate_hits"], {"legacy": 1, "gate.manifest_missing": 2})
        self.assertEqual(len(data["gate_hit_lines"]), 3)
        text = stats.report(data)
        self.assertIn("gate.manifest_missing", text)
        self.assertNotIn("run/alpha.json", text)

    def test_collect_and_report_metric_table(self):
        """(情境, 檔案, collect 期望值)。"""
        cases = [
            # --- rework ---
            (
                "rework_new_format_review_reds_gte1",
                {
                    "rx.json": M("rx", tier=1),
                    "rx.eval.json": {
                        "run_id": "rx",
                        "sub_tasks": [
                            {"id": 1, "first_review_reds": 1, "review_reds": 1},
                            {"id": 2, "first_review_reds": 0, "review_reds": 0},
                        ],
                    },
                },
                {"sub_tasks": 2, "rework": 1},
            ),
            (
                # legacy rounds 數不能推定首輪紅數
                "rework_legacy_rounds_unrecorded",
                {
                    "ry.json": M("ry"),
                    "ry.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "rounds": [{"round": 1}, {"round": 2}]},
                            {"id": 2, "rounds": [{"round": 1}]},
                        ]
                    },
                },
                {"sub_tasks": 2, "rework": 0, "rework_recorded": 0, "rework_missing": 2},
            ),
            # --- review_dimensions ---
            (
                "dims_new_format",
                {
                    "rz.json": M("rz"),
                    "rz.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "review_dimensions": {"Clarity": 3, "Testability": 1}},
                            {"id": 2, "review_dimensions": {"Clarity": 2}},
                        ]
                    },
                },
                {
                    ("dim_counter", "Clarity"): 5,
                    ("dim_counter", "Testability"): 1,
                    "has_legacy_dims": False,
                },
            ),
            (
                "dims_mixed_new_and_legacy",
                {
                    "rm.json": M("rm", tier=2),
                    "rm.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "review_reds": 1, "review_dimensions": {"Clarity": 2}},
                            {
                                "id": 2,
                                "rounds": [
                                    {
                                        "round": 1,
                                        "deduction_reasons": [
                                            {"points_lost": 3, "dimension": "Completeness"}
                                        ],
                                    }
                                ],
                            },
                        ]
                    },
                },
                {
                    ("dim_counter", "Clarity"): 2,
                    ("dim_counter", "Completeness"): 3,
                    "has_legacy_dims": True,
                },
            ),
            # --- verification_commands ---
            (
                # 既有 run 皆無此欄位 → 不拋例外、報「無記錄」
                "verification_absent_key_unrecorded",
                {"old.json": M("old")},
                {"verif_runs": 0, "verif_cmds": 0},
            ),
            (
                # 空陣列＝有記錄但 0 條，與「無記錄」可區分
                "verification_empty_list_recorded_zero",
                {"t1.json": M("t1", verification_commands=[])},
                {"verif_runs": 1, "verif_cmds": 0},
            ),
            (
                "verification_tier1_manifest_and_tier2_subtasks_mixed",
                {
                    "t1.json": M(
                        "t1",
                        verification_commands=[
                            {"command": "pytest -q", "exit_code": 0},
                            {"command": "ruff check .", "exit_code": 0},
                        ],
                    ),
                    "t2.json": M("t2", tier=2),
                    "t2.eval.json": {
                        "sub_tasks": [
                            {
                                "id": 1,
                                "review_reds": 0,
                                "verification_commands": [{"command": "a", "exit_code": 0}],
                            },
                            {
                                "id": 2,
                                "review_reds": 0,
                                "verification_commands": [
                                    {"command": "b", "exit_code": 1},
                                    {"command": "b", "exit_code": 0},
                                ],
                            },
                        ]
                    },
                    "old.json": M("old"),
                },
                {"verif_runs": 2, "verif_cmds": 5},
            ),
            # --- 1c：aborted 計入 status 分佈 ---
            (
                "aborted_status_in_distribution",
                {"ab.json": M("ab", status="aborted", failed_reason="x"), "ok.json": M("ok")},
                {("statuses", "aborted"): 1, ("statuses", "completed"): 1},
            ),
            # --- HITL 裁示數 ---
            (
                "hitl_rulings_missing_key",
                {"old.json": M("old")},
                {"hitl_rulings": [], "hitl_rulings_missing": 1},
            ),
            (
                "hitl_rulings_mixed_new_and_old",
                {"new.json": M("new", hitl_rulings=5), "old.json": M("old")},
                {"hitl_rulings": [5], "hitl_rulings_missing": 1},
            ),
            # --- checker 升級率 ---
            (
                "checker_escalation_with_reviewer_distribution",
                {
                    "ck.json": M("ck"),
                    "ck.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "checked_by": "checker"},
                            {"id": 2, "checked_by": "checker"},
                            {"id": 3, "checked_by": "reviewer:①"},
                        ]
                    },
                },
                {
                    "checked_by_direct": 2,
                    "checked_by_escalated": 1,
                    ("checked_by_dist", "reviewer:①"): 1,
                },  # 零 boundary 不印
            ),
            (
                # 2026-09-21：reviewer:boundary 另計，不入升級率分母與 reviewer 分佈
                "checker_escalation_boundary_dispatch_separate",
                {
                    "bd.json": M("bd", tier=2),
                    "bd.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "checked_by": "checker"},
                            {"id": 2, "checked_by": "reviewer:boundary"},
                            {"id": 3, "checked_by": "reviewer:①"},
                        ]
                    },
                },
                {"checked_by_direct": 1, "checked_by_escalated": 1, "checked_by_boundary": 1},
            ),
            (
                "checker_escalation_null_or_missing_is_no_record",
                {
                    "old.json": M("old"),
                    "old.eval.json": {"sub_tasks": [{"id": 1, "checked_by": None}, {"id": 2}]},
                },
                {"checked_by_direct": 0, "checked_by_escalated": 0, "checked_by_none": 2},
            ),
            (
                "checker_escalation_mixed_recorded_and_unrecorded",
                {
                    "mix.json": M("mix", tier=2),
                    "mix.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "checked_by": "checker"},
                            {"id": 2, "checked_by": None},  # 無記錄不計分母
                        ]
                    },
                },
                {"checked_by_direct": 1, "checked_by_none": 1},
            ),
            (
                # R-007：stats 不重列合法值清單，未知值原樣歸升級側計數，不驗證
                "checker_escalation_unknown_value_unvalidated",
                {
                    "unk.json": M("unk"),
                    "unk.eval.json": {"sub_tasks": [{"id": 1, "checked_by": "some_未知值"}]},
                },
                {"checked_by_escalated": 1, ("checked_by_dist", "some_未知值"): 1},
            ),
            # --- 前置/循環成本比 ---
            (
                "subagent_usage_per_run_and_ratio",
                {"su.json": M("su", tier=2, subagent_usage={"prep": 100, "loop": 400}, token_usage={})},
                {"subagent_usage": [("su", 100, 400)]},
            ),
            (
                "subagent_usage_missing_key",
                {"old.json": M("old")},
                {"subagent_usage": [], "subagent_usage_missing": 1},
            ),
            (
                # 壞形狀：值非 dict、prep 非 int、缺 loop → 寬容跳過，不 crash
                "subagent_usage_malformed_shapes_skipped",
                {
                    "bad1.json": M("bad1", subagent_usage="not_a_dict"),
                    "bad2.json": M("bad2", subagent_usage={"prep": "100", "loop": 400}),
                    "bad3.json": M("bad3", subagent_usage={"prep": 100}),
                },
                {"subagent_usage": [], "subagent_usage_missing": 3},
            ),
            (
                "subagent_usage_row1_main_key_reported",
                {
                    "m1.json": M(
                        "m1",
                        tier=2,
                        subagent_usage={"prep": 100, "loop": 400, "main": 300},
                        token_usage={},
                    )
                },
                {"subagent_usage_main": [("m1", 300)]},
            ),
            (
                # 舊制：有 subagent_usage 無 token_usage → 不進清單、legacy=1
                "subagent_usage_legacy_self_reported_excluded",
                {"lg.json": M("lg", subagent_usage={"prep": 0, "loop": 68161, "main": 50000})},
                {
                    "subagent_usage": [],
                    "subagent_usage_main": [],
                    "subagent_usage_legacy": 1,
                    "subagent_usage_missing": 0,
                },
            ),
            (
                # 組合：實測＋舊制＋無記錄各一，比值只算實測（舊制 999/1 未混入）
                "subagent_usage_measured_legacy_missing_three_segments",
                {
                    "ms.json": M(
                        "ms",
                        subagent_usage={"prep": 1000, "loop": 4000, "main": 7000},
                        token_usage={"session_id": "s", "window": None, "main": {}, "subagents": []},
                    ),
                    "lg.json": M("lg", subagent_usage={"prep": 999, "loop": 1}),
                    "none.json": M("none"),
                },
                {
                    "subagent_usage": [("ms", 1000, 4000)],
                    "subagent_usage_legacy": 1,
                    "subagent_usage_missing": 1,
                },
            ),
            (
                "subagent_usage_token_usage_non_dict_is_legacy",
                {"nd.json": M("nd", subagent_usage={"prep": 1, "loop": 2}, token_usage="x")},
                {"subagent_usage": [], "subagent_usage_legacy": 1},
            ),
            (
                "subagent_usage_row3_main_non_int_skipped",
                {
                    "mb.json": M(
                        "mb",
                        subagent_usage={"prep": 10, "loop": 20, "main": "300"},
                        token_usage={},
                    )
                },
                {"subagent_usage": [("mb", 10, 20)], "subagent_usage_main": []},
            ),
            # --- PER_TASK_CUTOFF 之後（2026-09-22 起一筆＝task）---
            (
                "new_period_counts_review_reds_and_checked_by",
                {
                    "2026-09-22-newtask.json": M("2026-09-22-newtask", tier=2),
                    "2026-09-22-newtask.eval.json": {
                        "sub_tasks": [
                            {"id": 1, "first_review_reds": 1, "review_reds": 1, "checked_by": "checker"},
                            {"id": 2, "first_review_reds": 0, "review_reds": 0, "checked_by": "reviewer:①"},
                        ]
                    },
                },
                {
                    "sub_tasks_new": 2,
                    "rework_new": 1,
                    "checked_by_direct_new": 1,
                    "checked_by_escalated_new": 1,
                    ("checked_by_dist_new", "reviewer:①"): 1,
                    "sub_tasks": 0,  # 舊期分母不受影響
                    "rework": 0,
                },
            ),
            (
                # 新形狀缺 review_reds／checked_by → 計「無記錄」，不誤判 rework 或升級
                "new_period_missing_fields_counted_as_no_record",
                {
                    "2026-09-22-bare.json": M("2026-09-22-bare", tier=2),
                    "2026-09-22-bare.eval.json": {"sub_tasks": [{"id": 1}]},
                },
                {
                    "sub_tasks_new": 1,
                    "rework_new": 0,
                    "checked_by_none_new": 1,
                    "checked_by_direct_new": 0,
                    "checked_by_escalated_new": 0,
                },
            ),
        ]
        for name, files, expect in cases:
            with self.subTest(name):
                self.run_dir = os.path.join(self.tmp.name, name)
                self.put(files)
                data = stats.collect(self.run_dir)
                for key, value in expect.items():
                    self.assertEqual(pick(data, key), value, key)

    def test_events_metrics_table(self):
        """(情境, 事件列或原文, 期望 count/span/reentry/full_suite 子集)。"""

        def ev(ts, cmd, **args):
            return {"ts": f"2026-08-20T10:{ts}+00:00", "cmd": cmd, "args": args}

        fs = "python3 .claude/hooks/test_baseline.py check --strike-key full_suite"
        cases = [
            (
                # 同 sub_task 同 step 出現 2 次 → 重入計 1
                "count_span_and_reentry",
                [
                    ev("00:00", "init", run_id="ev"),
                    ev("00:05", "add-subtask", id=1, name="x"),
                    ev("00:10", "set-step", id=1, step="writing"),
                    ev("05:10", "set-step", id=1, step="writing"),
                ],
                {"count": 4, "span_seconds": 310.0, "reentry": 1},
            ),
            (
                # 2026-09-21：args.verify_command 含 `--strike-key full_suite` 者計數
                "full_suite_count_from_verify_command",
                [
                    ev("00:00", "verify_cmd", verify_command=fs, exit_code=0),
                    ev("00:05", "add-verification", id=1, verify_command=fs + " --run-id fs", exit_code=0),
                    ev("00:10", "verify_cmd", verify_command="diff -q a b", exit_code=0),
                ],
                {"full_suite": 2},
            ),
            (
                # 空白行與壞 JSON 行寬容跳過，不計數
                "blank_and_malformed_lines_skipped",
                "\n".join(
                    [
                        json.dumps(ev("00:00", "init")),
                        "",
                        "   ",
                        "{not valid json}",
                        json.dumps(ev("00:05", "set-step", id=1, step="writing")),
                    ]
                )
                + "\n",
                {"count": 2, "span_seconds": 5.0},
            ),
            (
                # events.jsonl 存在但 0 行 → count=0、span=None
                "empty_file",
                "",
                {"count": 0, "span_seconds": None, "reentry": 0},
            ),
        ]
        for name, rows, expect in cases:
            with self.subTest(name):
                self.run_dir = os.path.join(self.tmp.name, name)
                self.put({"ev.json": M("ev")})
                if isinstance(rows, str):
                    self.events_file("ev", rows)
                else:
                    self.write_events("ev", rows)
                data = stats.collect(self.run_dir)
                info = dict(data["events"])["ev"]
                for key, value in expect.items():
                    self.assertEqual(info[key], value, key)

    def test_events_and_context_files_not_counted_as_run_manifest(self):
        # retro：新衍生檔命名前置檢查——這些 basename 不得匹配 MANIFEST_RE
        self.put({"cnt.json": M("cnt")})
        self.write_events("cnt", [{"ts": "2026-08-20T10:00:00+00:00", "cmd": "init", "args": {}}])
        for name in ("cnt.context.json", "cnt.context.writer.json"):
            self.put({name: {"run_id": "cnt"}})
            self.assertIsNone(stats.MANIFEST_RE.match(name))
        self.assertIsNone(stats.MANIFEST_RE.match("cnt.events.jsonl"))
        self.assertEqual(sorted(stats.collect(self.run_dir)["runs"]), ["cnt"])

class EventsIntegrationTest(unittest.TestCase):
    """跨 item 整合：真實 eval_state.py 子命令序列 → events.jsonl → stats 消費。"""

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
            check=True,
            capture_output=True,
            text=True,
        )

    def test_real_subcommand_sequence_consumed_correctly(self):
        run_id = "2026-08-20-int-test"
        self.run_eval_state("init", "--run-id", run_id)
        self.run_eval_state("add-subtask", "--id", "1", "--name", "demo")
        self.run_eval_state("set-step", "1", "writing")
        self.run_eval_state("set-step", "1", "writing")  # 重入：同 sub_task 同 step 第 2 次
        self.run_eval_state("set-files", "1", "src/a.py")
        self.run_eval_state("set-test", "1", "--passed", "--evidence", "pytest -> ok")
        self.run_eval_state("set-review", "1", "0")
        self.run_eval_state("set-verify", "1")
        self.run_eval_state("set-status", "1", "passed")
        self.run_eval_state("list-files")  # 唯讀，不應 append
        self.run_eval_state("archive")

        events_path = os.path.join("run", f"{run_id}.events.jsonl")
        with open(events_path, encoding="utf-8") as f:
            self.assertEqual(sum(1 for line in f if line.strip()), 10)
        write(os.path.join("run", f"{run_id}.json"), M(run_id, tier=2))

        data = stats.collect("run")
        info = dict(data["events"])[run_id]
        self.assertEqual(info["count"], 10)
        self.assertEqual(info["reentry"], 1)
        self.assertGreaterEqual(info["span_seconds"], 0)
        self.assertIn("重入 1", stats.report(data))


if __name__ == "__main__":
    unittest.main()
