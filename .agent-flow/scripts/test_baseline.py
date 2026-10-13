#!/usr/bin/env python3
"""test-strategy skill 的執行端：測試 baseline 建立與「新增失敗」判定。

用法：
  python3 .agent-flow/scripts/test_baseline.py baseline [--cmd "pytest -q"] [--run-id ID] [--fresh]
  python3 .agent-flow/scripts/test_baseline.py check    [--cmd "pytest -q"] [--strike-key sub_task_1] [--run-id ID]
  python3 .agent-flow/scripts/test_baseline.py related  --files src/a.py src/b.py
  python3 .agent-flow/scripts/test_baseline.py mine     [--cmd "pytest -q"] [--strike-key sub_task_1] [--run-id ID]  # 只跑本次未提交變更範圍內的測試檔

--cmd 省略時讀 run/<run_id>.json（manifest）的 test_command 欄位——全套指令的
single source of truth，保證 baseline 與 check 的範圍一致。

baseline：只在有 HEAD 且產品輸入乾淨時建立來源可信基準；可辨失敗重跑確認。
          schema 2 記錄來源、環境、命令、兩次結果與 stable_failures 交集。
          不可信舊檔不沿用；修改後只能沿用同來源的可信檔，不能補造。
check：   驗證可信來源與環境後比對，保留 --cmd 相關測試範圍；執行錯誤與逾時永不扣除。
          新的可辨失敗重跑確認，真新失敗 exit 2 並寫 failure_log。
related： 由變更檔案清單找出相關測試檔（測試檔命名慣例 + grep 引用），輸出路徑清單。

run_id 未指定時讀 eval_state.json 的 run_id。
exit 0 = gate 通過；exit 2 = 新增穩定失敗或執行問題；exit 1 = 使用錯誤／不可信來源。
"""

import argparse
import glob
import hashlib
import json
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import time

# 常見框架可辨測試 ID；無法解析的 suite sentinel 只表示執行問題。
FAIL_PATTERNS = [
    re.compile(r"^(?:FAIL|ERROR): (\S+) \(([^\n]+)\)$", re.M),
    re.compile(r"^FAILED (?!\()(\S+)", re.M),  # pytest
    re.compile(r"^ERROR (\S+)", re.M),  # pytest（collection error）
    re.compile(r"^--- FAIL: (\S+)", re.M),  # go test
    re.compile(r"^FAIL (?!\()(\S+)", re.M),  # jest / vitest（檔案層級）
    re.compile(r"^\s*[✕×✗] (.+?)(?: \(\d+ ?m?s\))?$", re.M),  # jest / vitest / mocha
]

TEST_FILE_RE = re.compile(
    r"(^test_.*|.*_test\.\w+$|.*\.test\.\w+$|.*\.spec\.\w+$|.*Tests?\.\w+$)"
)
TEST_DIR_NAMES = {
    "test",
    "tests",
    "__tests__",
}  # 不含 "spec"——與 eval-flow 自產的 spec/ 產出物目錄衝突
TEST_CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}


def fail(msg, code=1):
    print(f"[test-gate] {msg}", file=sys.stderr)
    sys.exit(code)


DEFAULT_TIMEOUT = 300
BASELINE_SCHEMA = 2


def _parse_fails(out, returncode):
    fails = set()
    for pat in FAIL_PATTERNS:
        for match in pat.findall(out):
            if isinstance(match, tuple):
                name, owner = match
                fails.add(owner if owner.endswith("." + name) else f"{owner}.{name}")
            else:
                fails.add(match.strip())
    if returncode != 0 and not fails:
        fails.add("__suite__")
    return fails


def _execute(command, *, shell, timeout):
    """有界執行；新 session 只包含本次測試程序，逾時清理整個程序群組。"""
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "failures": [],
            "returncode": None,
            "classification": "execution_error",
            "stdout": "",
            "stderr": str(exc),
            "duration_seconds": 0,
        }
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # 子程序可能持有 pipe，即使 shell 已退出仍須清理本 session。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # 父程序已退出時，部分平台以 EPERM 表示原群組不可操作。
            pass
        try:
            stdout, stderr = process.communicate(timeout=0.25)
        except subprocess.TimeoutExpired as exc:
            # 逃離本群組的後代可能仍持有 pipe；只保留已取得輸出，不能等 EOF。
            stdout = (exc.output or b"").decode(errors="replace")
            stderr = (exc.stderr or b"").decode(errors="replace")
            process.stdout.close()
            process.stderr.close()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                # 不擴大搜尋或終止其他群組；即使 wait 未完成也以 timeout 交付。
                pass
    rc = process.returncode
    fails = _parse_fails(stdout + "\n" + stderr, rc)
    classification = (
        "timeout"
        if timed_out or rc == 124
        else (
            "execution_error"
            if rc not in (0, 1) or "__suite__" in fails
            else "test_failure" if fails else "success"
        )
    )
    return {
        "failures": sorted(fails - {"__suite__"}),
        "returncode": rc,
        "classification": classification,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": round(time.monotonic() - start, 3),
    }


