#!/usr/bin/env python3
"""Flow 遙測彙總：掃 run/ 的冷溯源檔，輸出系統健康指標。

用法：
  python3 .claude/hooks/stats.py [--dir run]

指標與其回答的問題：
  tier 分佈        分級有沒有發揮省成本作用（Tier 1 幾乎為零 → 門檻太緊）
  waive 率         驗證豁免有沒有變質為常態後門
  HITL 打回率      歷史指標，僅供對照——人閘門的價值信號改看裁示數（實測：打回率 0% 的 HITL 單場出 5 條裁示）
  rework 率（首輪即有 🔴）  幾成 sub_task 首輪就有 review_reds >= 1（需要第二輪）；
                            legacy 歸檔無頂層 review_reds 時 fallback len(rounds) >= 2
  維度分佈         哪個品質維度問題最多（改進 writer prompt 的依據）；
                   優先讀 review_dimensions（維度→問題數）；
                   legacy 的 deduction_reasons（points_lost 加權）併入，標「含 legacy 扣分權重」
  baseline 欠帳    既有壞測試（stable_failures）的走勢
  驗證指令數       每個 run 實際跑了幾條獨立驗證指令（verification_commands）；
                   Tier 1 讀 manifest、Tier 2 讀各 sub_task。鍵不存在＝無記錄（不計入分母），
                   存在但空陣列＝有記錄但 0 條——兩者不可混為一談
  gate 命中        每條 gate 的觸發次數——從不觸發的 gate 是修剪候選
  事件記錄         每 run 的 events.jsonl 事件數／首尾時距／set-step 重入次數（重試信號）；
                   依 `ts` 欄位取極值、依 cmd+step 計數，不依賴檔內物理行序；無 events 檔顯示「無記錄」
  HITL 裁示數      人閘門的價值信號是不是裁示數而非打回率（現行打回率量錯維度）；
                   讀 manifest 選填欄 hitl_rulings（int），輸出分佈＋平均；
                   缺欄的 run 計「無記錄」不入分母
  checker 升級率   修剪審查後 checker 是否真的擋住問題、升級頻率多高；
                   讀 eval.json sub_tasks 的 checked_by 欄（checker／reviewer:碼／null）；
                   null 或缺鍵＝無記錄不入分母；未知值原樣歸「其他」桶顯示，不驗證
  前置/循環成本比  前置流程（Spec／風險／影響）相對執行循環的 token 成本結構；
                   讀 manifest 選填欄 subagent_usage（{"prep","loop"}）；
                   缺欄的 run 計「無記錄」

資料來源：run/*.json（manifest）、run/*.eval.json、run/*.test_baseline.json、
run/*.events.jsonl、run/gate_hits.log。欄位缺漏時顯示 n/a 並註明需要什麼資料，不猜。
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
from collections import Counter

MANIFEST_RE = re.compile(r"^(?P<run_id>[^/]+?)(?<!\.eval)(?<!\.test_baseline)\.json$")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _parse_events(path):
    """讀 events.jsonl；檔不存在回 None（消費端「無記錄」判準），壞行寬容跳過。"""
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


def _events_summary(events):
    """2c：事件數／首尾時距／set-step 重入。依 `ts` 取極值、依 (id, step) 計數，
    不依賴檔內物理行序（usage 正確性假設 1）。"""
    timestamps = []
    for e in events:
        ts = e.get("ts")
        if not ts:
            continue
        try:
            timestamps.append(datetime.datetime.fromisoformat(ts))
        except ValueError:
            continue
    span_seconds = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) >= 2 else None

    step_hits = Counter()
    for e in events:
        if e.get("cmd") == "set-step":
            args = e.get("args", {})
            step_hits[(args.get("id"), args.get("step"))] += 1
    reentry = sum(cnt - 1 for cnt in step_hits.values() if cnt >= 2)

    return {"count": len(events), "span_seconds": span_seconds, "reentry": reentry}


def collect(run_dir="run"):
    data = {
        "runs": [], "tiers": Counter(), "statuses": Counter(),
        "waived": 0, "hitl_confirmed": 0, "hitl_rejections": 0,
        "sub_tasks": 0, "rework": 0,
        "scores": [], "dim_counter": Counter(), "has_legacy_dims": False,
        "baseline": [],  # (run_id, stable)
        "verif_runs": 0, "verif_cmds": 0,
        "gate_hits": Counter(), "gate_hit_lines": [],
        "events": [],  # (run_id, summary dict | None)
        "hitl_rulings": [], "hitl_rulings_missing": 0,
        "checked_by_direct": 0, "checked_by_escalated": 0,
        "checked_by_dist": Counter(), "checked_by_none": 0,
        "subagent_usage": [], "subagent_usage_missing": 0,  # (run_id, prep, loop)
    }
    for path in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
        name = os.path.basename(path)
        if not MANIFEST_RE.match(name):
            continue
        m = load(path)
        if not isinstance(m, dict) or "run_id" not in m:
            continue
        data["runs"].append(m["run_id"])
        data["tiers"][str(m.get("tier"))] += 1
        data["statuses"][str(m.get("status"))] += 1
        if m.get("test_policy") == "waived_by_user":
            data["waived"] += 1
        if m.get("hitl_confirmed_at"):
            data["hitl_confirmed"] += 1
        data["hitl_rejections"] += int(m.get("hitl_rejections") or 0)

        # hitl_rulings：選填 int。鍵不存在或型別不符＝無記錄不計分母（沿既有寬容讀法原則）
        rulings = m.get("hitl_rulings")
        if isinstance(rulings, int) and not isinstance(rulings, bool):
            data["hitl_rulings"].append(rulings)
        else:
            data["hitl_rulings_missing"] += 1

        # subagent_usage：選填 {"prep": int, "loop": int}。缺鍵／非 dict／欄位非 int 一律寬容跳過
        usage = m.get("subagent_usage")
        if (
            isinstance(usage, dict)
            and isinstance(usage.get("prep"), int) and not isinstance(usage.get("prep"), bool)
            and isinstance(usage.get("loop"), int) and not isinstance(usage.get("loop"), bool)
        ):
            data["subagent_usage"].append((m["run_id"], usage["prep"], usage["loop"]))
        else:
            data["subagent_usage_missing"] += 1

        # verification_commands：Tier 1 記在 manifest、Tier 2 記在各 sub_task（下方 archive 迴圈併計）。
        # 鍵不存在＝該 run 無記錄（不計入平均分母）；存在但為空陣列＝有記錄但 0 條
        verif_recorded = isinstance(m.get("verification_commands"), list)
        verif_cmds = len(m["verification_commands"]) if verif_recorded else 0

        archive = load(os.path.join(run_dir, f"{m['run_id']}.eval.json"))
        if isinstance(archive, dict):
            for st in archive.get("sub_tasks", []):
                rounds = st.get("rounds", [])
                data["sub_tasks"] += 1
                # rework：優先讀頂層 review_reds；legacy 歸檔（無頂層 review_reds）fallback rounds 數
                top_reds = st.get("review_reds")
                if top_reds is not None:
                    if isinstance(top_reds, int) and not isinstance(top_reds, bool) and top_reds >= 1:
                        data["rework"] += 1
                else:
                    if len(rounds) >= 2:
                        data["rework"] += 1
                # legacy quality_score
                for rnd in rounds:
                    score = rnd.get("quality_score")
                    if isinstance(score, (int, float)):
                        data["scores"].append(score)
                # 維度分佈：優先讀 review_dimensions（維度→問題數）
                sub_vc = st.get("verification_commands")
                if isinstance(sub_vc, list):
                    verif_recorded = True
                    verif_cmds += len(sub_vc)
                # checker 升級率：checked_by 欄。null／缺鍵＝無記錄；"checker"＝直過；
                # 其餘任何值（reviewer:碼 或未知值，不驗證）＝升級，計入分佈
                checked_by = st.get("checked_by")
                if checked_by == "checker":
                    data["checked_by_direct"] += 1
                elif checked_by:
                    data["checked_by_escalated"] += 1
                    data["checked_by_dist"][checked_by] += 1
                else:
                    data["checked_by_none"] += 1

                review_dims = st.get("review_dimensions")
                if isinstance(review_dims, dict):
                    for dim, cnt in review_dims.items():
                        if isinstance(cnt, (int, float)):
                            data["dim_counter"][dim] += cnt
                else:
                    # legacy：從 rounds 的 deduction_reasons 累加 points_lost
                    for rnd in rounds:
                        for d in rnd.get("deduction_reasons", []):
                            pts = d.get("points_lost", 0)
                            if pts:
                                data["dim_counter"][d.get("dimension", "?")] += pts
                                data["has_legacy_dims"] = True

        if verif_recorded:
            data["verif_runs"] += 1
            data["verif_cmds"] += verif_cmds

        base = load(os.path.join(run_dir, f"{m['run_id']}.test_baseline.json"))
        if isinstance(base, dict):
            data["baseline"].append(
                (m["run_id"], len(base.get("stable_failures", [])))
            )

        events = _parse_events(os.path.join(run_dir, f"{m['run_id']}.events.jsonl"))
        data["events"].append(
            (m["run_id"], _events_summary(events) if events is not None else None)
        )

    # Tier 0 留痕（run/tier0.jsonl，eval_state.py tier0 產出）：沿用 _parse_events 寬容讀法（R-009）
    tier0_entries = _parse_events(os.path.join(run_dir, "tier0.jsonl"))
    if tier0_entries is None:
        data["tier0"] = None
    else:
        valid = [e for e in tier0_entries if isinstance(e, dict)]
        data["tier0"] = {
            "count": len(valid),
            "lines": sum(e["lines"] for e in valid
                         if isinstance(e.get("lines"), int) and not isinstance(e.get("lines"), bool)),
            "last_ts": max((e["ts"] for e in valid if isinstance(e.get("ts"), str)), default=None),
        }

    log_path = os.path.join(run_dir, "gate_hits.log")
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                data["gate_hit_lines"].append(line)
                msg = line.split("\t", 1)[-1]
                key = msg.split("：")[0].split(":")[0][:40]  # 訊息開頭當 gate 識別
                data["gate_hits"][key] += 1
    return data


def pct(n, d):
    return f"{100 * n / d:.0f}%（{n}/{d}）" if d else "n/a（無資料）"


def append_hitl_rulings(out, data):
    if data["hitl_rulings"]:
        dist = Counter(data["hitl_rulings"])
        avg = sum(data["hitl_rulings"]) / len(data["hitl_rulings"])
        out.append(
            f"HITL 裁示數：分佈 {dict(sorted(dist.items()))}　平均 {avg:.1f}"
            f"　無記錄：{data['hitl_rulings_missing']} 個 run"
        )
    else:
        out.append("HITL 裁示數：無記錄（需要 hitl_rulings）")


def append_checker_escalation(out, data):
    direct = data["checked_by_direct"]
    escalated = data["checked_by_escalated"]
    total = direct + escalated
    if total:
        dist = dict(data["checked_by_dist"].most_common())
        out.append(
            f"checker 升級率：{pct(escalated, total)}"
            f"（直過 {direct}／升級 {escalated}；reviewer 分佈 {dist}）"
            f"　無記錄：{data['checked_by_none']} 個 sub_task"
        )
    else:
        out.append("checker 升級率：無記錄（需要 checked_by）")


def append_subagent_usage(out, data):
    if data["subagent_usage"]:
        parts = [f"{run_id}: prep {prep}／loop {loop}" for run_id, prep, loop in data["subagent_usage"]]
        total_prep = sum(prep for _, prep, _ in data["subagent_usage"])
        total_loop = sum(loop for _, _, loop in data["subagent_usage"])
        ratio = f"{total_prep / total_loop:.2f}" if total_loop else "n/a"
        out.append(
            f"前置/循環成本比：{'、'.join(parts)}　合計比值 prep:loop = {ratio}"
            f"　無記錄：{data['subagent_usage_missing']} 個 run"
        )
    else:
        out.append("前置/循環成本比：無記錄（需要 subagent_usage）")


def append_gate_hits(out, data):
    if data["gate_hits"]:
        out.append("gate 命中（從不觸發的 gate 是修剪候選）：")
        for key, cnt in data["gate_hits"].most_common():
            out.append(f"  {cnt:>3} × {key}")
    else:
        out.append("gate 命中：0（gate_hits.log 無記錄）")


def report(data):
    out = []
    n_runs = len(data["runs"])
    out.append(f"== Flow 遙測（{n_runs} 個 run）==")
    if not n_runs:
        out.append("run/ 無 manifest——尚無 run 資料可統計")
        append_gate_hits(out, data)  # gate 攔截可能先於第一個完成的 run
        return "\n".join(out)
    out.append(f"tier 分佈：{dict(data['tiers'])}　status：{dict(data['statuses'])}")
    t0 = data.get("tier0")
    if t0:
        last = t0["last_ts"] or "n/a"
        out.append(f"Tier 0 留痕：{t0['count']} 筆／合計 {t0['lines']} 行／最近一筆 {last}")
    else:
        out.append("Tier 0 留痕：無記錄（需要 run/tier0.jsonl，見 eval_state.py tier0）")
    out.append(f"waive 率：{pct(data['waived'], n_runs)}")
    hitl_total = data["hitl_confirmed"] + data["hitl_rejections"]
    out.append(f"HITL 打回率：{pct(data['hitl_rejections'], hitl_total)}（歷史指標，價值信號看裁示數）")
    append_hitl_rulings(out, data)
    out.append(f"rework 率（首輪即有 🔴）：{pct(data['rework'], data['sub_tasks'])}")
    append_checker_escalation(out, data)
    if data["scores"]:
        out.append(f"quality_score（legacy）：平均 {sum(data['scores']) / len(data['scores']):.1f}（{len(data['scores'])} rounds）")
    if data["dim_counter"]:
        suffix = "（含 legacy 扣分權重）" if data["has_legacy_dims"] else ""
        out.append(f"維度分佈{suffix}：{dict(data['dim_counter'].most_common())}")
    if data["verif_runs"]:
        avg = data["verif_cmds"] / data["verif_runs"]
        out.append(
            f"驗證指令數：共 {data['verif_cmds']} 條／{data['verif_runs']} 個有記錄的 run"
            f"（平均 {avg:.1f} 條）　無記錄：{n_runs - data['verif_runs']} 個 run"
        )
    else:
        out.append(f"驗證指令數：無記錄（{n_runs} 個 run 皆無 verification_commands 欄位）")
    if data["baseline"]:
        trend = "、".join(f"{r}: stable {s}" for r, s in data["baseline"])
        out.append(f"baseline 欠帳走勢：{trend}")
    append_subagent_usage(out, data)
    if data["events"]:
        parts = []
        for run_id, info in data["events"]:
            if info is None:
                parts.append(f"{run_id}: 無記錄")
            else:
                span = f"{info['span_seconds']:.1f}s" if info["span_seconds"] is not None else "n/a"
                parts.append(f"{run_id}: {info['count']} 事件／時距 {span}／重入 {info['reentry']}")
        out.append(f"事件記錄：{'、'.join(parts)}")
    append_gate_hits(out, data)
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="run")
    args = parser.parse_args()
    if not os.path.isdir(args.dir):
        print(f"[stats] {args.dir}/ 不存在——不在 flow 專案根目錄，或尚無任何 run", file=sys.stderr)
        sys.exit(1)
    print(report(collect(args.dir)))


if __name__ == "__main__":
    main()
