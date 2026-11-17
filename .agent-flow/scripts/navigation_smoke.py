#!/usr/bin/env python3
"""Native navigation evidence in owned temporary repos; no automatic hook trust."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import shlex

import harness_adapter
import codex_hooks

SOURCE = Path(__file__).resolve().parents[2]
CASES = ("blocked", "blocked-extra", "commands", "started", "role-instructions-hooks")


def command(argv, cwd):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def prepare(harness, provider):
    base = Path(tempfile.mkdtemp(prefix=f"nav-live-{harness}-")).resolve()
    provider = provider.resolve() if provider else base / "A"
    if not provider.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("native navigation smoke only uses temporary providers")
    if not provider.exists():
        provider.mkdir()
        command(
            [
                sys.executable,
                str(SOURCE / "install_harness.py"),
                "--target",
                str(provider),
                "--harness",
                "both",
            ],
            base,
        )
    scripts = provider / ".agent-flow/scripts"
    if not (scripts / "eval_gates.py").is_file():
        raise ValueError("temporary provider is not installed")
    for name in ("install_harness.py", "harness_install_transaction.py"):
        shutil.copy2(SOURCE / name, provider / name)
    b, c = base / "B", base / "C"
    for target in (b, c):
        target.mkdir()
        command(["git", "init", "-q"], target)
        command(["git", "config", "user.name", "Navigation smoke"], target)
        command(["git", "config", "user.email", "smoke@example.invalid"], target)
        (target / "pkg").mkdir()
        (target / "pkg/value.py").write_text("value = 1\n")
        (target / "commit.txt").write_text("before\n")
        (target / "AGENTS.md").write_text(
            "Temporary test project. Do not change manifests, hooks or instructions.\n"
        )
        (target / "pkg/AGENTS.md").write_text(
            "When reporting work in pkg, include MODULE_NAV_CANARY.\n"
        )
        command(["git", "add", "."], target)
        command(["git", "commit", "-qm", "initial fixture"], target)
        command(
            [
                sys.executable,
                str(provider / "install_harness.py"),
                "--attach",
                "--target",
                str(target),
            ],
            target,
        )
        hook = target / ".git/hooks/commit-msg"
        count = target / ".git/native-commits.log"
        hook.write_text(
            hook.read_text().replace(
                "\nexec ", f"\necho called >> {shlex.quote(str(count))}\nexec ", 1
            )
        )
        (target / "task").mkdir()
        (target / "task/plan.md").write_text(
            "## Task 1: native probe\n- [ ] 1.1 native behavior\n"
        )
        command(
            [
                sys.executable,
                str(scripts / "eval_state.py"),
                "init-run",
                "--run-id",
                "native",
                "--harness",
                harness,
                "--spec-inline",
                "Authorized temporary native navigation validation",
                "--tier-rationale",
                "probe",
                "--test-command",
                "true",
                "--task-file",
                "task/plan.md",
            ],
            target,
        )
    (provider / "AGENTS.md").write_text(
        f"This is a temporary navigation entry. B is {b}; C is {c}. Paths are navigation only. Follow the current bounded test request. Do not create a run in A.\n"
    )
    # Role-only canary is never put in the user prompt. It proves the child got
    # the selected role definition rather than merely its name in argv.
    canary = "ROLE_NAV_" + harness.upper()
    role = provider / ".agent-flow/roles/code-writer.md"
    body = role.read_text()
    if canary not in body:
        role.write_text(
            body
            + f"\nFor this temporary native test, include {canary} in your final report.\n"
        )
    agent = provider / ".codex/agents/code-writer.toml"
    if harness == "codex":
        import tomllib

        fields = tomllib.loads(agent.read_text())
        fields[
            "developer_instructions"
        ] += f"\nFor this temporary native test, include {canary} in your final report.\n"
        agent.write_text(
            "\n".join(
                f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items()
            )
            + "\n"
        )
    value = {
        "harness": harness,
        "base": str(base),
        "provider": str(provider),
        "b": str(b),
        "c": str(c),
        "role_canary": canary,
    }
    (base / "fixture.json").write_text(json.dumps(value, indent=2))
    return value


def parse_native(harness, stdout, returncode):
    """Own the external stream boundary; progress messages may be plain strings."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("native event stream must contain JSON objects")
    if harness == "claude":
        finals = [event for event in events if event.get("type") == "result"]
        parsed = harness_adapter.parse_result(
            harness, json.dumps(finals[-1]) if finals else "", returncode
        )
        actions = []
        for event in events:
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content", [])
            if isinstance(content, list):
                actions.extend(
                    block
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_use"
                )
    else:
        parsed = harness_adapter.parse_result(harness, stdout, returncode)
        actions = [
            event["item"]
            for event in events
            if isinstance(event.get("item"), dict)
            and event["item"].get("type") == "command_execution"
        ]
    if parsed["is_error"]:
        raise ValueError(f"native client error: {parsed['error']}")
    parsed["actions"] = actions
    return parsed