def run_tests(cmd, timeout=DEFAULT_TIMEOUT):
    return _execute(cmd, shell=True, timeout=timeout)


def run_tests_argv(argv, timeout=DEFAULT_TIMEOUT):
    return _execute(argv, shell=False, timeout=timeout)


def _execution_problem(result):
    return result["classification"] in {"timeout", "execution_error"}


def environment_fingerprint():
    # 僅存雜湊，不保存環境值或秘密；排除 shell 自身的易變欄位。
    environment = {
        k: v for k, v in os.environ.items() if k not in {"_", "SHLVL", "PWD", "OLDPWD"}
    }
    environment.update(
        python=sys.executable,
        python_version=sys.version,
        platform=platform.platform(),
        cwd=os.path.realpath("."),
    )
    return hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()


def _flow_artifact(path):
    # 只豁免明確流程產物；不豁免 BUGLOG、RETRO、測試或產品設定。
    return (
        path == "eval_state.json"
        or (path.startswith("run/") and path.endswith((".json", ".jsonl", ".log")))
        or (path.startswith(("task/", "spec/")) and path.endswith(".md"))
    )


def source_snapshot():
    head = git_head()
    if not head:
        fail("無 HEAD：不能建立可信 baseline；先保留現場並確認修改前版本")
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        fail("無法檢查 Git 輸入：不能建立可信 baseline")
    records = status.split(b"\0")
    dirty = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        paths = [os.fsdecode(record[3:])]
        if b"R" in record[:2] or b"C" in record[:2]:
            if index >= len(records) or not records[index]:
                fail("Git status rename 記錄不完整")
            paths.append(os.fsdecode(records[index]))
            index += 1
        dirty.extend(path for path in paths if not _flow_artifact(path))
    if dirty:
        fail(
            "產品輸入已有修改，拒絕補建 baseline："
            + repr(sorted(dirty))
            + "；保留現場，使用乾淨起始版本另行取證比較，或直接驗證零失敗"
        )
    return {"head_sha": head, "clean_product_inputs": True}


def _trusted_baseline(data, cmd, environment, timeout):
    if not isinstance(data, dict) or data.get("schema") != BASELINE_SCHEMA:
        return False
    source = data.get("source")
    stable = data.get("stable_failures")
    observations = data.get("observations")
    if (
        not isinstance(source, dict)
        or source.get("clean_product_inputs") is not True
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(source.get("head_sha", "")))
        or source.get("head_sha") != data.get("head_sha")
        or data.get("source_after") != source
        or data.get("cmd") != cmd
        or data.get("environment") != environment
        or data.get("timeout_seconds") != timeout
        or not isinstance(stable, list)
        or not all(
            isinstance(test, str) and test and not test.startswith("__")
            for test in stable
        )
        or not isinstance(observations, list)
        or len(observations) not in (1, 2)
    ):
        return False
    for result in observations:
        if (
            not isinstance(result, dict)
            or result.get("classification") not in {"success", "test_failure"}
            or not isinstance(result.get("failures"), list)
            or not all(
                isinstance(test, str) and test and not test.startswith("__")
                for test in result["failures"]
            )
            or (
                result.get("classification") == "success"
                and (result.get("returncode") != 0 or result["failures"])
            )
            or (
                result.get("classification") == "test_failure"
                and (result.get("returncode") != 1 or not result["failures"])
            )
        ):
            return False
    if observations[0]["failures"] and len(observations) != 2:
        return False
    confirmed = set(observations[0]["failures"])
    if len(observations) == 2:
        confirmed &= set(observations[1]["failures"])
    return set(stable) == confirmed


