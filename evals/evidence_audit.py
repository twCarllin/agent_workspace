#!/usr/bin/env python3
"""Audit paired skill evaluations, reproduction data, and blocked handoffs."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PROVENANCE = (
    "source_commit",
    "source_changes_sha256",
    "case_files_sha256",
    "runner_sha256",
    "python_version",
    "cli_version",
    "permissions",
    "timeout_seconds",
)
HANDOFF_HEADINGS = (
    "重現步驟",
    "目前的根因假設",
    "失敗嘗試與結果",
    "證據位置",
    "使用者裁決",
)


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def provenance_gaps(data):
    provenance = data.get("provenance") if isinstance(data, dict) else None
    if not isinstance(provenance, dict):
        return list(REQUIRED_PROVENANCE)
    gaps = [key for key in REQUIRED_PROVENANCE if not provenance.get(key)]
    if provenance.get("source_clean") is not True:
        gaps.append("source_clean")
    return gaps


def assess_comparison(data):
    """Only completed, matched pairs can support a quality/cost comparison."""
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        return {"status": "insufficient", "reason": "缺成對執行記錄"}
    groups = {}
    for record in records:
        if not isinstance(record, dict):
            return {"status": "insufficient", "reason": "記錄格式錯誤"}
        key = record.get("run")
        variant = record.get("variant")
        if not isinstance(key, int) or variant not in ("baseline", "candidate"):
            return {"status": "insufficient", "reason": "缺輪次或版本"}
        group = groups.setdefault(key, {})
        if variant in group:
            return {"status": "insufficient", "reason": "同輪次版本重複"}
        group[variant] = record
    pairs = []
    for number, group in sorted(groups.items()):
        if set(group) != {"baseline", "candidate"}:
            return {"status": "insufficient", "reason": f"第 {number} 輪缺配對"}
        old, new = group["baseline"], group["candidate"]
        if old.get("verdict") not in ("pass", "fail") or new.get("verdict") not in (
            "pass",
            "fail",
        ):
            return {
                "status": "insufficient",
                "reason": f"第 {number} 輪有工具或檢查器錯誤",
            }
        for item in (old, new):
            value = item.get("duration_seconds")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                return {"status": "insufficient", "reason": f"第 {number} 輪缺有效時間"}
        pairs.append((old, new))
    baseline_pass = sum(old["verdict"] == "pass" for old, _ in pairs)
    candidate_pass = sum(new["verdict"] == "pass" for _, new in pairs)
    baseline_seconds = sum(old["duration_seconds"] for old, _ in pairs)
    candidate_seconds = sum(new["duration_seconds"] for _, new in pairs)
    return {
        "status": "comparable",
        "pairs": len(pairs),
        "baseline_pass": baseline_pass,
        "candidate_pass": candidate_pass,
        "baseline_seconds": round(baseline_seconds, 2),
        "candidate_seconds": round(candidate_seconds, 2),
        "quality_delta": candidate_pass - baseline_pass,
        "seconds_delta": round(candidate_seconds - baseline_seconds, 2),
        "cost_status": (
            "unknown"
            if any(
                old.get("cost_usd") is None or new.get("cost_usd") is None
                for old, new in pairs
            )
            else "recorded"
        ),
    }


def assess_handoff(path):
    text = Path(path).read_text(encoding="utf-8")
    missing = []
    for heading in HANDOFF_HEADINGS:
        marker = f"## {heading}"
        if marker not in text:
            missing.append(heading)
            continue
        body = text.split(marker, 1)[1].split("\n## ", 1)[0].strip()
        if not body:
            missing.append(heading)
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "evals/results")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "run")
    args = parser.parse_args()
    paths = sorted(args.results_dir.glob("*-practice-compare.json"))
    print(f"成對比較：{len(paths)} 份")
    for path in paths:
        data = read_json(path)
        result = assess_comparison(data)
        gaps = provenance_gaps(data)
        print(
            f"{path.name}: {json.dumps(result, ensure_ascii=False)}；重現缺項={','.join(gaps) or '無'}"
        )
    skill_paths = [p for p in sorted(args.results_dir.glob("*.json")) if p not in paths]
    print(f"其他評測：{len(skill_paths)} 份")
    for path in skill_paths:
        data = read_json(path)
        if data is None or "records" not in data:
            continue
        gaps = provenance_gaps(data)
        print(f"{path.name}: 重現缺項={','.join(gaps) or '無'}")
    handoffs = sorted(args.run_dir.glob("*-blocked.md"))
    print(f"真實卡點報告：{len(handoffs)} 份")
    for path in handoffs:
        print(f"{path.name}: 缺項={','.join(assess_handoff(path)) or '無'}")
    if not handoffs:
        print("卡點交接：無真實報告可驗；目前只能驗證格式與未來產出的資料。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
