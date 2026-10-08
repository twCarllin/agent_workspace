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
import json, os, sys, time
data = sys.stdin.read()
with open(os.environ["FAKE_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"exe": %r, "argv": sys.argv[1:], "stdin": data, "pid": os.getpid()}) + "\\n")
for path in [p for p in os.environ.get("FAKE_TOUCH", "").split("|") if p]:
    with open(path, "a", encoding="utf-8") as f:
        f.write("changed by fake worker\\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
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

    def dispatch(self, *args, stdout="", exit_code=0, touch=(), sleep=None):
        env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
               "FAKE_CALLS": self.calls, "FAKE_STDOUT": stdout, "FAKE_EXIT": str(exit_code),
               "FAKE_TOUCH": "|".join(touch)}
        if sleep is not None:
            env["FAKE_SLEEP"] = str(sleep)
        return subprocess.run([sys.executable, DISPATCH, *args], cwd=self.dir, env=env,
                              capture_output=True, text=True)

    def init_git(self, tracked=("a.py", "c.py")):
        """B 系列：把工作目錄變成 git repo，tracked 檔已提交（之後修改會出現在 git status）。"""
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                    ["git", "config", "user.name", "T"]):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)
        with open(os.path.join(self.dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("run/\nbin/\ncalls.jsonl\nprompt.md\n")
        for name in tracked:
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write("original\n")
        subprocess.run(["git", "add", "."], cwd=self.dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.dir, check=True, capture_output=True)

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
            "role": "task-verifier", "backend": "claude", "permissions": "inherit", "session_id": "sess-abc",
            "resumed": False, "model": "claude-haiku-4-5-20251001", "turns": 3,
            "input_tokens": 10, "cache_creation_input_tokens": 19448,
            "cache_read_input_tokens": 13971, "output_tokens": 44,
            "cost_usd": 0.0415, "exit_code": 0, "envelope": "ok",
            "failure": None, "out_of_scope": None, "retro": None,
        })

    def test_c2_claude_argv_and_stdin(self):
        """C2：argv 含 -p／--agent <role>／--output-format json；預設無 bypass；stdin == prompt 檔。"""
        self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["exe"], "claude")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--agent") + 1], "task-verifier")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--resume", argv)
        self.assertEqual(calls[0]["stdin"], "派工 prompt 全文\n第二行\n")

    def test_explicit_unrestricted_permissions_are_recorded(self):
        for backend, output, flag in (("claude", claude_json(), "--dangerously-skip-permissions"),
                                      ("codex", codex_jsonl(), "--dangerously-bypass-approvals-and-sandbox")):
            with self.subTest(backend=backend):
                if backend == "codex":
                    directory = Path(self.dir) / ".codex/agents"
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "task-verifier.toml").write_text(CODEX_TOML)
                result = self.dispatch("task-verifier", "--prompt-file", self.prompt,
                                       "--backend", backend, "--permissions", "unrestricted", stdout=output)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(flag, self.calls_made()[-1]["argv"])
                self.assertEqual(self.records()[-1]["permissions"], "unrestricted")

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
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
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
            "role": "task-verifier", "backend": "codex", "permissions": "inherit", "session_id": "thread-xyz",
            "resumed": False, "model": "gpt-6-luna", "turns": 1,
            "input_tokens": 16296, "cache_creation_input_tokens": 12,
            "cache_read_input_tokens": 7936, "output_tokens": 5,
            "cost_usd": None, "exit_code": 0, "envelope": "advisory",
            "failure": None, "out_of_scope": None, "retro": None,
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

    def test_invalid_manifest_harness_blocks_even_explicit_backend(self):
        for harness in ("unknown", "", None, 1):
            with self.subTest(harness=harness):
                self.write_manifest(harness=harness)
                proc = self.dispatch("task-verifier", "--prompt-file", self.prompt,
                                     "--backend", "claude", stdout=claude_json())
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn("harness 非法", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "run", RUN_ID + ".dispatch.jsonl")))

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


    # --- retro 自動前置（run 2026-10-08-retro-dispatch-inject item 1.1）---

    RETRO_FIXTURE = """# RETRO

> **ID 規則**：格式：條目行首 `- R-NNN 2026-...`

- R-101 2026-08-20［.claude/hooks／eval_gates／時序耦合／2026-08-20-obs］放行型與攔截型 gate 的順序。**約束：攔截型必須排在放行型之前。**
- R-103 ［retired 2026-09-11 2026-09-11-foo］ 2026-07-01［.claude/hooks／eval_gates／已退役／2026-07-01-x］舊機制。**約束：不該再被貼。**
- R-104 2026-07-17［.claude/hooks／eval_gates／錨點失效／2026-07-17-y］依賴一個已消失的 helper。**約束：必須沿用它。**［錨點: 這個符號不存在於任何檔案］
- R-105 2026-09-01［api／settlement／金流／2026-09-01-z］與本次無關的模組。**約束：不相干。**
"""
    RETRO_SECTION = "## 硬性約束區（retro 條目，dispatch 依 --files 自動前置）"

    def write_retro(self):
        os.makedirs(os.path.join(self.dir, "retro"), exist_ok=True)
        with open(os.path.join(self.dir, "retro", "RETRO.md"), "w", encoding="utf-8") as f:
            f.write(self.RETRO_FIXTURE)

    def test_r1_code_writer_prompt_gets_selected_retro_entries(self):
        """R1：code-writer ＋ --files eval_gates.py → stdin 含選中條目與節標題，不含 retired／無關／錨點失效；stderr 與留痕列計數。"""
        self.init_git(tracked=("eval_gates.py",))
        self.write_retro()
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "eval_gates.py",
                             stdout=claude_json())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdin = self.calls_made()[0]["stdin"]
        self.assertTrue(stdin.startswith("派工 prompt 全文\n第二行\n"))
        self.assertIn(self.RETRO_SECTION, stdin)
        self.assertIn("R-101", stdin)
        self.assertIn("攔截型必須排在放行型之前", stdin)
        for absent in ("R-103", "R-104", "R-105"):
            self.assertNotIn(absent, stdin)
        self.assertIn("retro 選中 1（R-101）、retire 候選 1（R-104）", proc.stderr)
        self.assertEqual(self.records()[0]["retro"], {"selected": ["R-101"], "retire": ["R-104"]})

    def test_r2_missing_retro_file_is_fail_open(self):
        """R2：無 retro/RETRO.md → 仍派工、該節寫原因、stderr 一句、exit 依信封、留痕空清單。"""
        self.init_git()
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py", stdout=claude_json())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdin = self.calls_made()[0]["stdin"]
        self.assertIn(self.RETRO_SECTION, stdin)
        self.assertIn("retro/RETRO.md 不存在", stdin)
        self.assertIn("retro/RETRO.md 不存在", proc.stderr)
        self.assertEqual(self.records()[0]["retro"], {"selected": [], "retire": []})

    def test_r3_resume_and_other_roles_do_not_prefix(self):
        """[邊界] --resume 修正輪不重複前置；task-verifier 的 stdin 與 prompt 檔逐位元相同；兩者留痕 retro=null。"""
        self.init_git(tracked=("eval_gates.py",))
        self.write_retro()
        self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "eval_gates.py",
                      "--resume", "sess-abc", stdout=claude_json())
        self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json())
        calls = self.calls_made()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call["stdin"], "派工 prompt 全文\n第二行\n")
        self.assertEqual([r["retro"] for r in self.records()], [None, None])