def resolve_run_id(args):
    if args.run_id:
        return args.run_id
    try:
        with open("eval_state.json", encoding="utf-8") as f:
            run_id = json.load(f).get("run_id")
    except (OSError, json.JSONDecodeError):
        run_id = None
    if not run_id:
        fail("無法定位 run_id：eval_state.json 不存在或缺 run_id，請用 --run-id 指定")
    return run_id


def baseline_path(run_id):
    return f"run/{run_id}.test_baseline.json"


def resolve_cmd(args, run_id):
    if args.cmd:
        return args.cmd
    manifest = f"run/{run_id}.json"
    try:
        with open(manifest, encoding="utf-8") as f:
            cmd = json.load(f).get("test_command")
    except (OSError, json.JSONDecodeError):
        cmd = None
    if not cmd:
        fail(
            f"未指定 --cmd 且 {manifest} 無 test_command：請先把全套測試指令寫入 manifest，或用 --cmd 指定"
        )
    return cmd


def git_head():
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return p.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None  # 非 git repo：不重用，照常全新建立


def find_reusable_baseline(run_id, cmd, head, environment, timeout):
    """只沿用同一進場版本與可信來源；不把舊單次快照升格。"""
    candidate = None
    for path in sorted(glob.glob("run/*.test_baseline.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            _trusted_baseline(data, cmd, environment, timeout)
            and data["head_sha"] == head
        ):
            candidate = data
    return candidate


def venv_mismatch(cmd, root="."):
    """偵測「專案有虛擬環境目錄、但 test_command 未使用它」的錯配。
    cwd（root）存在 .venv/bin（次選 venv/bin）且 cmd 字串未提及該目錄名 → 回傳目錄名；
    否則回傳 None。純偵測，不改任何執行環境（HITL 裁決：警示而非自動綁，2026-09-09）。"""
    for name in (".venv", "venv"):
        if os.path.isdir(os.path.join(root, name, "bin")):
            return None if name in cmd else name
    return None


def cmd_baseline(args):
    run_id = resolve_run_id(args)
    cmd = resolve_cmd(args, run_id)
    timeout = args.timeout
    environment = environment_fingerprint()
    head = git_head()
    if not args.fresh:
        previous = find_reusable_baseline(run_id, cmd, head, environment, timeout)
        if previous:
            data = dict(previous, run_id=run_id, reused_from=previous["run_id"])
            data.pop("failure_log", None)
            data.pop("check_observations", None)
            os.makedirs("run", exist_ok=True)
            _save(baseline_path(run_id), data)
            print(
                f"[test-gate] 沿用 {previous['run_id']} 的可信 baseline（來源、cmd、環境相同）"
            )
            return
    source = source_snapshot()
    observations = [run_tests(cmd, timeout)]
    if observations[0]["failures"] and not _execution_problem(observations[0]):
        print("[test-gate] 可辨失敗重跑一次，確認相同測試 ID…")
        if source_snapshot() != source:
            fail("測試期間來源漂移：不發布可信 baseline")
        observations.append(run_tests(cmd, timeout))
    # 必須在每輪測試後確認來源，避免測試本身改動產品輸入。
    source_after = source_snapshot()
    if source != source_after or environment != environment_fingerprint():
        fail("測試期間來源或環境漂移：不發布可信 baseline")
    problems = [result for result in observations if _execution_problem(result)]
    if problems:
        os.makedirs("run", exist_ok=True)
        evidence = f"run/{run_id}.baseline_execution.json"
        _save(
            evidence,
            {
                "run_id": run_id,
                "cmd": cmd,
                "source": source,
                "timeout_seconds": timeout,
                "observations": observations,
            },
        )
        fail(
            f"baseline {problems[0]['classification']}：不能記為穩定失敗；證據 {evidence}",
            2,
        )
    stable = set(observations[0]["failures"])
    if len(observations) == 2:
        stable &= set(observations[1]["failures"])
    data = {
        "schema": BASELINE_SCHEMA,
        "run_id": run_id,
        "cmd": cmd,
        "head_sha": head,
        "source": source,
        "source_after": source_after,
        "environment": environment,
        "timeout_seconds": timeout,
        "observations": observations,
        "stable_failures": sorted(stable),
    }
    os.makedirs("run", exist_ok=True)
    _save(baseline_path(run_id), data)
    print(
        f"[test-gate] baseline 已寫入 {baseline_path(run_id)}：stable(確認既有失敗) {len(stable)} 個"
    )
    if stable:
        print("[test-gate] 已確認既有失敗：" + ", ".join(sorted(stable)))
        mismatch = venv_mismatch(cmd)
        if mismatch:
            print(
                f"[test-gate] 警告：專案有 {mismatch}/bin 但 test_command 未使用它",
                file=sys.stderr,
            )


def cmd_check(args):
    run_id = resolve_run_id(args)
    path = baseline_path(run_id)
    if not os.path.exists(path):
        fail(f"{path} 不存在：須在第一次修改前先跑 baseline；現在不可補造")
    try:
        with open(path, encoding="utf-8") as f:
            base = json.load(f)
    except (OSError, json.JSONDecodeError):
        fail("baseline 無法讀取：拒絕扣除失敗")
    cmd = resolve_cmd(args, run_id)
    if not _trusted_baseline(
        base,
        base.get("cmd") if isinstance(base, dict) else None,
        environment_fingerprint(),
        args.timeout,
    ):
        fail(
            "baseline 不可信或命令／環境不匹配：拒絕扣除；保留現場，直接驗證零失敗或用乾淨起始版本建基準"
        )
    # commit 後仍可沿用起始基準，前提是來源是目前版本的祖先。
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base["head_sha"], "HEAD"],
        capture_output=True,
    )
    if ancestry.returncode != 0:
        fail("baseline 來源不是目前 HEAD 的祖先：拒絕扣除")
    known = set(base["stable_failures"])
    key = args.strike_key or "_default"
    observations = [run_tests(cmd, args.timeout)]
    new = set(observations[0]["failures"]) - known
    if new and not _execution_problem(observations[0]):
        print(f"[test-gate] 出現 {len(new)} 個非 baseline 的失敗，重跑一次確認可重現…")
        observations.append(run_tests(cmd, args.timeout))
    base.setdefault("check_observations", []).append(
        {"key": key, "cmd": cmd, "observations": observations}
    )
    _save(path, base)
    problems = [result for result in observations if _execution_problem(result)]
    if problems:
        fail(f"check {problems[0]['classification']}：執行問題不可扣除為既有失敗", 2)
    real = sorted(new & set(observations[-1]["failures"]))
    non_reproducible = sorted(new - set(observations[-1]["failures"]))
    if non_reproducible:
        print(f"[test-gate] 非確定性失敗，未阻擋：{', '.join(non_reproducible)}")
    if real:
        base.setdefault("failure_log", []).append({"key": key, "tests": real})
        _save(path, base)
        print(
            f"[test-gate] BLOCK: 真實新失敗 {len(real)} 個，停止自修，回報使用者裁決",
            file=sys.stderr,
        )
        for test in real:
            print(f"  - {test}", file=sys.stderr)
        sys.exit(2)
    ignored = set(observations[0]["failures"]) & known
    print(
        "[test-gate] PASS: 無新增穩定失敗"
        + (f"（{len(ignored)} 個 baseline 既有失敗已略過）" if ignored else "")
    )


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def git_changed_files():
    """以 git status --porcelain -z 取得所有未提交變更檔（staged＋unstaged＋untracked）。
    deleted 檔排除；rename 行（-z 下格式 XY new\\0old\\0）取 new；
    untracked 目錄（以 / 結尾）遞歸展開為子檔案。"""
    try:
        p = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    # -z 用 NUL 分隔記錄；split("\0") 最後一個元素為空字串，filter 掉
    records = p.stdout.split("\0")
    files = []
    i = 0
    while i < len(records):
        rec = records[i]
        if len(rec) < 3:
            i += 1
            continue
        xy = rec[:2]
        path = rec[3:]
        # deleted（D 在 index 或 worktree）：排除
        if "D" in xy:
            # rename/copy 的 old path 跟在下一個 NUL 段，跳過
            if xy[0] in ("R", "C"):
                i += 2
            else:
                i += 1
            continue
        # rename / copy：new path 已在本 rec（path），old path 在下一個 NUL 段，跳過
        if xy[0] in ("R", "C"):
            files.append(path)
            i += 2
            continue
        # untracked 目錄（?? dir/ 形式）：遞歸展開為子檔案
        if path.endswith("/") and os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fname in filenames:
                    files.append(os.path.join(dirpath, fname).replace("\\", "/"))
        else:
            files.append(path)
        i += 1
    return files