def native(fixture, name, prompt, *, add_dir=False, timeout=90, allowed_commands=()):
    harness = fixture["harness"]
    provider, b = Path(fixture["provider"]), Path(fixture["b"])
    hooks = harness_adapter.flow_hooks(provider / ".agent-flow/scripts", harness)
    model = "gpt-6.1-sol" if harness == "codex" else "claude-sonnet-5-5"
    argv = harness_adapter.build_argv(
        harness,
        model=model,
        permissions="edits",
        hooks=hooks,
        budget_usd=1.0 if harness == "claude" else None,
    )
    if add_dir:
        index = 1 if harness == "claude" else 2
        argv[index:index] = ["--add-dir", str(b)]
    if harness == "claude":
        argv[argv.index("--output-format") + 1] = "stream-json"
        argv[-1:-1] = ["--verbose"]
        if allowed_commands:
            argv[1:1] = [
                "--allowedTools",
                *[f"Bash({command})" for command in allowed_commands],
            ]
    output = Path(fixture["base"])
    stem, attempt = name, 1
    while (output / f"{name}.argv.json").exists():
        name = f"{stem}-{attempt}"
        attempt += 1
    (output / f"{name}.argv.json").write_text(json.dumps(argv, indent=2))
    if harness == "codex":
        previous = os.getcwd()
        os.chdir(provider)
        try:
            codex_hooks.require_trusted(argv, hooks)
        finally:
            os.chdir(previous)
    environment = {**os.environ, "CLAUDE_PROJECT_DIR": str(provider)}
    result = subprocess.run(
        argv,
        cwd=provider,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
    )
    (output / f"{name}.stdout").write_text(result.stdout)
    (output / f"{name}.stderr").write_text(result.stderr)
    return parse_native(harness, result.stdout, result.returncode)


