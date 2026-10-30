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
COMPLIANT = "\n".join(
    [STAMP, "", "## 完成度", "全部完成", "## 憑據", "測試通過", "Self-check: 通過"]
)
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
        "type": "result",
        "is_error": False,
        "result": result,
        "session_id": "sess-abc",
        "num_turns": 3,
        "total_cost_usd": 0.0415,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 19448,
            "cache_read_input_tokens": 13971,
            "output_tokens": 44,
        },
        "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.0415}},
    }
    data.update(extra)
    return json.dumps(data)


CODEX_TEXT = (
    "## 完成度\n全部完成\n## 憑據\n測試通過\nSelf-check: 通過"  # 無戳記行 → advisory
)


def codex_jsonl(text=CODEX_TEXT, with_message=True):
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "thread-xyz"}),
        json.dumps({"type": "turn.started"}),
    ]
    if with_message:
        lines.append(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": text},
                }
            )
        )
    lines.append(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 16296,
                    "cached_input_tokens": 7936,
                    "cache_write_input_tokens": 12,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 0,
                },
            }
        )
    )
    return "\n".join(lines) + "\n"


class DispatchFixture:
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
        m = {
            "run_id": RUN_ID,
            "tier": 1,
            "status": "in_progress",
            "phase": "decomposed",
            "spec_inline": "s",
            "task_file": "task/x.md",
            **extra,
        }
        with open(
            os.path.join(self.dir, "run", f"{RUN_ID}.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(m, f)

    def dispatch(self, *args, stdout="", exit_code=0, touch=(), sleep=None, input=None):
        env = {
            **os.environ,
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_CALLS": self.calls,
            "FAKE_STDOUT": stdout,
            "FAKE_EXIT": str(exit_code),
            "FAKE_TOUCH": "|".join(touch),
        }
        if sleep is not None:
            env["FAKE_SLEEP"] = str(sleep)
        return subprocess.run(
            [sys.executable, DISPATCH, *args],
            cwd=self.dir,
            env=env,
            capture_output=True,
            text=True,
            input=input,
        )

    def run_role(self, *args, role="task-verifier", stdout=None, **kw):
        """以預設 prompt 檔派工；stdout 缺省為合規 claude JSON。"""
        if stdout is None:
            stdout = claude_json()
        return self.dispatch(role, "--prompt-file", self.prompt, *args, stdout=stdout, **kw)

    def write_codex_toml(self):
        directory = Path(self.dir) / ".codex" / "agents"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "task-verifier.toml").write_text(CODEX_TOML, encoding="utf-8")

    def record_core(self, index=0):
        """取第 index 筆留痕，驗 ts 可解析、duration_ms 為 int 後移除，回傳其餘逐鍵內容。"""
        rec = self.records()[index]
        datetime.datetime.fromisoformat(rec.pop("ts"))
        self.assertIsInstance(rec.pop("duration_ms"), int)
        return rec

    def init_git(self, tracked=("a.py", "c.py")):
        """B 系列：把工作目錄變成 git repo，tracked 檔已提交（之後修改會出現在 git status）。"""
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@t.com"],
            ["git", "config", "user.name", "T"],
        ):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)
        with open(os.path.join(self.dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("run/\nbin/\ncalls.jsonl\nprompt.md\n")
        for name in tracked:
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write("original\n")
        for cmd in (["git", "add", "."], ["git", "commit", "-q", "-m", "init"]):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)

    def reset_git(self):
        for cmd in (["git", "reset", "-q", "--hard"], ["git", "clean", "-fdq"]):
            subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True)

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


REC_CLAUDE = {
    "role": "task-verifier",
    "backend": "claude",
    "permissions": "inherit",
    "session_id": "sess-abc",
    "resumed": False,
    "model": "claude-haiku-4-5-20251001",
    "turns": 3,
    "input_tokens": 10,
    "cache_creation_input_tokens": 19448,
    "cache_read_input_tokens": 13971,
    "output_tokens": 44,
    "cost_usd": 0.0415,
    "exit_code": 0,
    "envelope": "ok",
    "failure": None,
    "out_of_scope": None,
    "retro": None,
    "permission_denials": [],
}
REC_CODEX = {
    **REC_CLAUDE,
    "backend": "codex",
    "session_id": "thread-xyz",
    "model": "gpt-6-luna",
    "turns": 1,
    "input_tokens": 16296,
    "cache_creation_input_tokens": 12,
    "cache_read_input_tokens": 7936,
    "output_tokens": 5,
    "cost_usd": None,
    "envelope": "advisory",
}
PROMPT_TEXT = "派工 prompt 全文\n第二行\n"
BROKEN = "\n".join([STAMP, "", "## 完成度", "x", "## 憑據", "y"])  # 缺 Self-check 終行