def is_test_file(path):
    """判定是否為測試檔（與 cmd_related 邏輯一致）。"""
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    if any(p in SKIP_DIRS for p in parts):
        return False
    # 以點開頭的目錄（.claude/hooks、.venv…）一律排除：Python module 路徑不可含
    # 這種段，build_mine_argv 轉出的 ".claude.hooks.test_baseline" 首段為空，
    # unittest 會以 ValueError: Empty module name 整個 suite 判失敗。
    # 觸發條件是「改到 .agent-flow/scripts/ 下名為 test_*.py 的 script」——本框架自己就有
    # test_baseline.py 與 test_lint.py 兩支，改它們時必中（2026-09-22 實測）。
    if any(p.startswith(".") and p not in (".", "..") for p in parts[:-1]):
        return False
    if os.path.splitext(name)[1] not in TEST_CODE_EXTS:
        return False  # 非測試語言副檔名（.md/.json fixture 等）不餵 runner
    in_test_dir = any(p in TEST_DIR_NAMES for p in parts[:-1])
    return bool(TEST_FILE_RE.match(name)) or in_test_dir


def build_mine_argv(cmd, files):
    """組合 mine 執行 argv list：unittest discover 型轉 module 路徑，其他直接附路徑。
    回傳 list，供 run_tests_argv 使用（不經 shell，避免檔名注入）。"""
    if cmd.startswith("python3 -m unittest"):
        # 丟棄 discover 及其後參數，改為直接指定 module
        modules = [f.replace("/", ".").removesuffix(".py") for f in files]
        return ["python3", "-m", "unittest", *modules]
    return [*shlex.split(cmd), *files]


