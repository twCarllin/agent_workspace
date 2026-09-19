#!/usr/bin/env python3
"""Token 用量實測：從 Claude Code transcript（*.jsonl）算出一個 run 實際耗用的 token。

用法：
  python3 .claude/hooks/token_usage.py <run_id> [--dir run] [--full-session] [--write] [--projects-root <dir>]

定位 transcript：
  manifest `run/<run_id>.json` 有 `session_id`／`config_dir` → 主 flow 檔＝
  `<config_dir>/projects/<cwd 編碼>/<session_id>.jsonl`，subagent 檔＝同層
  `<session_id>/subagents/agent-*.jsonl`，各配同名 `.meta.json`（鍵 `agentType`、
  `description`）。cwd 編碼＝`re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())`。
  `--projects-root` 給定時直接以該目錄替代 `<config_dir>/projects/<cwd 編碼>/`
  （測試注入用，免動 HOME）。

  manifest 無 `session_id`（舊 run）→ glob `~/.claude*/projects/*/*.jsonl`
  （`--projects-root` 給定時改 glob `<projects-root>/*.jsonl`），挑檔內含 run_id
  字串者，逐檔照同法加總（其 subagents 目錄一併算）；候選檔 0 個 → stderr 訊息、exit 1。

時間窗：讀 `run/<run_id>.events.jsonl` 全部行的 `ts` 取 min／max 為 [lo, hi]；
  transcript 每行 `type == "assistant"` 且 `timestamp` 落在窗內者計入。
  `--full-session` 或 events 檔不存在 → 不切窗、整檔計入。

分類：subagent `agentType` ∈ {usage-analyzer, task-decomposer, impact-analyzer} → prep；
  其餘（含缺 meta）→ loop。

`--write`：回寫 manifest `subagent_usage`（prep／loop／main 三個 int 總數）與
  `token_usage`（明細：session_id、window、main、subagents）；其他欄位不動。
  無 `--write` 不寫任何檔。
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402  重用 MANIFEST_RE（單一判定點鐵律，禁止自建第三份 pattern）

TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
PREP_AGENT_TYPES = {"usage-analyzer", "task-decomposer", "impact-analyzer"}


def load(path):
    """比照 stats.py 的 `load()`：壞 JSON／不存在一律寬容回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _parse_events(path):
    """讀 events.jsonl；檔不存在回 None，壞行寬容跳過（比照 stats.py `_parse_events`）。"""
    if not os.path.exists(path):
        return None
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _manifest_path(dir_, run_id):
    """比照 devlog.py list_run_ids：MANIFEST_RE 錨定字面 "run/" 前綴，與 --dir 值無關，
    用 basename 重組固定前綴比對，維持單一判定點（R-009）。"""
    name = f"{run_id}.json"
    if not eval_gates.MANIFEST_RE.match("run/" + name):
        return None
    return os.path.join(dir_, name)


def _zero_usage():
    return {**{k: 0 for k in TOKEN_FIELDS}, "turns": 0}


def _add_usage(a, b):
    out = {k: a.get(k, 0) + b.get(k, 0) for k in TOKEN_FIELDS}
    out["turns"] = a.get("turns", 0) + b.get("turns", 0)
    return out


def _sum4(usage):
    return sum(usage.get(k, 0) for k in TOKEN_FIELDS)


def _sum4_list(usages):
    return sum(_sum4(u) for u in usages)


