#!/usr/bin/env python3
"""Verify cross-process behavior, counterexamples, and historical rationale."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import Checker, load_result  # noqa: E402


def main(fixture):
    root = Path(fixture)
    checker = Checker()
    report = load_result(root / "verification.json")
    if not isinstance(report, dict):
        checker.check("驗證資料存在且可解析", False)
        return checker.finish()
    original = subprocess.run(
        ["git", "show", "HEAD:consumer.py"], cwd=root, capture_output=True, text=True
    )
    producer = subprocess.run(
        ["git", "diff", "HEAD", "--", "producer.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    history = {}
    for revision, path in (
        ("HEAD^", "producer.py"),
        ("HEAD^", "consumer.py"),
        ("HEAD", "producer.py"),
        ("HEAD", "valid_consumer.py"),
    ):
        history[(revision, path)] = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
        )
    if (
        original.returncode
        or producer.returncode
        or any(result.returncode for result in history.values())
    ):
        checker.check("歷史及原始程式可用", False)
        return checker.finish()
    actual = {}
    counterexamples = {}
    valid_output = None
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "consumer.py"
        old.write_text(original.stdout)
        for amount in (125, 0):
            data = Path(tmp) / f"order-{amount}.json"
            produced = subprocess.run(
                [sys.executable, str(root / "producer.py"), str(data), str(amount)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            current = subprocess.run(
                [sys.executable, str(root / "consumer.py"), str(data)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            previous = subprocess.run(
                [sys.executable, str(old), str(data)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if amount == 125:
                valid = subprocess.run(
                    [sys.executable, str(root / "valid_consumer.py"), str(data)],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                if valid.returncode == 0:
                    valid_output = valid.stdout.strip()
            actual[str(amount)] = current.stdout.strip()
            counterexamples[str(amount)] = previous.returncode
            checker.check(
                f"{amount} 跨程序輸出正確",
                produced.returncode == 0
                and current.returncode == 0
                and current.stdout.strip() == str(amount),
                current.stderr or produced.stderr,
            )
    checker.check("producer 未修改", producer.stdout == "")
    checker.check("實作證據對應實際輸出", report.get("implementation") == actual)
    checker.check(
        "對抗案例重現舊消費端失敗",
        report.get("adversarial") == counterexamples
        and all(code != 0 for code in counterexamples.values()),
    )
    correction = report.get("correction")
    checker.check(
        "歷史理由及結構約束",
        '"total":' in history[("HEAD^", "producer.py")].stdout
        and '["total"]' in history[("HEAD^", "consumer.py")].stdout
        and '"total_cents":' in history[("HEAD", "producer.py")].stdout
        and isinstance(correction, dict)
        and correction.get("historical_fields")
        == {"producer": "total", "consumer": "total"}
        and correction.get("premise_valid") is False
        and correction.get("constraint") == "total_cents",
    )
    checker.check(
        "仍有效的歷史理由",
        valid_output == "125"
        and '["total_cents"]' in history[("HEAD", "valid_consumer.py")].stdout
        and report.get("valid_correction")
        == {"premise_valid": True, "constraint": "total_cents", "output": valid_output},
    )
    evidence = report.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    for ability in ("implementation", "adversarial", "correction"):
        required = (
            {"producer.py", "consumer.py"}
            if ability == "implementation"
            else {"producer.py", "git:HEAD"}
        )
        if ability == "correction":
            required = {"git:HEAD", "valid_consumer.py"}
        refs = evidence.get(ability)
        valid = isinstance(refs, list) and all(
            isinstance(ref, str) and (ref == "git:HEAD" or (root / ref).is_file())
            for ref in refs
        )
        checker.check(f"{ability} 證據完整", valid and required.issubset(refs))
    return checker.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check.py <fixture_dir> <result_json>")
    raise SystemExit(main(sys.argv[1]))
