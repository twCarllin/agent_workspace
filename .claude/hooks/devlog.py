#!/usr/bin/env python3
"""Flow 敘事 render：把單一 run 的冷溯源檔渲染成 markdown 摘要。唯讀，不寫任何檔案。

用法：
  python3 .claude/hooks/devlog.py <run_id> [--dir run]
  python3 .claude/hooks/devlog.py [--dir run]   # 無 run_id 時列出可用 run_id 清單

輸出節次（固定）：
  ①run 概要      run_id、tier、created_at、status/phase、tier_rationale、
                  spec_path 或 spec_inline 摘句（來源 manifest `run/<run_id>.json`）
  ②前置軌跡      risk/usage/impact/task_file 路徑與 hitl_confirmed_at、hitl_rejections
                  （來源同上 manifest）
  ③sub_task 逐一  來源 `run/<run_id>.eval.json`；Tier 1 無此檔則改列 manifest 四憑據欄
                  local_test_passed/local_test_evidence/review_reds/verify_passed
  ④時間線        來源 `run/<run_id>.events.jsonl`，逐行 ts+cmd 摘要；無檔顯示「無事件記錄」

一切缺漏欄位顯示 n/a、壞 JSON 行寬容跳過（比照 stats.py `_parse_events`），不猜不虛構。
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402  重用 MANIFEST_RE（單一判定點鐵律，禁止自建第三份 pattern）


def load(path):
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


def _na(v):
    return v if v not in (None, "") else "n/a"


def list_run_ids(run_dir):
    """掃 run_dir 下的 manifest（`eval_gates.MANIFEST_RE` 判定），回傳 run_id 清單。"""
    ids = []
    for path in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
        # MANIFEST_RE 錨定字面 "run/" 前綴（eval_gates.py:43），與 --dir 實際路徑無關；
        # 用 basename 重組固定前綴比對，維持單一判定點且不受 --dir 值影響（reviewer 🟡 1）。
        if not eval_gates.MANIFEST_RE.match("run/" + os.path.basename(path)):
            continue
        m = load(path)
        if isinstance(m, dict) and m.get("run_id"):
            ids.append(m["run_id"])
    return ids


def section_summary(manifest):
    out = ["## ①run 概要"]
    out.append(f"- run_id: {_na(manifest.get('run_id'))}")
    out.append(f"- tier: {_na(manifest.get('tier'))}")
    out.append(f"- created_at: {_na(manifest.get('created_at'))}")
    out.append(f"- status/phase: {_na(manifest.get('status'))}/{_na(manifest.get('phase'))}")
    out.append(f"- tier_rationale: {_na(manifest.get('tier_rationale'))}")
    spec = manifest.get("spec_path") or manifest.get("spec_inline")
    out.append(f"- spec: {_na(spec)}")
    return out


def section_pretrack(manifest):
    out = ["", "## ②前置軌跡"]
    out.append(f"- risk_report_path: {_na(manifest.get('risk_report_path'))}")
    out.append(f"- usage_report_path: {_na(manifest.get('usage_report_path'))}")
    out.append(f"- impact_report_path: {_na(manifest.get('impact_report_path'))}")
    out.append(f"- task_file: {_na(manifest.get('task_file'))}")
    out.append(f"- hitl_confirmed_at: {_na(manifest.get('hitl_confirmed_at'))}")
    out.append(f"- hitl_rejections: {_na(manifest.get('hitl_rejections'))}")
    return out


def section_subtasks(run_id, run_dir, manifest):
    out = ["", "## ③sub_task"]
    archive = load(os.path.join(run_dir, f"{run_id}.eval.json"))
    sub_tasks = archive.get("sub_tasks") if isinstance(archive, dict) else None
    if isinstance(sub_tasks, list):
        for st in sub_tasks:
            rounds = st.get("rounds")
            vc = st.get("verification_commands")
            out.append(
                f"- name={_na(st.get('name'))}｜status={_na(st.get('status'))}｜"
                f"review_reds={_na(st.get('review_reds'))}｜"
                f"rounds={len(rounds) if isinstance(rounds, list) else 'n/a'}｜"
                f"local_test_evidence={_na(st.get('local_test_evidence'))}｜"
                f"verification_commands={len(vc) if isinstance(vc, list) else 'n/a'}"
            )
    else:
        out.append("（Tier 1：無 eval.json，改列 manifest 四憑據欄）")
        out.append(
            f"- local_test_passed={_na(manifest.get('local_test_passed'))}｜"
            f"local_test_evidence={_na(manifest.get('local_test_evidence'))}｜"
            f"review_reds={_na(manifest.get('review_reds'))}｜"
            f"verify_passed={_na(manifest.get('verify_passed'))}"
        )
    return out


def section_timeline(run_id, run_dir):
    out = ["", "## ④時間線"]
    events = _parse_events(os.path.join(run_dir, f"{run_id}.events.jsonl"))
    if not events:
        out.append("無事件記錄")
    else:
        for e in events:
            ts = _na(e.get("ts"))
            cmd = _na(e.get("cmd"))
            args = e.get("args")
            args_str = f" {json.dumps(args, ensure_ascii=False)}" if args else ""
            out.append(f"- {ts} {cmd}{args_str}")
    return out


def render(run_id, run_dir, manifest):
    lines = [f"# devlog：{run_id}"]
    lines += section_summary(manifest)
    lines += section_pretrack(manifest)
    lines += section_subtasks(run_id, run_dir, manifest)
    lines += section_timeline(run_id, run_dir)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id", nargs="?", help="run_id；留空則列出可用清單")
    parser.add_argument("--dir", default="run")
    args = parser.parse_args()

    if args.run_id is None:
        ids = list_run_ids(args.dir)
        if not ids:
            print(f"[devlog] {args.dir}/ 下無可用 run_id", file=sys.stderr)
            sys.exit(1)
        print(f"{args.dir}/ 下可用 run_id：")
        for rid in ids:
            print(f"  {rid}")
        return

    manifest = load(os.path.join(args.dir, f"{args.run_id}.json"))
    if not isinstance(manifest, dict):
        print(f"[devlog] run_id 不存在：{args.dir}/{args.run_id}.json 找不到或非合法 JSON", file=sys.stderr)
        sys.exit(1)

    print(render(args.run_id, args.dir, manifest))


if __name__ == "__main__":
    main()
