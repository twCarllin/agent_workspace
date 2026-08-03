#!/usr/bin/env python3
"""Flow 遙測彙總：掃 run/ 的冷溯源檔，輸出系統健康指標。

用法：
  python3 .claude/hooks/stats.py [--dir run]

指標與其回答的問題：
  tier 分佈        分級有沒有發揮省成本作用（Tier 1 幾乎為零 → 門檻太緊）
  waive 率         驗證豁免有沒有變質為常態後門
  HITL 打回率      人閘門是真防線還是蓋章（趨近 0% → 候選降級為通知）
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

資料來源：run/*.json（manifest）、run/*.eval.json、run/*.test_baseline.json、
run/gate_hits.log。欄位缺漏時顯示 n/a 並註明需要什麼資料，不猜。
"""
import argparse
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


def collect(run_dir="run"):
    data = {
        "runs": [], "tiers": Counter(), "statuses": Counter(),
        "waived": 0, "hitl_confirmed": 0, "hitl_rejections": 0,
        "sub_tasks": 0, "rework": 0,
        "scores": [], "dim_counter": Counter(), "has_legacy_dims": False,
        "baseline": [],  # (run_id, stable)
        "verif_runs": 0, "verif_cmds": 0,
        "gate_hits": Counter(), "gate_hit_lines": [],
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
    out.append(f"waive 率：{pct(data['waived'], n_runs)}")
    hitl_total = data["hitl_confirmed"] + data["hitl_rejections"]
    out.append(
        f"HITL 打回率：{pct(data['hitl_rejections'], hitl_total)}"
        + ("　⚠ 趨近 0% 的人閘門是蓋章，候選降級" if hitl_total and not data["hitl_rejections"] else "")
    )
    out.append(f"rework 率（首輪即有 🔴）：{pct(data['rework'], data['sub_tasks'])}")
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