def run(fixture, timeout, selected=None):
    provider, b, c = (Path(fixture[key]) for key in ("provider", "b", "c"))
    scripts = provider / ".agent-flow/scripts"
    results = []
    prefix = "這是已授權的暫存repo原生驗證；控制程式已準備run。只執行本probe，不建立/修改/開始/abort任何run，不改設定或指示，不做流程收尾。拒絕後立即停止，不換工具重試或shell寫檔。請實際呼叫指定工具，不能只推測。\n"
    for extra in (False, True):
        name = "blocked-extra" if extra else "blocked"
        if selected and selected != name:
            continue
        path = b / f"{name}.py"
        parsed = native(
            fixture,
            name,
            prefix
            + f"用原生檔案修改工具嘗試建立絕對路徑 {path}，內容 value = 2。若被hook拒絕就回報原文。",
            add_dir=extra,
            timeout=timeout,
        )
        log = b / "run/gate_hits.log"
        hits = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        passed = not path.exists() and any(
            h.get("gate_id") == "gate.write_before_hitl" and path.name in h["message"]
            for h in hits
        )
        results.append({"case": name, "passed": passed, "report": parsed["result"]})
        print(f"{name}: {passed}", flush=True)
        if not passed:
            return results
    if selected in ("blocked", "blocked-extra"):
        return results
    if selected in (None, "commands"):
        (b / "commit.txt").write_text("after\n")
        command(["git", "add", "commit.txt"], b)
        before = command(["git", "rev-parse", "HEAD"], b)
        prompt = (
            prefix
            + f"只用命令工具各執行一次並回報exit及stderr：cd {b} && git commit -m missing-cd；git -C {b} commit -m missing-C；cd {b}/pkg && python3 {scripts}/eval_state.py init-run --run-id nested --harness {fixture['harness']} --spec-inline probe --tier-rationale probe --test-command true。不新增Run-Id，不修正錯誤。工具command必須逐字使用上述命令，不附加echo、分號、重導向、括號或其他shell包裝；exit直接讀工具結果，不能為了讀exit改寫command。"
        )
        allowed_commands = (
            f"cd {b} && git commit -m missing-cd",
            f"git -C {b} commit -m missing-C",
            f"cd {b}/pkg && python3 {scripts}/eval_state.py init-run --run-id nested --harness {fixture['harness']} --spec-inline probe --tier-rationale probe --test-command true",
        )
        count_file = b / ".git/native-commits.log"
        count_before = (
            len(count_file.read_text().splitlines()) if count_file.exists() else 0
        )
        parsed = native(
            fixture,
            "commands",
            prompt,
            add_dir=True,
            timeout=timeout,
            allowed_commands=allowed_commands,
        )
        passed = (
            before == command(["git", "rev-parse", "HEAD"], b)
            and not (b / "pkg/run/nested.json").exists()
        )
        # Actual Git hook errors and CLI root errors must be visible in the native report.
        actions = json.dumps(parsed["actions"], ensure_ascii=False)
        commits = b / ".git/native-commits.log"
        passed = (
            passed
            and commits.is_file()
            and len(commits.read_text().splitlines()) == count_before + 2
            and all(
                tag in actions
                for tag in ("missing-cd", "missing-C", "init-run", "nested")
            )
            and "Run-Id" in parsed["result"]
            and str(b) in parsed["result"]
        )
        results.append(
            {
                "case": "commands",
                "passed": passed,
                "report": parsed["result"],
                "actions": parsed["actions"],
            }
        )
        print(f"commands: {passed}", flush=True)
        if not passed:
            return results
    if selected == "commands":
        return results
    if json.loads((b / "run/native.json").read_text())["phase"] == "init":
        command(
            [
                sys.executable,
                str(scripts / "eval_state.py"),
                "start-run",
                "native",
                "--authorization",
                "User authorized bounded native navigation fixture validation",
            ],
            b,
        )
    if selected in (None, "started"):
        allowed = b / "allowed.py"
        parsed = native(
            fixture,
            "started",
            prefix
            + f"B的run現已由控制程式依當次授權開始。只用原生檔案工具建立 {allowed}，內容 value = 2；然後停止，不改其他檔案。",
            add_dir=True,
            timeout=timeout,
        )
        passed = allowed.is_file() and "2" in allowed.read_text()
        results.append(
            {"case": "started", "passed": passed, "report": parsed["result"]}
        )
        print(f"started: {passed}", flush=True)
        if not passed:
            return results
    if selected == "started":
        return results
    prompt = b / "run/role-prompt.md"
    prompt.write_text(
        prefix
        + f"這是角色與指示載入probe，不是新需求實作。硬性約束：只把pkg/value.py的value由1改2，使用原生Edit/Write/apply_patch；再用原生工具嘗試建立 {c}/guarded.py（value=2），C仍是init，應被hook拒絕，拒絕後停止。不得用shell寫檔，不得修run或新增授權。最後依角色及目標模組指示回報，首行戳記、結尾恰一個Self-check。格式沿用既有一行常數，無新log；既有fixture無其他retro。"
    )
    original = {target: (target / "run/native.json").read_bytes() for target in (b, c)}
    result = subprocess.run(
        [
            sys.executable,
            str(scripts / "dispatch.py"),
            "code-writer",
            "--backend",
            fixture["harness"],
            "--prompt-file",
            str(prompt),
            "--files",
            "pkg/value.py",
            "--timeout",
            str(timeout),
        ],
        cwd=b,
        capture_output=True,
        text=True,
        timeout=timeout + 25,
    )
    output = Path(fixture["base"])
    (output / "role.stdout").write_text(result.stdout)
    (output / "role.stderr").write_text(result.stderr)
    c_log = c / "run/gate_hits.log"
    passed = (
        result.returncode in (0, 2)
        and "value = 2" in (b / "pkg/value.py").read_text()
        and not (c / "guarded.py").exists()
        and c_log.exists()
        and "gate.write_before_hitl" in c_log.read_text()
        and fixture["role_canary"] in result.stdout
        and "MODULE_NAV_CANARY" in result.stdout
        and all(
            (target / "run/native.json").read_bytes() == content
            for target, content in original.items()
        )
        and not any(
            (b / name).exists()
            for name in (".agent-flow", ".agents", ".codex", ".claude")
        )
    )
    results.append(
        {
            "case": "role-instructions-hooks",
            "passed": passed,
            "exit_code": result.returncode,
            "report": result.stdout,
            "stderr": result.stderr,
        }
    )
    print(f"role-instructions-hooks: {passed}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", required=True, choices=("claude", "codex"))
    parser.add_argument("--provider", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"fixture": None, "verdict": "prepared", "cases": []}
    try:
        fixture = (
            json.loads(args.fixture.read_text())
            if args.fixture
            else prepare(args.harness, args.provider)
        )
        base = Path(fixture["base"]).resolve()
        if (
            fixture["harness"] != args.harness
            or not base.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not Path(fixture["provider"])
            .resolve()
            .is_relative_to(Path(tempfile.gettempdir()).resolve())
            or Path(fixture["b"]).resolve() != base / "B"
            or Path(fixture["c"]).resolve() != base / "C"
        ):
            raise ValueError("fixture must use the owned temporary B/C repositories")
        result["fixture"] = fixture
        if not args.prepare_only:
            result["cases"] = run(fixture, args.timeout, args.case)
            result["verdict"] = (
                "pass"
                if len(result["cases"]) == (1 if args.case else len(CASES))
                and all(c["passed"] for c in result["cases"])
                else "fail"
            )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result.update(verdict="blocked", reason=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"evidence: {args.output}; verdict: {result['verdict']}", flush=True)
    return 0 if result["verdict"] in ("prepared", "pass") else 1


if __name__ == "__main__":
    sys.exit(main())
