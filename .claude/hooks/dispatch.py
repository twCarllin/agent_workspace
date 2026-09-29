#!/usr/bin/env python3
"""subagent 派工：以 headless CLI 子程序執行流程角色（`claude -p` 預設、`codex exec` 備選）。

用法：
  python3 .claude/hooks/dispatch.py <role> --prompt-file <path|-> [--backend claude|codex] [--resume <session_id>]
                                    [--files <逗號清單>] [--timeout <秒>] [--max-output-chars <n>]

- `<role>`：`.claude/agents/<role>.md` 存在者（code-writer／task-verifier／…）；不存在 → exit 1
- `--prompt-file`：派工 prompt 全文（`-`＝stdin）。約定路徑 `run/<run_id>.prompt-<role>-<n>.md`
- `--backend`：省略時依 manifest `harness`（`"codex"` → codex，否則 claude）
- `--resume`：修正輪沿用同一子 session（claude session_id／codex thread_id）
- `--files`：本 item 允許變更的檔案清單（repo 相對路徑）。派工前後各取一次 `git status --porcelain -z`，
  「派工後有、派工前無」且不在清單內的路徑＝越界 → stderr 列出、留痕 `out_of_scope`、exit 4（報告仍印出）。
  未給＝不檢查；非 git repo＝不檢查（fail-open，stderr 一句）
- `--timeout`：子程序秒數上限（預設 1200）；超時終止 → 留痕 `failure="timed_out"`、exit 3
- `--max-output-chars`：報告字元上限（預設 60000）；超量 → stdout 只印前 n 字元＋截斷末行、留痕
  `failure="output_truncated"`、exit 3、不做信封判定

後端指令（權限依 2026-09-29 使用者裁決 D3 全放行）：
  claude：`claude -p --agent <role> --output-format json --dangerously-skip-permissions [--resume <sid>] -`（prompt 走 stdin）
  codex ：`codex exec [resume <tid>] --json --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox
           -m <model> -c model_reasoning_effort=<effort> -`（model／effort 讀 `.codex/agents/<role>.toml`；
           stdin＝該檔 developer_instructions ＋ 空行 ＋ prompt）

輸出契約：
  stdout ＝ 子 agent 報告全文（claude：JSON `result`；codex：最後一個 agent_message 的 text），不夾其他行
  stderr ＝ 摘要行 `[dispatch] role=… backend=… session=… turns=… tokens=… cost_usd=…`（＋信封訊息）
  exit   ＝ 0 正常／advisory；1 用法錯誤；2 信封 blocking（報告仍完整輸出）；3 子程序失敗／超時／超量；
           4 越界變更（報告仍完整輸出；優先於 2）

留痕：每次派工 append `run/<run_id>.dispatch.jsonl` 一行（鍵集見 append_record；純記錄、不被 gate 消費）。
run_id 解析沿用 eval_gates 既有基準（R-009）：eval_state.json → 唯一 tier 1 in_progress manifest；
皆無（run 外手動觸發）→ 不落檔、stderr 一句、exit code 不變。
信封判定重用 report_envelope_check.check_envelope（單一出處，不自建第二份規則）。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import tomllib

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS_DIR)
import eval_gates  # noqa: E402
import report_envelope_check  # noqa: E402

AGENTS_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "agents")
TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
# codex `turn.completed.usage` 鍵 → 本檔四欄（Spec 2026-09-29 §3.4）
CODEX_USAGE_MAP = {
    "input_tokens": "input_tokens",
    "cached_input_tokens": "cache_read_input_tokens",
    "cache_write_input_tokens": "cache_creation_input_tokens",
    "output_tokens": "output_tokens",
}


class ChildError(Exception):
    """子程序失敗 → exit 3。kind 記入留痕 `failure`：child_error（非 0 exit、輸出不可解析、is_error）
    ／timed_out（超過 --timeout）。"""

    def __init__(self, msg, kind="child_error"):
        super().__init__(msg)
        self.kind = kind


def fail(msg, code):
    print(f"[dispatch] {msg}", file=sys.stderr)
    sys.exit(code)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _zero_tokens():
    return {k: 0 for k in TOKEN_FIELDS}


def resolve_run_id():
    """同 eval_gates.check_task_gate 的定位基準：eval_state.json 優先，否則唯一 tier 1 in_progress。"""
    if os.path.exists("eval_state.json"):
        state = eval_gates.load_json_quiet("eval_state.json")
        if isinstance(state, dict) and state.get("run_id"):
            return state["run_id"]
    found = eval_gates._find_unique_tier1_inprogress()
    if found:
        return eval_gates.MANIFEST_RE.match(found[0]).group("run_id")
    return None


def default_backend(run_id):
    if run_id:
        manifest = eval_gates.load_json_quiet(f"run/{run_id}.json")
        if isinstance(manifest, dict) and manifest.get("harness") == "codex":
            return "codex"
    return "claude"


def read_prompt(path):
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        fail(f"讀不到 prompt 檔 {path}（{e}）", 1)


def _run(argv, stdin_text, timeout):
    try:
        return subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # subprocess.run 於超時已 kill 子程序並回收
        raise ChildError(f"{argv[0]} 超過 timeout {timeout:g} 秒，子程序已終止", kind="timed_out")
    except OSError as e:
        raise ChildError(f"無法啟動 {argv[0]}（{e}）")


def run_claude(role, prompt, resume, timeout):
    argv = ["claude", "-p", "--agent", role, "--output-format", "json", "--dangerously-skip-permissions"]
    if resume:
        argv += ["--resume", resume]
    argv.append("-")
    proc = _run(argv, prompt, timeout)
    if proc.returncode != 0:
        raise ChildError(f"claude exit {proc.returncode}：{(proc.stderr or proc.stdout).strip()[-500:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ChildError(f"claude 輸出非 JSON：{proc.stdout.strip()[:300]}")
    if not isinstance(data, dict):
        raise ChildError("claude 輸出非 JSON 物件")
    if data.get("is_error"):
        raise ChildError(f"claude 回報 is_error：{str(data.get('result'))[:300]}")
    report = data.get("result")
    if not isinstance(report, str) or not report.strip():
        raise ChildError("claude 輸出缺 result 報告")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model_usage = data.get("modelUsage") if isinstance(data.get("modelUsage"), dict) else {}
    meta = {
        "session_id": data.get("session_id"),
        "model": next(iter(model_usage), None),
        "turns": _int(data.get("num_turns")),
        "cost_usd": data.get("total_cost_usd") if isinstance(data.get("total_cost_usd"), (int, float)) else None,
        **{k: _int(usage.get(k)) for k in TOKEN_FIELDS},
    }
    return report, meta


def load_codex_agent(role):
    path = os.path.join(".codex", "agents", f"{role}.toml")
    if not os.path.exists(path):
        fail(f"{path} 不存在（codex 後端需先跑 install_codex.py 產生角色設定）", 1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def run_codex(role, prompt, resume, timeout):
    agent = load_codex_agent(role)
    argv = ["codex", "exec"]
    if resume:
        argv += ["resume", resume]
    argv += [
        "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
        "-m", str(agent.get("model", "")),
        "-c", f"model_reasoning_effort={agent.get('model_reasoning_effort', 'medium')}",
        "-",
    ]
    stdin_text = f"{agent.get('developer_instructions', '')}\n\n{prompt}"
    proc = _run(argv, stdin_text, timeout)
    if proc.returncode != 0:
        raise ChildError(f"codex exit {proc.returncode}：{(proc.stderr or proc.stdout).strip()[-500:]}")
    thread_id, report, usage = None, None, {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id")
        elif kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                report = item["text"]
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    if not report or not report.strip():
        raise ChildError("codex 輸出無 agent_message 報告")
    meta = {
        "session_id": thread_id,
        "model": agent.get("model"),
        "turns": 1,
        "cost_usd": None,
        **_zero_tokens(),
    }
    for src, dst in CODEX_USAGE_MAP.items():
        meta[dst] = _int(usage.get(src))
    return report, meta


BACKENDS = {"claude": run_claude, "codex": run_codex}


def git_status_paths():
    """`git status --porcelain -z` 的路徑集合（R-003：NUL 分割，rename／copy 兩段路徑都收；
    不以空白 split）。非 git repo 等失敗回 None（呼叫端 fail-open）。"""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "-z"],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    tokens = out.split(b"\0")
    paths = set()
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        paths.add(os.fsdecode(path))
        if (b"R" in xy or b"C" in xy) and i < len(tokens):
            paths.add(os.fsdecode(tokens[i]))  # rename／copy：下一個 token 是原路徑
            i += 1
    return paths


def out_of_scope_changes(before, after, allowed):
    """派工後新出現的變更路徑中，不在 allowed 清單者（排序後回傳）。"""
    return sorted(p for p in (after - before) if p not in allowed)


def append_record(run_id, record):
    """旁路留痕：寫入失敗只 stderr warning、不改 exit code（同 eval_state.append_event 慣例）。"""
    if not run_id:
        print("[dispatch] 無進行中的 run（eval_state.json／tier 1 in_progress manifest 皆無），不寫派工留痕", file=sys.stderr)
        return
    try:
        os.makedirs("run", exist_ok=True)
        with open(os.path.join("run", f"{run_id}.dispatch.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[dispatch] 警告：派工留痕寫入失敗（{e}），不影響本次派工", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role")
    parser.add_argument("--prompt-file", required=True, dest="prompt_file")
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=None)
    parser.add_argument("--resume", default=None)
    parser.add_argument("--files", default=None, help="本 item 允許變更的檔案（逗號分隔，repo 相對路徑）")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--max-output-chars", type=int, default=60000, dest="max_output_chars")
    args = parser.parse_args()

    if not os.path.exists(os.path.join(AGENTS_DIR, f"{args.role}.md")):
        fail(f"角色 {args.role} 無對應 {AGENTS_DIR}/{args.role}.md", 1)
    prompt = read_prompt(args.prompt_file)
    run_id = resolve_run_id()
    backend = args.backend or default_backend(run_id)
    allowed = {p.strip() for p in args.files.split(",") if p.strip()} if args.files is not None else None
    before = git_status_paths() if allowed is not None else None
    if allowed is not None and before is None:
        print("[dispatch] 非 git repo，略過越界檢查", file=sys.stderr)

    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "role": args.role, "backend": backend, "session_id": None,
        "resumed": bool(args.resume), "model": None, "turns": 0,
        **_zero_tokens(), "cost_usd": None, "duration_ms": 0, "exit_code": 0, "envelope": None,
        "failure": None, "out_of_scope": None,
    }
    started = time.monotonic()
    try:
        report, meta = BACKENDS[backend](args.role, prompt, args.resume, args.timeout)
    except ChildError as e:
        record.update(duration_ms=int((time.monotonic() - started) * 1000), exit_code=3, failure=e.kind)
        append_record(run_id, record)
        fail(str(e), 3)
    record.update(meta, duration_ms=int((time.monotonic() - started) * 1000))

    if len(report) > args.max_output_chars:
        record.update(exit_code=3, failure="output_truncated")
        sys.stdout.write(report[:args.max_output_chars])
        sys.stdout.write(f"\n[dispatch] 輸出截斷：{len(report)} 字元超過上限 {args.max_output_chars}\n")
        sys.stdout.flush()
        append_record(run_id, record)
        fail(f"報告 {len(report)} 字元超過上限 {args.max_output_chars}，已截斷、不做信封判定", 3)

    blocking, advisory = report_envelope_check.check_envelope(report, args.role)
    record["envelope"] = "blocking" if blocking else ("advisory" if advisory else "ok")
    if allowed is not None and before is not None:
        after = git_status_paths()
        record["out_of_scope"] = out_of_scope_changes(before, after, allowed) if after is not None else None
    out_of_scope = record["out_of_scope"] or []
    record["exit_code"] = 4 if out_of_scope else (2 if blocking else 0)

    sys.stdout.write(report if report.endswith("\n") else report + "\n")
    sys.stdout.flush()
    tokens = sum(record[k] for k in TOKEN_FIELDS)
    cost = f"{record['cost_usd']:.4f}" if isinstance(record["cost_usd"], (int, float)) else "n/a"
    print(f"[dispatch] role={args.role} backend={backend} session={record['session_id']} "
          f"turns={record['turns']} tokens={tokens} cost_usd={cost}", file=sys.stderr)
    if out_of_scope:
        print(f"[dispatch] 越界變更：{', '.join(out_of_scope)}（不在 --files 清單內，退件）", file=sys.stderr)
    append_record(run_id, record)

    if blocking:
        print(f"[dispatch] 信封缺損（{args.role}）：{'、'.join(blocking + advisory)}。退件重取：以 --resume "
              f"{record['session_id']} 重新派工補齊信封（首行戳記行、末行恰一個 Self-check:）。"
              f"重取上限見 eval-flow SKILL.md 憑據紀律。", file=sys.stderr)
    elif advisory:
        print(f"[dispatch] 警告（{args.role}）：缺{'、'.join(advisory)}，表現層缺項不退件；主 flow 於回報留痕一句。",
              file=sys.stderr)
    sys.exit(record["exit_code"])


if __name__ == "__main__":
    main()