def _parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def get_window(events_path, full_session):
    """回傳 (lo, hi) datetime 或 (None, None)（無切窗）。
    `--full-session` 或 events 檔不存在（`_parse_events` 回 None）→ 不切窗。"""
    if full_session:
        return None, None
    events = _parse_events(events_path)
    if events is None:
        return None, None
    timestamps = []
    for e in events:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts")
        if not ts:
            continue
        try:
            timestamps.append(_parse_ts(ts))
        except ValueError:
            continue
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def read_jsonl_usage(path, lo, hi):
    """讀一個 transcript jsonl 檔，加總落在 [lo, hi] 窗內（lo/hi 皆 None＝不切窗）的
    assistant 訊息 usage 四欄＋turns。壞 JSON 行寬容跳過，不 crash。"""
    totals = _zero_usage()
    if not os.path.exists(path):
        return totals
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "assistant":
                continue
            if lo is not None and hi is not None:
                ts = obj.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = _parse_ts(ts)
                except ValueError:
                    continue
                if not (lo <= dt <= hi):
                    continue
            usage = (obj.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                usage = {}
            for k in TOKEN_FIELDS:
                v = usage.get(k, 0)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    totals[k] += v
            totals["turns"] += 1
    return totals


def read_meta(jsonl_path):
    if jsonl_path.endswith(".jsonl"):
        meta_path = jsonl_path[: -len(".jsonl")] + ".meta.json"
    else:
        meta_path = jsonl_path + ".meta.json"
    data = load(meta_path)
    return data if isinstance(data, dict) else {}


def collect_subagents(subagents_dir, lo, hi):
    subagents = []
    if not os.path.isdir(subagents_dir):
        return subagents
    for jsonl_path in sorted(glob.glob(os.path.join(subagents_dir, "agent-*.jsonl"))):
        usage = read_jsonl_usage(jsonl_path, lo, hi)
        meta = read_meta(jsonl_path)
        subagents.append({
            "agent_type": meta.get("agentType"),
            "description": (meta.get("description") or "")[:30],
            **usage,
        })
    return subagents


def _contains_run_id(path, run_id):
    try:
        with open(path, encoding="utf-8") as f:
            return run_id in f.read()
    except OSError:
        return False


def resolve_usage(manifest, args, lo, hi):
    """定位並加總 main + subagents。無候選（fallback 零候選）時印 stderr 並 exit 1。"""
    session_id = manifest.get("session_id")

    if session_id:
        config_dir = manifest.get("config_dir") or os.path.expanduser("~/.claude")
        if args.projects_root:
            base_dir = args.projects_root
        else:
            cwd_encoded = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
            base_dir = os.path.join(config_dir, "projects", cwd_encoded)
        main_path = os.path.join(base_dir, f"{session_id}.jsonl")
        subagents_dir = os.path.join(base_dir, session_id, "subagents")
        main_usage = read_jsonl_usage(main_path, lo, hi)
        subagents = collect_subagents(subagents_dir, lo, hi)
        return session_id, main_usage, subagents

    if args.projects_root:
        pattern = os.path.join(args.projects_root, "*.jsonl")
    else:
        pattern = os.path.expanduser("~/.claude*/projects/*/*.jsonl")
    candidates = [p for p in sorted(glob.glob(pattern)) if _contains_run_id(p, args.run_id)]
    if not candidates:
        print(
            f"[token-usage] 找不到 run_id={args.run_id} 對應的 transcript"
            "（manifest 無 session_id，fallback 掃描也無候選）",
            file=sys.stderr,
        )
        sys.exit(1)

    main_usage = _zero_usage()
    subagents = []
    for candidate in candidates:
        main_usage = _add_usage(main_usage, read_jsonl_usage(candidate, lo, hi))
        base_no_ext = candidate[: -len(".jsonl")] if candidate.endswith(".jsonl") else candidate
        subagents += collect_subagents(os.path.join(base_no_ext, "subagents"), lo, hi)
    return None, main_usage, subagents


def _fmt(u):
    return (
        f"input={u['input_tokens']} cache_creation={u['cache_creation_input_tokens']} "
        f"cache_read={u['cache_read_input_tokens']} output={u['output_tokens']} turns={u['turns']}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("--dir", default="run")
    parser.add_argument("--full-session", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--projects-root", default=None)
    args = parser.parse_args()

    manifest_path = _manifest_path(args.dir, args.run_id)
    manifest = load(manifest_path) if manifest_path else None
    if not isinstance(manifest, dict):
        manifest = {}

    events_path = os.path.join(args.dir, f"{args.run_id}.events.jsonl")
    lo, hi = get_window(events_path, args.full_session)

    session_id, main_usage, subagents = resolve_usage(manifest, args, lo, hi)

    prep = [s for s in subagents if s.get("agent_type") in PREP_AGENT_TYPES]
    loop = [s for s in subagents if s.get("agent_type") not in PREP_AGENT_TYPES]

    print(f"main: {_fmt(main_usage)}")
    for s in subagents:
        label = f"{s.get('agent_type') or '(no-meta)'} {s.get('description', '')}"
        print(f"{label}: {_fmt(s)}")
    total = main_usage
    for s in subagents:
        total = _add_usage(total, s)
    print(f"total: {_fmt(total)}")

    if args.write:
        if not manifest_path or not os.path.isfile(manifest_path):
            print(f"[token-usage] --write 需要既有 manifest：{args.dir}/{args.run_id}.json 不存在", file=sys.stderr)
            sys.exit(1)
        manifest["subagent_usage"] = {
            "prep": _sum4_list(prep),
            "loop": _sum4_list(loop),
            "main": _sum4(main_usage),
        }
        manifest["token_usage"] = {
            "session_id": session_id,
            "window": [lo.isoformat(), hi.isoformat()] if lo is not None and hi is not None else None,
            "main": main_usage,
            "subagents": subagents,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
