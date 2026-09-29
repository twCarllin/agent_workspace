"""token_usage.py transcript 實測腳本的行為測試（黑箱：subprocess 呼叫 CLI，
驗 stdout/exit code/manifest 副作用；比照 tests/test_devlog.py 的 subprocess 慣例）。

執行：python3 -m unittest tests.test_token_usage -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS_DIR = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks")
TOKEN_USAGE_PATH = os.path.join(HOOKS_DIR, "token_usage.py")


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def write_raw(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def assistant_line(timestamp, usage):
    return json.dumps({
        "type": "assistant",
        "timestamp": timestamp,
        "message": {"model": "m", "usage": usage},
    })


def write_jsonl(path, lines):
    write_raw(path, "\n".join(lines) + "\n")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_cli(run_dir, *extra_args):
    return subprocess.run(
        [sys.executable, TOKEN_USAGE_PATH, *extra_args, "--dir", run_dir],
        capture_output=True, text=True,
    )


class TokenUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.projects_root = os.path.join(self.tmp.name, "projects")

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_run_sums_main_within_window_only(self):
        """契約row「正常」：manifest 有 session_id；events 窗 [t1,t2]；主 flow 3 則
        assistant（2 在窗內）→ main 四欄＝窗內 2 則之和、turns=2，窗外訊息不計入。"""
        run_id = "r-normal"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "session_id": "sess-normal",
        })
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.events.jsonl"), [
            json.dumps({"ts": "2026-09-06T09:00:00+00:00", "cmd": "init", "args": {}}),
            json.dumps({"ts": "2026-09-06T09:10:00+00:00", "cmd": "set-step", "args": {}}),
        ])
        write_jsonl(os.path.join(self.projects_root, "sess-normal.jsonl"), [
            assistant_line("2026-09-06T08:00:00+00:00",
                            {"input_tokens": 100, "output_tokens": 10}),  # 窗外
            assistant_line("2026-09-06T09:05:00+00:00", {
                "input_tokens": 2, "cache_creation_input_tokens": 20170,
                "cache_read_input_tokens": 21304, "output_tokens": 715,
            }),
            assistant_line("2026-09-06T09:06:00+00:00", {
                "input_tokens": 3, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200, "output_tokens": 50,
            }),
        ])

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        main = manifest["token_usage"]["main"]
        self.assertEqual(main, {
            "input_tokens": 5, "cache_creation_input_tokens": 20270,
            "cache_read_input_tokens": 21504, "output_tokens": 765, "turns": 2,
        })
        self.assertEqual(manifest["subagent_usage"]["main"], 5 + 20270 + 21504 + 765)

    def test_subagent_classification_prep_vs_loop(self):
        """契約row「分類」：subagents 為 task-decomposer、code-writer、無 meta →
        prep＝task-decomposer 之和；loop＝另兩者之和（無 meta 歸 loop）。"""
        run_id = "r-classify"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "session_id": "sess-classify",
        })
        sub_dir = os.path.join(self.projects_root, "sess-classify", "subagents")
        write_jsonl(os.path.join(sub_dir, "agent-1.jsonl"), [
            assistant_line("2026-09-06T09:05:00+00:00", {
                "input_tokens": 50, "cache_creation_input_tokens": 1,
                "cache_read_input_tokens": 2, "output_tokens": 5,
            }),
        ])
        write(os.path.join(sub_dir, "agent-1.meta.json"),
              {"agentType": "task-decomposer", "description": "decompose task"})
        write_jsonl(os.path.join(sub_dir, "agent-2.jsonl"), [
            assistant_line("2026-09-06T09:05:00+00:00",
                            {"input_tokens": 7, "output_tokens": 1}),
        ])
        write(os.path.join(sub_dir, "agent-2.meta.json"),
              {"agentType": "code-writer", "description": "write code"})
        write_jsonl(os.path.join(sub_dir, "agent-3.jsonl"), [
            assistant_line("2026-09-06T09:05:00+00:00",
                            {"input_tokens": 9, "output_tokens": 2}),
        ])
        # agent-3 無 .meta.json（缺 meta → 歸 loop）

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(manifest["subagent_usage"]["prep"], 50 + 1 + 2 + 5)
        self.assertEqual(manifest["subagent_usage"]["loop"], (7 + 1) + (9 + 2))

    def test_full_session_and_write_writes_all_three_messages(self):
        """契約row「組合：--full-session＋--write」：同上 fixture（含窗外訊息）→
        main 含 3 則；manifest.subagent_usage.main＝3 則四欄和；既有欄位不變。"""
        run_id = "r-combo"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "session_id": "sess-combo",
        })
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.events.jsonl"), [
            json.dumps({"ts": "2026-09-06T09:00:00+00:00", "cmd": "init", "args": {}}),
            json.dumps({"ts": "2026-09-06T09:10:00+00:00", "cmd": "set-step", "args": {}}),
        ])
        write_jsonl(os.path.join(self.projects_root, "sess-combo.jsonl"), [
            assistant_line("2026-09-06T08:00:00+00:00",
                            {"input_tokens": 100, "output_tokens": 10}),
            assistant_line("2026-09-06T09:05:00+00:00", {
                "input_tokens": 2, "cache_creation_input_tokens": 20170,
                "cache_read_input_tokens": 21304, "output_tokens": 715,
            }),
            assistant_line("2026-09-06T09:06:00+00:00", {
                "input_tokens": 3, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200, "output_tokens": 50,
            }),
        ])

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root,
                          "--full-session", "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(manifest["token_usage"]["main"]["turns"], 3)
        expected_total = (100 + 2 + 3) + (0 + 20170 + 100) + (0 + 21304 + 200) + (10 + 715 + 50)
        self.assertEqual(manifest["subagent_usage"]["main"], expected_total)
        self.assertIsNone(manifest["token_usage"]["window"])
        # 既有欄位不變
        self.assertEqual(manifest["tier"], 1)
        self.assertEqual(manifest["run_id"], run_id)

    def test_missing_events_file_equals_full_session(self):
        """契約row「邊界：無 events 檔」：刪（不建）events.jsonl → 結果同 --full-session
        （窗外訊息也計入）。"""
        run_id = "r-noevents"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "session_id": "sess-noevents",
        })
        # 刻意不建立 events.jsonl
        write_jsonl(os.path.join(self.projects_root, "sess-noevents.jsonl"), [
            assistant_line("2026-09-06T08:00:00+00:00",
                            {"input_tokens": 100, "output_tokens": 10}),
            assistant_line("2026-09-06T09:05:00+00:00", {
                "input_tokens": 2, "cache_creation_input_tokens": 20170,
                "cache_read_input_tokens": 21304, "output_tokens": 715,
            }),
            assistant_line("2026-09-06T09:06:00+00:00", {
                "input_tokens": 3, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200, "output_tokens": 50,
            }),
        ])

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(manifest["token_usage"]["main"]["turns"], 3)
        self.assertEqual(manifest["token_usage"]["main"]["input_tokens"], 100 + 2 + 3)

    def test_fallback_zero_candidates_exits_1_and_manifest_unchanged(self):
        """契約row「邊界：fallback 零候選」：manifest 無 session_id、projects-root 空
        → exit 1、stderr 有訊息、manifest 不變。"""
        run_id = "r-fallback-empty"
        manifest_path = os.path.join(self.run_dir, f"{run_id}.json")
        write(manifest_path, {"run_id": run_id, "tier": 1})
        empty_root = os.path.join(self.tmp.name, "empty-projects")
        os.makedirs(empty_root, exist_ok=True)
        with open(manifest_path, "rb") as f:
            before = f.read()

        result = run_cli(self.run_dir, run_id, "--projects-root", empty_root)

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        with open(manifest_path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_fallback_with_one_matching_candidate_sums_only_that_file(self):
        """契約row「fallback 有候選」：manifest 無 session_id；projects-root 下 1 個
        transcript 內含 run_id 字串（含其 subagents 目錄 1 檔）、另 1 個不含 →
        只計含 run_id 者：main＝該檔窗內和、loop 含其 subagent；不含者不計。"""
        run_id = "r-fallback-candidate"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1,
        })
        # 含 run_id 字串的候選檔（sessionId 欄位帶 run_id，模擬真實 transcript 的 sessionId 鍵）
        write_jsonl(os.path.join(self.projects_root, "match.jsonl"), [
            json.dumps({
                "type": "assistant", "timestamp": "2026-09-06T09:05:00+00:00",
                "sessionId": run_id,
                "message": {"usage": {"input_tokens": 11, "output_tokens": 2}},
            }),
        ])
        # 該候選檔的 subagents 目錄（<候選檔去副檔名>/subagents/）
        write_jsonl(
            os.path.join(self.projects_root, "match", "subagents", "agent-1.jsonl"),
            [assistant_line("2026-09-06T09:05:00+00:00", {"input_tokens": 3, "output_tokens": 1})],
        )
        write(os.path.join(self.projects_root, "match", "subagents", "agent-1.meta.json"),
              {"agentType": "code-writer", "description": "write code"})
        # 不含 run_id 字串的候選檔——不應被計入
        write_jsonl(os.path.join(self.projects_root, "nomatch.jsonl"), [
            json.dumps({
                "type": "assistant", "timestamp": "2026-09-06T09:05:00+00:00",
                "sessionId": "other-session-unrelated",
                "message": {"usage": {"input_tokens": 999, "output_tokens": 999}},
            }),
        ])

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        main = manifest["token_usage"]["main"]
        self.assertEqual(main["input_tokens"], 11)
        self.assertEqual(main["output_tokens"], 2)
        self.assertEqual(main["turns"], 1)
        self.assertEqual(manifest["subagent_usage"]["main"], 11 + 2)
        self.assertEqual(manifest["subagent_usage"]["loop"], 3 + 1)
        self.assertEqual(manifest["subagent_usage"]["prep"], 0)

    def test_bad_json_line_skipped_without_crash(self):
        """契約row「邊界：壞行」：transcript 夾一行非 JSON → 跳過、其餘照算，不 crash。"""
        run_id = "r-badline"
        write(os.path.join(self.run_dir, f"{run_id}.json"), {
            "run_id": run_id, "tier": 1, "session_id": "sess-bad",
        })
        write_jsonl(os.path.join(self.projects_root, "sess-bad.jsonl"), [
            assistant_line("2026-09-06T09:05:00+00:00", {"input_tokens": 4, "output_tokens": 1}),
            "{not valid json}",
            assistant_line("2026-09-06T09:06:00+00:00", {"input_tokens": 6, "output_tokens": 2}),
        ])

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(manifest["token_usage"]["main"]["input_tokens"], 10)
        self.assertEqual(manifest["token_usage"]["main"]["turns"], 2)

    def test_no_write_flag_leaves_manifest_unchanged(self):
        """契約row「唯讀」：無 --write → manifest 位元不變。"""
        run_id = "r-readonly"
        manifest_path = os.path.join(self.run_dir, f"{run_id}.json")
        write(manifest_path, {"run_id": run_id, "tier": 1, "session_id": "sess-readonly"})
        write_jsonl(os.path.join(self.projects_root, "sess-readonly.jsonl"), [
            assistant_line("2026-09-06T09:05:00+00:00", {"input_tokens": 1, "output_tokens": 1}),
        ])
        with open(manifest_path, "rb") as f:
            before = f.read()

        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root)

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(manifest_path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)


def dispatch_line(role, backend="claude", ts="2026-09-29T02:00:00+00:00", **usage):
    """`run/<run_id>.dispatch.jsonl` 一行（鍵集依 Spec 2026-09-29 §3.4；未給的四欄為 0）。"""
    line = {"ts": ts, "role": role, "backend": backend, "session_id": "s", "resumed": False,
            "model": "m", "turns": 2, "input_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "output_tokens": 0, "cost_usd": None,
            "duration_ms": 1, "exit_code": 0, "envelope": "ok"}
    line.update(usage)
    return json.dumps(line)


class DispatchRecordsTest(unittest.TestCase):
    """item 1.4（task/2026-09-29.md）契約 T1–T4：headless 派工留痕併入 subagents。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.projects_root = os.path.join(self.tmp.name, "projects")

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest_with_empty_main(self, run_id):
        write(os.path.join(self.run_dir, f"{run_id}.json"),
              {"run_id": run_id, "tier": 1, "session_id": f"sess-{run_id}"})
        # 主 flow transcript 存在但無訊息 → main 全 0，不干擾 prep/loop 斷言
        write_raw(os.path.join(self.projects_root, f"sess-{run_id}.jsonl"), "")

    def test_t1_dispatch_records_become_subagents_prep_and_loop(self):
        """T1：兩行（task-decomposer、code-writer）、無 transcript subagents → stdout 各印一行；
        --write 後 prep／loop＝各行四欄和；token_usage.subagents 兩筆逐鍵相符。"""
        run_id = "r-dispatch"
        self._manifest_with_empty_main(run_id)
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.dispatch.jsonl"), [
            dispatch_line("task-decomposer", input_tokens=10, cache_creation_input_tokens=20,
                          cache_read_input_tokens=30, output_tokens=40),
            dispatch_line("code-writer", input_tokens=1, cache_creation_input_tokens=2,
                          cache_read_input_tokens=3, output_tokens=4),
        ])
        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("task-decomposer dispatch:claude:", result.stdout)
        self.assertIn("code-writer dispatch:claude:", result.stdout)
        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(manifest["subagent_usage"]["prep"], 10 + 20 + 30 + 40)
        self.assertEqual(manifest["subagent_usage"]["loop"], 1 + 2 + 3 + 4)
        self.assertEqual(manifest["token_usage"]["subagents"], [
            {"agent_type": "task-decomposer", "description": "dispatch:claude", "input_tokens": 10,
             "cache_creation_input_tokens": 20, "cache_read_input_tokens": 30, "output_tokens": 40, "turns": 2},
            {"agent_type": "code-writer", "description": "dispatch:claude", "input_tokens": 1,
             "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3, "output_tokens": 4, "turns": 2},
        ])

    def test_t2_transcript_and_dispatch_sources_union(self):
        """T2 [組合]：transcript subagents 一筆 ＋ dispatch 一筆 → subagents 恰 2 筆、loop 為兩者和。"""
        run_id = "r-union"
        self._manifest_with_empty_main(run_id)
        sub_dir = os.path.join(self.projects_root, f"sess-{run_id}", "subagents")
        write_jsonl(os.path.join(sub_dir, "agent-1.jsonl"), [
            assistant_line("2026-09-29T02:00:00+00:00", {"input_tokens": 7, "output_tokens": 1}),
        ])
        write(os.path.join(sub_dir, "agent-1.meta.json"), {"agentType": "code-writer", "description": "d"})
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.dispatch.jsonl"),
                    [dispatch_line("task-verifier", input_tokens=5, output_tokens=6)])
        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(len(manifest["token_usage"]["subagents"]), 2)
        self.assertEqual(manifest["subagent_usage"]["loop"], (7 + 1) + (5 + 6))

    def test_t3_missing_file_unchanged_and_bad_line_skipped(self):
        """T3 [邊界]：無 dispatch.jsonl → subagents 空（與改造前一致）；含一行壞 JSON → 跳過、其餘照計、exit 0。"""
        run_id = "r-badline-dispatch"
        self._manifest_with_empty_main(run_id)
        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load(os.path.join(self.run_dir, f"{run_id}.json"))["token_usage"]["subagents"], [])
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.dispatch.jsonl"), [
            "{broken json",
            dispatch_line("retro", input_tokens=3, output_tokens=4),
        ])
        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = load(os.path.join(self.run_dir, f"{run_id}.json"))
        self.assertEqual(len(manifest["token_usage"]["subagents"]), 1)
        self.assertEqual(manifest["subagent_usage"]["loop"], 3 + 4)

    def test_t4_dispatch_outside_events_window_still_counted(self):
        """T4：events 窗 [09:00, 09:10]，dispatch 行 ts 在窗外 → 仍計入 loop。"""
        run_id = "r-window-dispatch"
        self._manifest_with_empty_main(run_id)
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.events.jsonl"), [
            json.dumps({"ts": "2026-09-06T09:00:00+00:00", "cmd": "init", "args": {}}),
            json.dumps({"ts": "2026-09-06T09:10:00+00:00", "cmd": "set-step", "args": {}}),
        ])
        write_jsonl(os.path.join(self.run_dir, f"{run_id}.dispatch.jsonl"),
                    [dispatch_line("code-writer", ts="2026-09-06T08:00:00+00:00", input_tokens=9, output_tokens=1)])
        result = run_cli(self.run_dir, run_id, "--projects-root", self.projects_root, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load(os.path.join(self.run_dir, f"{run_id}.json"))["subagent_usage"]["loop"], 9 + 1)


if __name__ == "__main__":
    unittest.main()