class DispatchTest(DispatchFixture, unittest.TestCase):
    # --- item 1.1 ---

    def test_c1_compliant_report_stdout_exit_and_record(self):
        """C1：合規報告 → stdout == result；exit 0；留痕逐鍵相符。"""
        proc = self.run_role()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.record_core(), REC_CLAUDE)

    def test_c2_claude_argv_and_stdin(self):
        """C2：argv 含 -p／--agent <role>／--output-format json；預設無 bypass；stdin == prompt 檔。"""
        self.run_role()
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["exe"], "claude")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--agent") + 1], "task-verifier")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--resume", argv)
        self.assertEqual(calls[0]["stdin"], PROMPT_TEXT)

    def test_permission_flags_and_record(self):
        unrestricted = (
            "--dangerously-skip-permissions",
            "--dangerously-bypass-approvals-and-sandbox",
        )
        for name, role, backend, perms, flag, mode, recorded in (
            ("唯讀角色預設", "task-verifier", "claude", None, None, None, "inherit"),
            ("寫入角色預設 edits", "code-writer", "claude", None, None, "acceptEdits", "edits"),
            ("寫入角色明示 inherit", "code-writer", "claude", "inherit", None, None, "inherit"),
            ("claude unrestricted", "task-verifier", "claude", "unrestricted", unrestricted[0], None, "unrestricted"),
            ("codex unrestricted", "task-verifier", "codex", "unrestricted", unrestricted[1], None, "unrestricted"),
        ):
            with self.subTest(name):
                args = ["--backend", backend] + (["--permissions", perms] if perms else [])
                if backend == "codex":
                    self.write_codex_toml()
                out = codex_jsonl() if backend == "codex" else claude_json()
                proc = self.run_role(*args, role=role, stdout=out)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                argv = self.calls_made()[-1]["argv"]
                self.assertEqual([f for f in unrestricted if f in argv], [flag] if flag else [])
                got_mode = argv[argv.index("--permission-mode") + 1] if "--permission-mode" in argv else None
                self.assertEqual(got_mode, mode)
                self.assertEqual(self.records()[-1]["permissions"], recorded)

    def test_blocking_envelope_and_permission_denials_exit_2(self):
        """C3：缺 Self-check 終行 → exit 2、stdout 仍全文、envelope=blocking；權限拒絕 → exit 2、留痕列工具名。"""
        denial = {"permission_denials": [{"tool_name": "Write", "tool_input": {}}]}
        for name, result, extra, envelope, denials in (
            ("C3 缺 Self-check", BROKEN, {}, "blocking", []),
            ("permission_denials", COMPLIANT, denial, "ok", ["Write"]),
        ):
            with self.subTest(name):
                proc = self.run_role(stdout=claude_json(result=result, **extra))
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(proc.stdout, result + "\n")
                rec = self.records()[-1]
                self.assertEqual(
                    (rec["exit_code"], rec["envelope"], rec["permission_denials"]),
                    (2, envelope, denials),
                )

    def test_c4_resume_with_missing_stamp_is_advisory(self):
        """C4 [組合]：--resume sid ＋ 只缺戳記行 → argv 含 --resume sid；exit 0；留痕 resumed／advisory。"""
        no_stamp = "\n".join(["不是戳記行", "", "## 內容", "x", "Self-check: 通過"])
        proc = self.run_role(
            "--resume", "sess-prev", role="code-writer", stdout=claude_json(result=no_stamp)
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.calls_made()[0]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-prev")
        rec = self.records()[0]
        self.assertEqual((rec["resumed"], rec["envelope"], rec["exit_code"]), (True, "advisory", 0))

    def test_c5_child_failures_exit_3_and_unknown_role_exit_1(self):
        """C5 [邊界]：子程序 exit 1／stdout 非 JSON／is_error → exit 3、留痕 exit_code=3（exit 1 者 failure=child_error）；
        角色無定義檔 → exit 1 且不呼叫 claude。"""
        for label, kwargs in (
            ("exit1", {"stdout": claude_json(), "exit_code": 1}),
            ("nonjson", {"stdout": "not json at all"}),
            ("is_error", {"stdout": claude_json(is_error=True)}),
        ):
            with self.subTest(case=label):
                proc = self.run_role(**kwargs)
                self.assertEqual(proc.returncode, 3)
                self.assertEqual(proc.stdout, "")
        self.assertEqual([r["exit_code"] for r in self.records()], [3, 3, 3])
        self.assertEqual(self.records()[0]["failure"], "child_error")
        before = len(self.calls_made())
        proc = self.run_role(role="no-such-role")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no-such-role", proc.stderr)
        self.assertEqual(len(self.calls_made()), before)

    def test_no_run_resolvable_skips_record_keeps_output(self):
        """DoD 2 邊界：無 eval_state、無 tier 1 in_progress manifest → 不落檔、exit 與 stdout 不變。"""
        os.remove(os.path.join(self.dir, "run", f"{RUN_ID}.json"))
        proc = self.run_role()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertEqual(os.listdir(os.path.join(self.dir, "run")), [])

    # --- item 1.2 ---

    def test_k1_k2_codex_argv_stdin_stdout_and_record(self):
        """K1／K2：--backend codex → stdout == text；argv 含 exec／--json／-m／-c effort 且無 bypass；
        stdin 頭尾；留痕 backend=codex、session_id=thread_id、用量映射、cost_usd=null 逐鍵相符。"""
        self.write_codex_toml()
        proc = self.run_role("--backend", "codex", stdout=codex_jsonl())
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
        self.assertTrue(call["stdin"].endswith(PROMPT_TEXT))
        self.assertEqual(self.record_core(), REC_CODEX)

    def test_k3_default_backend_follows_manifest_harness(self):
        """K3：無 --backend；manifest harness=codex → 呼叫 codex；無 harness → 呼叫 claude。"""
        self.write_codex_toml()
        self.write_manifest(harness="codex")
        self.run_role(stdout=codex_jsonl())
        self.assertEqual([c["exe"] for c in self.calls_made()], ["codex"])
        self.write_manifest()
        self.run_role()
        self.assertEqual([c["exe"] for c in self.calls_made()], ["codex", "claude"])

    def test_invalid_manifest_harness_blocks_even_explicit_backend(self):
        for harness in ("unknown", "", None, 1):
            with self.subTest(harness=harness):
                self.write_manifest(harness=harness)
                proc = self.run_role("--backend", "claude")
                self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.assertEqual(self.records(), [])

    def test_k4_codex_resume(self):
        """K4 [組合]：--backend codex --resume tid → argv 以 exec resume tid 開頭且含 --json。"""
        self.write_codex_toml()
        proc = self.run_role("--backend", "codex", "--resume", "thread-prev", stdout=codex_jsonl())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.calls_made()[0]["argv"]
        self.assertEqual(argv[:3], ["exec", "resume", "thread-prev"])
        self.assertIn("--json", argv)
        self.assertTrue(self.records()[0]["resumed"])

    def test_k5_codex_missing_toml_and_missing_message(self):
        """K5 [邊界]：toml 不存在 → exit 1、不呼叫 codex；JSONL 無 agent_message → exit 3。"""
        proc = self.run_role("--backend", "codex", stdout=codex_jsonl())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("task-verifier.toml", proc.stderr)
        self.assertEqual(self.calls_made(), [])
        self.write_codex_toml()
        proc = self.run_role("--backend", "codex", stdout=codex_jsonl(with_message=False))
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
        """R1：code-writer ＋ --files eval_gates.py → stdin 含選中條目與節標題，不含 retired／無關／錨點失效；留痕列計數。"""
        self.init_git(tracked=("eval_gates.py",))
        self.write_retro()
        proc = self.run_role("--files", "eval_gates.py", role="code-writer")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdin = self.calls_made()[0]["stdin"]
        self.assertTrue(stdin.startswith(PROMPT_TEXT))
        self.assertIn(self.RETRO_SECTION, stdin)
        self.assertIn("R-101", stdin)
        for absent in ("R-103", "R-104", "R-105"):
            self.assertNotIn(absent, stdin)
        self.assertEqual(self.records()[0]["retro"], {"selected": ["R-101"], "retire": ["R-104"]})

    def test_r2_missing_retro_file_is_fail_open(self):
        """R2：無 retro/RETRO.md → 仍派工（exit 依信封）、該節寫原因、留痕空清單。"""
        self.init_git()
        proc = self.run_role("--files", "a.py", role="code-writer")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdin = self.calls_made()[0]["stdin"]
        self.assertIn(self.RETRO_SECTION, stdin)
        self.assertIn("retro/RETRO.md", stdin)
        self.assertEqual(self.records()[0]["retro"], {"selected": [], "retire": []})

    def test_r3_resume_and_other_roles_do_not_prefix(self):
        """[邊界] --resume 修正輪不重複前置；task-verifier 的 stdin 與 prompt 檔逐位元相同；兩者留痕 retro=null。"""
        self.init_git(tracked=("eval_gates.py",))
        self.write_retro()
        self.run_role("--files", "eval_gates.py", "--resume", "sess-abc", role="code-writer")
        self.run_role()
        calls = self.calls_made()
        self.assertEqual([c["stdin"] for c in calls], [PROMPT_TEXT, PROMPT_TEXT])
        self.assertEqual([r["retro"] for r in self.records()], [None, None])


class DispatchGuardsTest(DispatchFixture, unittest.TestCase):
    """run 2026-09-29-dispatch-guards：item 1.1 契約 A1–A4（timeout／輸出上限）、item 1.2 契約 B1–B5（越界檢查）。
    A4（子程序 exit 1 → failure=child_error）併入 DispatchTest.test_c5。"""

    def test_a1_timeout_kills_child(self):
        """A1：假 claude 睡 5 秒、--timeout 1 → exit 3；stdout 空；留痕 timed_out；子程序已不存在。"""
        proc = self.run_role("--timeout", "1", sleep=5)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("timeout", proc.stderr)
        self.assertEqual(proc.stdout, "")
        rec = self.records()[0]
        self.assertEqual((rec["failure"], rec["exit_code"], rec["envelope"]), ("timed_out", 3, None))
        with self.assertRaises(ProcessLookupError):
            os.kill(self.calls_made()[0]["pid"], 0)

    def test_a2_output_over_limit_is_truncated(self):
        """A2：報告 > --max-output-chars 100 → exit 3；stdout 以前 100 字元開頭、不含第 101 個；留痕 output_truncated。"""
        proc = self.run_role("--max-output-chars", "100", stdout=claude_json(result="x" * 250))
        self.assertEqual(proc.returncode, 3)
        self.assertTrue(proc.stdout.startswith("x" * 100 + "\n"))
        self.assertNotIn("x" * 101, proc.stdout)
        rec = self.records()[0]
        self.assertEqual((rec["failure"], rec["exit_code"], rec["envelope"]), ("output_truncated", 3, None))

    def test_a3_explicit_limits_with_short_report_unchanged(self):
        """A3 [組合]：--timeout 30 --max-output-chars 100000 ＋ 合規短報告 → exit 0、failure=null。"""
        proc = self.run_role("--timeout", "30", "--max-output-chars", "100000")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, COMPLIANT + "\n")
        self.assertIsNone(self.records()[0]["failure"])

    def test_b1_to_b4_out_of_scope_detection(self):
        """B1 越界檔 → exit 4、列 b.py、stdout 仍全文；B2 只改允許檔 → exit 0、out_of_scope=[]；
        B3 [組合] 越界＋信封缺損 → exit 4、envelope=blocking；B4 [邊界] 派工前已修改的 c.py 不算越界、含空白檔名正確列出。"""
        self.init_git()
        for name, touch, result, preexisting, rc, oos, envelope in (
            ("B1", ("a.py", "b.py"), COMPLIANT, False, 4, ["b.py"], "ok"),
            ("B2", ("a.py",), COMPLIANT, False, 0, [], "ok"),
            ("B3", ("b.py",), BROKEN, False, 4, ["b.py"], "blocking"),
            ("B4", ("a.py", "sp ace.py"), COMPLIANT, True, 4, ["sp ace.py"], "ok"),
        ):
            with self.subTest(name):
                self.reset_git()
                if preexisting:
                    with open(os.path.join(self.dir, "c.py"), "a", encoding="utf-8") as f:
                        f.write("pre-existing edit\n")
                proc = self.run_role(
                    "--files", "a.py", role="code-writer", stdout=claude_json(result=result), touch=touch
                )
                self.assertEqual(proc.returncode, rc, proc.stderr)
                self.assertEqual(proc.stdout, result + "\n")
                rec = self.records()[-1]
                self.assertEqual((rec["out_of_scope"], rec["exit_code"], rec["envelope"]), (oos, rc, envelope))
                for path in oos:
                    self.assertIn(path, proc.stderr)

    def test_b5_no_files_flag_and_non_git_dir(self):
        """B5 [邊界]：無 --files → out_of_scope=null；非 git 目錄給 --files → 略過檢查、exit 依信封、out_of_scope=null。"""
        for extra in ((), ("--files", "a.py")):
            with self.subTest(extra=extra):
                proc = self.run_role(*extra, role="code-writer", touch=("b.py",))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIsNone(self.records()[-1]["out_of_scope"])

    def test_empty_prompt_rejected(self):
        """空指令派工等於沒派工（run 2026-10-03-parked-fixes，使用者裁示「應該要擋空的 prompt」）：
        b6 空檔、b7 只有空白字元、b8 [邊界] --prompt-file - 且 stdin 為空 → exit 1、未呼叫子程序、未落留痕。"""
        for name, content, prompt_arg in (
            ("b6 空檔", "", "empty.md"),
            ("b7 純空白", "\n  \n\t\n", "ws.md"),
            ("b8 stdin 為空", None, "-"),
        ):
            with self.subTest(name):
                if content is not None:
                    prompt_arg = os.path.join(self.dir, prompt_arg)
                    with open(prompt_arg, "w", encoding="utf-8") as f:
                        f.write(content)
                proc = self.dispatch(
                    "task-verifier", "--prompt-file", prompt_arg, stdout=claude_json(), input=""
                )
                self.assertEqual(proc.returncode, 1)
                self.assertEqual(self.calls_made(), [])
                self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