class DispatchGuardsTest(DispatchTest):
    """run 2026-09-29-dispatch-guards：item 1.1 契約 A1–A4（timeout／輸出上限）、item 1.2 契約 B1–B5（越界檢查）。
    沿用 DispatchTest 的 fixture（setUp／dispatch／records）；父類測試不在此重跑（見 load_tests）。"""

    def test_a1_timeout_kills_child(self):
        """A1：假 claude 睡 5 秒、--timeout 1 → exit 3；stderr 含 timeout；stdout 空；留痕 timed_out；子程序已不存在。"""
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--timeout", "1",
                             stdout=claude_json(), sleep=5)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("timeout", proc.stderr)
        self.assertEqual(proc.stdout, "")
        rec = self.records()[0]
        self.assertEqual((rec["failure"], rec["exit_code"], rec["envelope"]), ("timed_out", 3, None))
        pid = self.calls_made()[0]["pid"]
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a2_output_over_limit_is_truncated(self):
        """A2：報告 > --max-output-chars 100 → exit 3；stdout＝前 100 字元＋截斷末行；留痕 output_truncated。"""
        long_report = "x" * 250
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--max-output-chars", "100",
                             stdout=claude_json(result=long_report))
        self.assertEqual(proc.returncode, 3)
        self.assertIn("截斷", proc.stderr)
        self.assertEqual(proc.stdout, "x" * 100 + "\n[dispatch] 輸出截斷：250 字元超過上限 100\n")
        rec = self.records()[0]
        self.assertEqual((rec["failure"], rec["exit_code"], rec["envelope"]), ("output_truncated", 3, None))

    def test_a3_explicit_limits_with_short_report_unchanged(self):
        """A3 [組合]：--timeout 30 --max-output-chars 100000 ＋ 合規短報告 → exit 0、failure=null。"""
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, "--timeout", "30",
                             "--max-output-chars", "100000", stdout=claude_json())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertIsNone(self.records()[0]["failure"])

    def test_a4_child_exit_records_child_error(self):
        """A4 [邊界]：假 claude exit 1 → 留痕 failure=child_error（exit 3 行為不變）。"""
        proc = self.dispatch("task-verifier", "--prompt-file", self.prompt, stdout=claude_json(), exit_code=1)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.records()[0]["failure"], "child_error")

    def test_b1_out_of_scope_file_rejected(self):
        """B1：--files a.py，假 claude 改 a.py 並新增 b.py → exit 4；stderr 含越界與 b.py；留痕 ["b.py"]；stdout 仍全文。"""
        self.init_git()
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py",
                             stdout=claude_json(), touch=("a.py", "b.py"))
        self.assertEqual(proc.returncode, 4)
        self.assertIn("越界", proc.stderr)
        self.assertIn("b.py", proc.stderr)
        self.assertNotIn("a.py", proc.stderr.split("越界變更")[1])
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        rec = self.records()[0]
        self.assertEqual((rec["out_of_scope"], rec["exit_code"]), (["b.py"], 4))

    def test_b2_only_allowed_file_changed(self):
        """B2：--files a.py，只改 a.py → exit 0；留痕 out_of_scope=[]。"""
        self.init_git()
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py",
                             stdout=claude_json(), touch=("a.py",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.records()[0]["out_of_scope"], [])

    def test_b3_out_of_scope_wins_over_envelope_blocking(self):
        """B3 [組合]：越界 b.py ＋ 報告缺 Self-check → exit 4；stderr 同時含越界與信封缺損；留痕 blocking＋["b.py"]。"""
        self.init_git()
        broken = "\n".join([STAMP, "", "## 完成度", "x", "## 憑據", "y"])
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py",
                             stdout=claude_json(result=broken), touch=("b.py",))
        self.assertEqual(proc.returncode, 4)
        self.assertIn("越界", proc.stderr)
        self.assertIn("信封缺損", proc.stderr)
        rec = self.records()[0]
        self.assertEqual((rec["envelope"], rec["out_of_scope"]), ("blocking", ["b.py"]))

    def test_b4_preexisting_change_ignored_and_space_path_listed(self):
        """B4 [邊界]：派工前 c.py 已修改且假 claude 不動它 → 不算越界；含空白檔名 `sp ace.py` 越界時正確列出。"""
        self.init_git()
        with open(os.path.join(self.dir, "c.py"), "a", encoding="utf-8") as f:
            f.write("pre-existing edit\n")
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py",
                             stdout=claude_json(), touch=("a.py", "sp ace.py"))
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(self.records()[0]["out_of_scope"], ["sp ace.py"])

    def test_b5_no_files_flag_and_non_git_dir(self):
        """B5 [邊界]：無 --files → out_of_scope=null、無越界行；非 git 目錄給 --files → stderr 一句、exit 依信封。"""
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, stdout=claude_json(), touch=("b.py",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("越界", proc.stderr)
        self.assertIsNone(self.records()[0]["out_of_scope"])
        proc = self.dispatch("code-writer", "--prompt-file", self.prompt, "--files", "a.py",
                             stdout=claude_json(), touch=("b.py",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("略過越界檢查", proc.stderr)
        self.assertIsNone(self.records()[1]["out_of_scope"])


    # --- 空 prompt 斷言（run 2026-10-03-parked-fixes，使用者裁示「應該要擋空的 prompt」）---

    def test_b6_empty_prompt_file_rejected(self):
        """空 prompt 檔 → exit 1、stderr 指出為空、未呼叫子程序、未落留痕（空指令派工等於沒派工）。"""
        empty = os.path.join(self.dir, "empty.md")
        open(empty, "w", encoding="utf-8").close()
        proc = self.dispatch("task-verifier", "--prompt-file", empty, stdout=claude_json())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("為空", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.assertEqual(self.records(), [])

    def test_b7_whitespace_only_prompt_rejected(self):
        """只有空白字元（換行／空格／tab）的 prompt 檔 → 同空檔處置 exit 1。"""
        ws = os.path.join(self.dir, "ws.md")
        with open(ws, "w", encoding="utf-8") as f:
            f.write("\n  \n\t\n")
        proc = self.dispatch("task-verifier", "--prompt-file", ws, stdout=claude_json())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("為空", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.assertEqual(self.records(), [])

    def test_b8_empty_stdin_prompt_rejected(self):
        """[邊界] --prompt-file - 且 stdin 為空 → exit 1（stdin 路徑同守此斷言）。"""
        env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
               "FAKE_CALLS": self.calls, "FAKE_STDOUT": claude_json(), "FAKE_EXIT": "0",
               "FAKE_TOUCH": ""}
        proc = subprocess.run([sys.executable, DISPATCH, "task-verifier", "--prompt-file", "-"],
                              cwd=self.dir, env=env, input="", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("為空", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.assertEqual(self.records(), [])


def load_tests(loader, tests, pattern):
    """DispatchGuardsTest 繼承 DispatchTest 只為共用 fixture；父類的測試只在父類跑一次。"""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(DispatchTest))
    suite.addTests(
        t for t in loader.loadTestsFromTestCase(DispatchGuardsTest)
        if t.id().rsplit(".", 1)[1].startswith(("test_a", "test_b"))
    )
    return suite


if __name__ == "__main__":
    unittest.main()