def cmd_mine(args):
    run_id = resolve_run_id(args)
    changed = git_changed_files()
    test_files = [f for f in changed if is_test_file(f)]

    if not test_files:
        print("[test-gate] 本次變更無測試檔（測試建立與否由 DoD 決定）")
        return

    cmd = resolve_cmd(args, run_id)
    mine_argv = build_mine_argv(cmd, test_files)

    result = run_tests_argv(mine_argv, args.timeout)
    fails = set(result["failures"])
    rc = result["returncode"]

    if result["classification"] == "success" and rc == 0 and not fails:
        print(f"[test-gate] mine PASS: {len(test_files)} 個測試檔全部通過")
        return

    if _execution_problem(result):
        print(
            f"[test-gate] mine {result['classification']}: {result['stderr']}",
            file=sys.stderr,
        )
    print(f"[test-gate] mine BLOCK: {len(fails)} 個失敗：", file=sys.stderr)
    for t in sorted(fails):
        print(f"  - {t}", file=sys.stderr)
    sys.exit(2)


def cmd_related(args):
    stems = set()
    for f in args.files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem:
            stems.add(stem)
    related = set()
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name).lstrip("./")
            if not is_test_file(path):
                continue
            if any(s in name for s in stems):
                related.add(path)
                continue
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            if any(re.search(rf"\b{re.escape(s)}\b", content) for s in stems):
                related.add(path)
    for path in sorted(related):
        print(path)
    if not related:
        print(
            "[test-gate] 找不到相關測試檔（可能是新行為尚無測試，或對映不到慣例）；"
            "Tier 2 新行為必須有測試 item，請確認",
            file=sys.stderr,
        )


def _positive_timeout(value):
    seconds = float(value)
    if not 0 < seconds <= 86400:
        raise argparse.ArgumentTypeError("timeout 須介於 0 與 86400 秒")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_base = sub.add_parser("baseline")
    p_base.add_argument("--cmd")
    p_base.add_argument("--run-id")
    p_base.add_argument("--fresh", action="store_true")
    p_base.set_defaults(func=cmd_baseline)

    p_check = sub.add_parser("check")
    p_check.add_argument("--cmd")
    p_check.add_argument("--strike-key")
    p_check.add_argument("--run-id")
    p_check.set_defaults(func=cmd_check)

    p_rel = sub.add_parser("related")
    p_rel.add_argument("--files", nargs="+", required=True)
    p_rel.set_defaults(func=cmd_related)

    p_mine = sub.add_parser("mine")
    p_mine.add_argument("--cmd")
    p_mine.add_argument("--strike-key")
    p_mine.add_argument("--run-id")
    p_mine.set_defaults(func=cmd_mine)

    for execution_parser in (p_base, p_check, p_mine):
        execution_parser.add_argument(
            "--timeout",
            type=_positive_timeout,
            default=DEFAULT_TIMEOUT,
            help="每次測試上限秒數（0 < 秒數 <= 86400，預設 300）",
        )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
