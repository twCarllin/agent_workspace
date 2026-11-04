#!/usr/bin/env python3
"""Check analysis against executable order flow and the recorded decision."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import Checker, load_result  # noqa: E402


def main(fixture):
    root = Path(fixture)
    checker = Checker()
    analysis = load_result(root / "analysis.json")
    if not isinstance(analysis, dict):
        checker.check("分析資料存在且可解析", False)
        return checker.finish()
    process = subprocess.run(
        [sys.executable, "app.py"], cwd=root, capture_output=True, text=True, timeout=20
    )
    history = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=root, capture_output=True, text=True
    )
    valid_process = subprocess.run(
        [sys.executable, "valid_pricing.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if (
        process.returncode != 0
        or history.returncode != 0
        or valid_process.returncode != 0
    ):
        checker.check("執行及歷史證據可用", False, process.stderr or history.stderr)
        return checker.finish()
    actual = json.loads(process.stdout)
    required = {
        "understanding": {"app.py", "pricing.py"},
        "cause": {"pricing.py", "valid_pricing.py", "git:HEAD"},
        "design": {"pricing.py", "app.py"},
        "impact": {"app.py", "receipt.py", "ledger.py"},
    }
    evidence = analysis.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    for ability, paths in required.items():
        references = evidence.get(ability)
        valid = isinstance(references, list) and all(
            isinstance(ref, str) and (ref == "git:HEAD" or (root / ref).is_file())
            for ref in references
        )
        checker.check(
            f"{ability} 證據完整",
            valid and paths.issubset(references),
            f"需要 {sorted(paths)}",
        )
    checker.check(
        "理解實際資料流",
        analysis.get("understanding")
        == {name: actual[name]["net"] for name in ("standard", "discount")},
    )
    cause = analysis.get("cause")
    checker.check(
        "原因與歷史前提",
        isinstance(cause, dict)
        and history.stdout.strip() == "Apply discount before tax for every order"
        and cause.get("operation_order") == ["discount", "tax"]
        and cause.get("actual") == actual["discount"]["net"]
        and cause.get("expected") == 880
        and cause.get("premise_valid") is False,
    )
    valid_actual = json.loads(valid_process.stdout)["discount"]
    checker.check(
        "仍有效的歷史前提",
        analysis.get("valid_cause")
        == {"actual": valid_actual, "expected": 880, "premise_valid": True}
        and valid_actual == 880,
    )
    checker.check(
        "設計契約及候選結果",
        analysis.get("design")
        == {
            "before_tax": {"standard": 1100, "discount": 880},
            "after_tax": {"standard": 1100, "discount": 900},
            "choice": "before_tax",
        },
    )
    impact = analysis.get("impact")
    checker.check(
        "影響與實際消費結果",
        isinstance(impact, dict)
        and sorted(impact.get("consumers", [])) == ["ledger.py", "receipt.py"]
        and impact.get("outputs")
        == {
            "receipt.py": actual["discount"]["receipt"],
            "ledger.py": actual["discount"]["ledger"],
        },
    )
    return checker.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check.py <fixture_dir> <result_json>")
    raise SystemExit(main(sys.argv[1]))
