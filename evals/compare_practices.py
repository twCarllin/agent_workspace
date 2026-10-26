#!/usr/bin/env python3
"""Run the same evaluation case against two versions of PRACTICES.md."""

import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evals/results"
RUNNER = ROOT / ".agent-flow/scripts/skill_eval.py"
sys.path.insert(0, str(ROOT / ".agent-flow/scripts"))
from eval_provenance import collect


def load_runner():
    spec = importlib.util.spec_from_file_location("skill_eval", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def changed_lines(fixture, baseline):
    result = subprocess.run(
        ["git", "diff", "--numstat", baseline],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=True,
    )
    return sum(
        int(added) + int(removed)
        for added, removed, _ in (
            line.split("\t", 2) for line in result.stdout.splitlines()
        )
        if added.isdigit() and removed.isdigit()
    )


def set_practices(fixture, source):
    shutil.copyfile(source, fixture / ".agent-flow/PRACTICES.md")
    path = ".agent-flow/PRACTICES.md"
    difference = subprocess.run(
        ["git", "diff", "--quiet", "--", path],
        cwd=fixture,
        capture_output=True,
    )
    if difference.returncode == 0:
        return
    if difference.returncode != 1:
        raise RuntimeError("無法檢查 fixture 的指引差異")
    subprocess.run(
        ["git", "add", "--", path], cwd=fixture, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-q",
            "-m",
            "fixture comparison rule",
        ],
        cwd=fixture,
        check=True,
        capture_output=True,
    )


def run_one(runner, case, source, label, number, args):
    workdir = Path(tempfile.mkdtemp(prefix="practice-compare-"))
    record = {"variant": label, "run": number, "practices_sha256": sha256(source)}
    try:
        fixture = Path(runner.build_fixture(str(case), str(workdir), args.harness))
        set_practices(fixture, source)
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=fixture,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        started = time.monotonic()
        data, raw, note = runner.run_harness(
            args.harness,
            str(fixture),
            runner.read_prompt(str(case)),
            args.budget_usd if args.harness == "claude" else None,
            args.timeout,
            permissions=args.permissions,
            model=args.model,
        )
        record["duration_seconds"] = round(time.monotonic() - started, 2)
        record["changed_lines"] = changed_lines(fixture, baseline)
        record["cost_usd"] = data.get("total_cost_usd") if data else None
        record["turns"] = data.get("num_turns") if data else None
        record["agent_result"] = data.get("result", "")[-2000:] if data else ""
        if data is None or note:
            record["verdict"] = "error"
            record["note"] = note
        else:
            result_path = workdir / "result.json"
            result_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            verdict, output = runner.run_check(
                str(case), str(fixture), str(result_path)
            )
            record["verdict"] = verdict
            record["check_output"] = output.strip()
        if args.keep_fixture:
            record["fixture"] = str(fixture)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        record["verdict"] = "error"
        record["note"] = str(exc)
    finally:
        if not args.keep_fixture:
            shutil.rmtree(workdir, ignore_errors=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="reuse-existing", help="evals/ 下的案例名稱")
    parser.add_argument(
        "--baseline", type=Path, required=True, help="舊版 PRACTICES.md"
    )
    parser.add_argument("--runs", type=int, default=1, help="每版執行次數")
    parser.add_argument("--harness", choices=("claude", "codex"), default="codex")
    parser.add_argument("--model", help="預設使用專案模型設定")
    parser.add_argument(
        "--permissions", choices=("edits", "unrestricted"), default="edits"
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--budget-usd", type=float, default=3.0, help="Claude 單次預算上限"
    )
    parser.add_argument("--keep-fixture", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if (
        not args.baseline.is_file()
        or args.runs < 1
        or args.timeout < 1
        or args.budget_usd <= 0
    ):
        parser.error("baseline 須是檔案，runs／timeout／budget-usd 須大於零")
    candidate = ROOT / ".agent-flow/PRACTICES.md"
    if sha256(args.baseline) == sha256(candidate):
        parser.error("兩份指引內容相同，無法比較")
    runner = load_runner()
    case = runner.discover_cases(args.case)[0]
    args.model = args.model or runner.selected_model(args.harness)
    if args.dry_run:
        print(
            f"case={args.case} harness={args.harness} model={args.model} runs={args.runs}"
        )
        print(f"baseline={sha256(args.baseline)} candidate={sha256(candidate)}")
        return 0
    if shutil.which(args.harness) is None:
        parser.error(f"找不到 {args.harness} CLI")
    provenance = collect(case, RUNNER, args.harness, args.permissions, args.timeout)
    provenance["comparison_runner_sha256"] = sha256(__file__)
    records = []
    for number in range(1, args.runs + 1):
        variants = (("baseline", args.baseline), ("candidate", candidate))
        if number % 2 == 0:
            variants = tuple(reversed(variants))
        for label, source in variants:
            record = run_one(runner, case, source, label, number, args)
            records.append(record)
            print(
                f"{label} {number}: {record['verdict']} lines={record.get('changed_lines')} "
                f"seconds={record.get('duration_seconds')}",
                flush=True,
            )
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output = RESULTS / f"{stamp}-practice-compare.json"
    output.write_text(
        json.dumps(
            {
                "case": args.case,
                "harness": args.harness,
                "model": args.model,
                "provenance": provenance,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"results={output.relative_to(ROOT)}")
    return 0 if all(record["verdict"] == "pass" for record in records) else 1


if __name__ == "__main__":
    sys.exit(main())
