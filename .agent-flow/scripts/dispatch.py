#!/usr/bin/env python3
"""subagent 派工：以 headless CLI 子程序執行流程角色（`claude -p` 預設、`codex exec` 備選）。

用法：
  python3 .agent-flow/scripts/dispatch.py <role> --prompt-file <path|-> [--backend claude|codex] [--resume <session_id>]
                                    [--files <逗號清單>] [--timeout <秒>] [--max-output-chars <n>]

- `<role>`：`.agent-flow/roles/<role>.md` 存在者（舊部署退回 `.claude/agents/`）（code-writer／task-verifier／…）；不存在 → exit 1
- `--prompt-file`：派工 prompt 全文（`-`＝stdin）。約定路徑 `run/<run_id>.prompt-<role>-<n>.md`。
  內容為空或只有空白字元 → exit 1、不呼叫子程序、不落留痕（空指令派工等於沒派工）
- `--backend`：省略時依 manifest `harness`（claude／codex；缺值使用 claude，非法值報錯）
- `--resume`：修正輪沿用同一子 session（claude session_id／codex thread_id）
- `--files`：本 item 允許變更的檔案清單（repo 相對路徑）。role 為 code-writer 且無 `--resume` 時，另依此清單
  以 retro_select 篩選 `retro/RETRO.md`，把選中條目附加到 prompt 末尾的硬性約束節（主 flow 不讀 RETRO.md、不貼條目）；
  RETRO.md 不存在或推不出模組名片段 → 該節寫一句原因、stderr 一句，exit code 不受影響。派工前後各取一次 `git status --porcelain -z`，
  「派工後有、派工前無」且不在清單內的路徑＝越界 → stderr 列出、留痕 `out_of_scope`、exit 4（報告仍印出）。
  未給＝不檢查；非 git repo＝不檢查（fail-open，stderr 一句）
- `--timeout`：子程序秒數上限（預設 1200）；超時終止 → 留痕 `failure="timed_out"`、exit 3
- `--max-output-chars`：報告字元上限（預設 60000）；超量 → stdout 只印前 n 字元＋截斷末行、留痕
  `failure="output_truncated"`、exit 3、不做信封判定

權限：省略 `--permissions` 時依角色選擇：有寫入工具的角色用 `edits`（Claude `--permission-mode acceptEdits`、
Codex `--sandbox workspace-write`，只自動允許工作目錄內的檔案編輯），其他角色用 `inherit`（不附權限覆寫，遵守各 CLI
設定；不保證繼承未保存的父程序權限）。明確給 `--permissions unrestricted` 才使用各 CLI 的完整權限旗標。
子 agent 有工具呼叫被權限拒絕（Claude 結果的 `permission_denials`）→ stderr 列出工具名、exit 2。
CLI argv 與結果格式由 harness_adapter.py 轉換。

輸出契約：
  stdout ＝ 子 agent 報告全文（claude：JSON `result`；codex：最後一個 agent_message 的 text），不夾其他行
  stderr ＝ 摘要行 `[dispatch] role=… backend=… session=… turns=… tokens=… cost_usd=…`（＋信封訊息）
  exit   ＝ 0 正常／advisory；1 用法錯誤；2 信封 blocking（報告仍完整輸出）；3 子程序失敗／超時／超量；
           4 越界變更（報告仍完整輸出；優先於 2）

留痕：每次派工 append `run/<run_id>.dispatch.jsonl` 一行（鍵集見 append_record；純記錄、不被 gate 消費）。
run_id 解析沿用 run_evidence 既有基準（R-009）：eval_state.json → 唯一 tier 1 in_progress manifest；
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

HOOKS_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HOOKS_DIR)
import harness_adapter  # noqa: E402
import flow_rules
import run_evidence  # noqa: E402
import report_envelope_check  # noqa: E402
import retro_select  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HOOKS_DIR))
AGENTS_DIR = os.path.join(ROOT, ".agent-flow", "roles")
LEGACY_AGENTS_DIR = os.path.join(ROOT, ".claude", "agents")
MODELS_PATH = os.path.join(ROOT, ".agent-flow", "harnesses", "models.json")
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
    """共用 run_evidence 的定位基準：eval_state.json 優先，否則唯一 tier 1 in_progress。"""
    if os.path.exists("eval_state.json"):
        state = run_evidence.load_json_quiet("eval_state.json")
        if isinstance(state, dict) and state.get("run_id"):
            return state["run_id"]
    found = run_evidence.find_unique_tier1_inprogress()
    if found:
        return flow_rules.MANIFEST_RE.match(found[0]).group("run_id")
    return None


def default_backend(run_id):
    if run_id:
        manifest = run_evidence.load_json_quiet(f"run/{run_id}.json")
        if isinstance(manifest, dict) and "harness" in manifest:
            harness = manifest["harness"]
            if harness not in ("claude", "codex"):
                fail(f"manifest harness 非法：{harness!r}", 1)
            return harness
    return "claude"


def default_permissions(role):
    """省略 --permissions 時：角色有寫入工具（models.json Claude frontmatter 的 tools 行含 Write／Edit）→ edits，
    否則 inherit。headless 子程序不能互動批准，有寫入職責的角色在 inherit 下會被拒寫（2026-10-09 實測）。"""
    try:
        with open(MODELS_PATH, encoding="utf-8") as f:
            frontmatter = json.load(f)["claude"][role]["frontmatter"]
    except (OSError, ValueError, KeyError, TypeError):
        return "inherit"
    tools = next((line for line in str(frontmatter).splitlines() if line.startswith("tools:")), "")
    return "edits" if {"Write", "Edit"} & {t.strip() for t in tools[6:].split(",")} else "inherit"


def read_prompt(path):
    if path == "-":
        text, src = sys.stdin.read(), "stdin 的 prompt"
    else:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            fail(f"讀不到 prompt 檔 {path}（{e}）", 1)
        src = f"prompt 檔 {path}"
    # 空 prompt 不可派工：子 agent 會拿著空指令照自己的 system prompt 亂跑，主 flow 卻以為派了工。
    # 實測成因（2026-10-03）：未加引號的 heredoc 把 markdown 反引號當命令替換執行並卡在等 stdin，
    # 寫檔中斷、留下 0 字節 prompt 檔。此處與「讀不到檔」同屬使用錯誤，exit 1。
    if not text.strip():
        fail(f"{src} 為空（或只有空白字元），不派工", 1)
    return text


def _run(argv, stdin_text, timeout):
    try:
        return subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # subprocess.run 於超時已 kill 子程序並回收
        raise ChildError(f"{argv[0]} 超過 timeout {timeout:g} 秒，子程序已終止", kind="timed_out")
    except OSError as e:
        raise ChildError(f"無法啟動 {argv[0]}（{e}）")


def _child_result(backend, proc):
    data = harness_adapter.parse_result(backend, proc.stdout, proc.returncode)
    if data['is_error']:
        detail = (proc.stderr or data['error'] or '').strip()[-500:]
        raise ChildError(f"{backend}: {detail}")
    usage = data['usage']
    meta = {'session_id': data['session_id'], 'model': data['model'],
            'turns': data['num_turns'] or 0, 'cost_usd': data['total_cost_usd'],
            'permission_denials': data['permission_denials'],
            **{k: _int(usage.get(k)) for k in TOKEN_FIELDS}}
    if backend == 'codex':
        for src, dst in CODEX_USAGE_MAP.items():
            meta[dst] = _int(usage.get(src))
    return data['result'], meta


def run_claude(role, prompt, resume, timeout, permissions='inherit'):
    argv = harness_adapter.build_argv('claude', role=role, resume=resume, permissions=permissions)
    return _child_result('claude', _run(argv, prompt, timeout))


def load_codex_agent(role):
    path = os.path.join(".codex", "agents", f"{role}.toml")
    if not os.path.exists(path):
        fail(f"{path} 不存在（codex 後端需先跑 install_codex.py 產生角色設定）", 1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def run_codex(role, prompt, resume, timeout, permissions='inherit'):
    agent = load_codex_agent(role)
    argv = harness_adapter.build_argv('codex', model=agent.get('model'),
                                     reasoning_effort=agent.get('model_reasoning_effort', 'low'),
                                     resume=resume, permissions=permissions)
    stdin_text = f"{agent.get('developer_instructions', '')}\n\n{prompt}"
    report, meta = _child_result('codex', _run(argv, stdin_text, timeout))
    meta['model'] = agent.get('model')
    return report, meta


BACKENDS = {"claude": run_claude, "codex": run_codex}


RETRO_PATH = "retro/RETRO.md"
RETRO_SECTION = "## 硬性約束區（retro 條目，dispatch 依 --files 自動前置）"


def retro_prefix(files, root="."):
    """依 files 篩選 RETRO.md，回傳 (附加到 prompt 的文字, 留痕 dict, 需印到 stderr 的一句或 None)。

    主 flow 不再讀 RETRO.md 或執行 retro_select：選中條目只進 writer prompt，主 session 只看到計數。
    fail-open：RETRO.md 不存在或 files 推不出片段時仍派工，該節寫原因（知識前置留痕，防跳步）。
    """
    def section(lines):
        return "\n\n" + RETRO_SECTION + "\n\n" + "\n".join(lines) + "\n"
    try:
        with open(RETRO_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        note = f"知識前置（retro）：{RETRO_PATH} 不存在，無條目"
        return section([note]), {"selected": [], "retire": []}, note
    fragments = retro_select.module_fragments(files)
    if not fragments:
        note = "知識前置（retro）：--files 推導不出模組名片段，無條目"
        return section([note]), {"selected": [], "retire": []}, note
    entries = retro_select.parse_entries(text)
    excludes = retro_select._anchor_scan_excludes(RETRO_PATH, root)
    chosen, retire = retro_select.select(entries, fragments, root, excludes)
    lines = [e["text"] for e in chosen] or ["知識前置（retro）：無相關條目"]
    return section(lines), {"selected": [e["id"] for e in chosen], "retire": [e["id"] for e in retire]}, None


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
    parser.add_argument("--review-packet", help="validated review data for task-verifier only")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--permissions", choices=harness_adapter.PERMISSIONS, default=None,
                        help="inherit: keep CLI settings; edits: auto-accept file edits; unrestricted: explicit "
                             "full access; omitted: edits for roles with write tools, else inherit")
    parser.add_argument("--files", default=None, help="本 item 允許變更的檔案（逗號分隔，repo 相對路徑）")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--max-output-chars", type=int, default=60000, dest="max_output_chars")
    args = parser.parse_args()
    permissions = args.permissions or default_permissions(args.role)

    if not any(os.path.isfile(os.path.join(directory, f"{args.role}.md"))
               for directory in (AGENTS_DIR, LEGACY_AGENTS_DIR)):
        fail(f"角色 {args.role} 無對應 {AGENTS_DIR}/{args.role}.md", 1)
    prompt = read_prompt(args.prompt_file)
    run_id = resolve_run_id()
    if args.review_packet:
        if args.role != "task-verifier":
            fail("--review-packet is only supported for task-verifier", 1)
        if not run_id:
            fail("--review-packet requires an active run", 1)
        import review_packet
        try:
            packet = review_packet.validate(args.review_packet, run_id)
        except (ValueError, OSError, TypeError) as error:
            fail(str(error), 1)
        prompt += "\n\n" + review_packet.render(packet)
    manifest_backend = default_backend(run_id)
    backend = args.backend or manifest_backend
    allowed = {p.strip() for p in args.files.split(",") if p.strip()} if args.files is not None else None
    retro = None
    if args.role == "code-writer" and allowed is not None and not args.resume:
        extra, retro, note = retro_prefix(sorted(allowed))
        prompt += extra
        if note:
            print(f"[dispatch] {note}", file=sys.stderr)
    before = git_status_paths() if allowed is not None else None
    if allowed is not None and before is None:
        print("[dispatch] 非 git repo，略過越界檢查", file=sys.stderr)

    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "role": args.role, "backend": backend, "permissions": permissions, "session_id": None,
        "resumed": bool(args.resume), "model": None, "turns": 0,
        **_zero_tokens(), "cost_usd": None, "duration_ms": 0, "exit_code": 0, "envelope": None,
        "failure": None, "out_of_scope": None, "retro": retro, "permission_denials": [],
    }
    started = time.monotonic()
    try:
        report, meta = BACKENDS[backend](args.role, prompt, args.resume, args.timeout, permissions)
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
    denials = record["permission_denials"]
    record["exit_code"] = 4 if out_of_scope else (2 if blocking or denials else 0)

    sys.stdout.write(report if report.endswith("\n") else report + "\n")
    sys.stdout.flush()
    tokens = sum(record[k] for k in TOKEN_FIELDS)
    cost = f"{record['cost_usd']:.4f}" if isinstance(record["cost_usd"], (int, float)) else "n/a"
    print(f"[dispatch] role={args.role} backend={backend} session={record['session_id']} "
          f"turns={record['turns']} tokens={tokens} cost_usd={cost}", file=sys.stderr)
    if retro is not None:
        print(f"[dispatch] retro 選中 {len(retro['selected'])}（{', '.join(retro['selected']) or '無'}）、"
              f"retire 候選 {len(retro['retire'])}（{', '.join(retro['retire']) or '無'}）", file=sys.stderr)
    if out_of_scope:
        print(f"[dispatch] 越界變更：{', '.join(out_of_scope)}（不在 --files 清單內，退件）", file=sys.stderr)
    if denials:
        print(f"[dispatch] 子 agent 有 {len(denials)} 次工具呼叫被權限拒絕（{', '.join(sorted(set(denials)))}）："
              f"交付不完整；以 --permissions edits／unrestricted 重派或改用原生 Agent", file=sys.stderr)
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
