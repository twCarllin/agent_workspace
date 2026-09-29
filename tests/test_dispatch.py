"""dispatch.py 的黑箱行為測試（task/2026-09-29.md item 1.1 C1–C5、item 1.2 K1–K5）。

依 R-005：跨進程執行契約以 subprocess 跑真實 script；子程序 `claude`／`codex` 以 PATH 上的
假可執行檔取代——假檔把 argv 與 stdin 落檔（fixture 在斷言中直接可驗，R-004），並回傳
環境變數指定的 stdout／exit code。留痕逐鍵斷言（R-004 加嚴）。
"""
import datetime
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = str(ROOT / ".claude" / "hooks" / "dispatch.py")
RUN_ID = "2026-09-29-dispatch-test"
STAMP = "* _2026-09-29 10:00 (claude-haiku-4-5-20251001)_"
# 合規＝report_envelope_check.check_envelope 的定義：戳記行＋（task-verifier）完成度／憑據兩節＋Self-check 終行
COMPLIANT = "\n".join([STAMP, "", "## 完成度", "全部完成", "## 憑據", "測試通過", "Self-check: 通過"])
FAKE_EXE = """#!/usr/bin/env python3
import json, os, sys
data = sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"exe": %r, "argv": sys.argv[1:], "stdin": data}) + "\\n")
sys.stdout.write(os.environ.get("FAKE_STDOUT", ""))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
CODEX_TOML = (
    'name = "task-verifier"\nmodel = "gpt-6-luna"\nmodel_reasoning_effort = "high"\n'
    'developer_instructions = "Codex role adapter: checker 指令全文"\n'
)


def claude_json(result=COMPLIANT, **extra):
    data = {
        "type": "result", "is_error": False, "result": result, "session_id": "sess-abc",
        "num_turns": 3, "total_cost_usd": 0.0415,
        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 19448,
                  "cache_read_input_tokens": 13971, "output_tokens": 44},
        "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.0415}},
    }
    data.update(extra)
    return json.dumps(data)


CODEX_TEXT = "## 完成度\n全部完成\n## 憑據\n測試通過\nSelf-check: 通過"  # 無戳記行 → advisory


def codex_jsonl(text=CODEX_TEXT, with_message=True):
    lines = [json.dumps({"type": "thread.started", "thread_id": "thread-xyz"}),
             json.dumps({"type": "turn.started"})]
    if with_message:
        lines.append(json.dumps({"type": "item.completed",
                                 "item": {"id": "item_0", "type": "agent_message", "text": text}}))
    lines.append(json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 16296, "cached_input_tokens": 7936, "cache_write_input_tokens": 12,
        "output_tokens": 5, "reasoning_output_tokens": 0}}))
    return "\n".join(lines) + "\n"


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        os.makedirs(os.path.join(self.dir, "run"))
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        for exe in ("claude", "codex"):
            path = os.path.join(self.bin, exe)
            with open(path, "w", encoding="utf-8") as f:
                f.write(FAKE_EXE % exe)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.calls = os.path.join(self.dir, "calls.jsonl")
        self.prompt = os.path.join(self.dir, "prompt.md")
        with open(self.prompt, "w", encoding="utf-8") as f:
            f.write("派工 prompt 全文\n第二行\n")
        self.write_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self, **extra):
        m = {"run_id": RUN_ID, "tier": 1, "status": "in_progress", "phase": "decomposed",
             "spec_inline": "s", "task_file": "task/x.md", **extra}
        with open(os.path.join(self.dir, "run", f"{RUN_ID}.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)

    def dispatch(self, *args, stdout="", exit_code=0):
        env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
               "FAKE_CALLS": self.calls, "FAKE_STDOUT": stdout, "FAKE_EXIT": str(exit_code)}
        return subprocess.run([sys.executable, DISPATCH, *args], cwd=self.dir, env=env,
                              capture_output=True, text=True)

    def calls_made(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def records(self):
        path = os.path.join(self.dir, "run", f"{RUN_ID}.dispatch.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # --- item 1.1 ---

    def test_c1_compliant_report_stdout_exit_and_record(self):
        """C1：合規報告 → stdout == result；exit 0；留痕逐鍵相符。"""
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertIn("[dispatch] role=task-verifier backend=claude session=sess-abc turns=3 "
                      "tokens=33473 cost_usd=0.0415", proc.stderr)
        records = self.records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        datetime.datetime.fromisoformat(rec.pop("ts"))
        self.assertIsInstance(rec.pop("duration_ms"), int)
        self.assertEqual(rec, {
            "role": "task-verifier", "backend": "claude", "session_id": "sess-abc",
            "resumed": False, "model": "claude-haiku-4-5-20251001", "turns": 3,
            "input_tokens": 10, "cache_creation_input_tokens": 19448,
            "cache_read_input_tokens": 13971, "output_tokens": 44,
            "cost_usd": 0.0415, "exit_code": 0, "envelope": "ok",
        })

    def test_c2_claude_argv_and_stdin(self):
        """C2：argv 含 -p／--agent <role>／--output-format json／--dangerously-skip-permissions；stdin == prompt 檔。"""
        self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["exe"], "claude")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--agent") + 1], "task-verifier")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--resume", argv)
        self.assertEqual(calls[0]["stdin"], "派工 prompt 全文\n第二行\n")

    def test_c3_missing_self_check_is_blocking(self):
        """C3：缺 Self-check 終行 → exit 2；stderr 含「信封缺損」；stdout 仍全文；留痕 envelope=blocking。"""
        broken = "\n".join([STAMP, "", "## 完成度", "x", "## 憑據", "y"])
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json(result=broken))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("信封缺損", proc.stderr)
        self.assertIn("Self-check", proc.stderr)
        self.assertEqual(proc.stdout, broken + "\n")
        rec = self.records()[0]
        self.assertEqual(rec["envelope"], "blocking")
        self.assertEqual(rec["exit_code"], 2)

    def test_c4_resume_with_missing_stamp_is_advisory(self):
        """C4 [組合]：--resume sid ＋ 只缺戳記行 → argv 含 --resume sid；exit 0；stderr 含「警告」；留痕 resumed／advisory。"""
        no_stamp = "\n".join(["不是戳記行", "", "## 內容", "x", "Self-check: 通過"])
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--resume", "sess-prev",
                             stdout=claude_json(result=no_stamp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("警告", proc.stderr)
        argv = self.calls_made()[0]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-prev")
        rec = self.records()[0]
        self.assertTrue(rec["resumed"])
        self.assertEqual(rec["envelope"], "advisory")
        self.assertEqual(rec["exit_code"], 0)

    def test_c5_child_failures_exit_3_and_unknown_role_exit_1(self):
        """C5 [邊界]：子程序 exit 1／stdout 非 JSON／is_error → exit 3、stderr 含原因、留痕 exit_code=3；
        角色無定義檔 → exit 1 且不呼叫 claude。"""
        for label, kwargs in (
            ("exit1", {"stdout": claude_json(), "exit_code": 1}),
            ("nonjson", {"stdout": "not json at all"}),
            ("is_error", {"stdout": claude_json(is_error=True)}),
        ):
            with self.subTest(case=label):
                proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, **kwargs)
                self.assertEqual(proc.returncode, 3)
                self.assertIn("[dispatch]", proc.stderr)
                self.assertEqual(proc.stdout, "")
        self.assertEqual([r["exit_code"] for r in self.records()], [3, 3, 3])
        before = len(self.calls_made())
        proc = self.dispatch("no-such-role", "--prompt-file", self.prompt, stdout=claude_json())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no-such-role", proc.stderr)
        self.assertEqual(len(self.calls_made()), before)

    def test_no_run_resolvable_skips_record_keeps_output(self):
        """DoD 2 邊界：無 eval_state、無 tier 1 in_progress manifest → 不落檔、stderr 一句、exit 不變。"""
        os.remove(os.path.join(self.dir, "run", f"{RUN_ID}.json"))
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertIn("不寫派工留痕", proc.stderr)
        self.assertEqual(os.listdir(os.path.join(self.dir, "run")), [])

    # --- item 1.2 ---

    def write_codex_toml(self):
        os.makedirs(os.path.join(self.dir, ".codex", "agents"))
        with open(os.path.join(self.dir, ".codex", "agents", "task-verifier.toml"), "w", encoding="utf-8") as f:
            f.write(CODEX_TOML)

    def test_k1_codex_argv_stdin_and_stdout(self):
        """K1：--backend codex → stdout == text；argv 含 exec／--json／-m／-c effort／bypass；stdin 頭尾。"""
        self.write_codex_toml()
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--backend", "codex",
                             stdout=codex_jsonl())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, CODEX_TEXT + "\n")
        call = self.calls_made()[0]
        argv = call["argv"]
        self.assertEqual(call["exe"], "codex")
        self.assertEqual(argv[0], "exec")
        self.assertIn("--json", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=high")
        self.assertTrue(call["stdin"].startswith("Codex role adapter: checker 指令全文"))
        self.assertTrue(call["stdin"].endswith("派工 prompt 全文\n第二行\n"))

    def test_k2_codex_record_fields(self):
        """K2：留痕 backend=codex、session_id=thread_id、用量映射、cost_usd=null 逐鍵相符。"""
        self.write_codex_toml()
        self.dispatch("task-verifier", "--prompt-file", self.prompt, "--backend", "codex", stdout=codex_jsonl())
        rec = self.records()[0]
        rec.pop("ts")
        rec.pop("duration_ms")
        self.assertEqual(rec, {
            "role": "task-verifier", "backend": "codex", "session_id": "thread-xyz",
            "resumed": False, "model": "gpt-6-luna", "turns": 1,
            "input_tokens": 16296, "cache_creation_input_tokens": 12,
            "cache_read_input_tokens": 7936, "output_tokens": 5,
            "cost_usd": None, "exit_code": 0, "envelope": "advisory",
        })

    def test_k3_default_backend_follows_manifest_harness(self):
        """K3：無 --backend；manifest harness=codex → 呼叫 codex；無 harness → 呼叫 claude。"""
        self.write_codex_toml()
        self.write_manifest(harness="codex")
        self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=codex_jsonl())
        self.assertEqual([c["exe"] for c in self.calls_made()], ["codex"])
        self.write_manifest()
        self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        self.assertEqual([c["exe"] for c in self.calls_made()], ["codex", "claude"])

    def test_k4_codex_resume(self):
        """K4 [組合]：--backend codex --resume tid → argv 以 exec resume tid 開頭且含 --json。"""
        self.write_codex_toml()
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--backend", "codex",
                             "--resume", "thread-prev", stdout=codex_jsonl())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.calls_made()[0]["argv"]
        self.assertEqual(argv[:3], ["exec", "resume", "thread-prev"])
        self.assertIn("--json", argv)
        self.assertTrue(self.records()[0]["resumed"])

    def test_k5_codex_missing_toml_and_missing_message(self):
        """K5 [邊界]：toml 不存在 → exit 1、不呼叫 codex；JSONL 無 agent_message → exit 3。"""
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--backend", "codex",
                             stdout=codex_jsonl())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("task-verifier.toml", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.write_codex_toml()
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--backend", "codex",
                             stdout=codex_jsonl(with_message=False))
        self.assertEqual(proc.returncode, 3)
        self.assertIn("agent_message", proc.stderr)


if __name__ == "__main__":
    unittest.main()
