#!/usr/bin/env python3
"""test-strategy skill 的執行端：測試 baseline 建立與「新增失敗」判定。

用法：
  python3 .claude/hooks/test_baseline.py baseline [--cmd "pytest -q"] [--run-id ID] [--fresh]
  python3 .claude/hooks/test_baseline.py check    [--cmd "pytest -q"] [--strike-key sub_task_1] [--run-id ID]
  python3 .claude/hooks/test_baseline.py related  --files src/a.py src/b.py
  python3 .claude/hooks/test_baseline.py mine     [--cmd "pytest -q"] [--strike-key sub_task_1] [--run-id ID]  # 只跑本次未提交變更範圍內的測試檔

--cmd 省略時讀 run/<run_id>.json（manifest）的 test_command 欄位——全套指令的
single source of truth，保證 baseline 與 check 的範圍一致。

baseline：跑一次，所有失敗記為 stable（既有壞測試，之後不擋）。
          寫入 run/<run_id>.test_baseline.json。
          既有 baseline 檔中存在「head_sha == 目前 HEAD 且 cmd 相同」者 → 直接沿用
          其 stable_failures 名單（baseline 記的是進場 HEAD 的既有失敗快照，同進場 HEAD
          即可沿用，免重跑全套；本 run 工作樹的新變更由 check 把關），--fresh 強制重建。
check：   跑一次，扣掉 baseline 的 stable_failures 後若有新失敗，重跑一次確認可重現：
          可重現 → 真的新增失敗，exit 2；不可重現 → 印警示「非確定性失敗，未阻擋」但不擋。
          真實新失敗會 append 一筆 failure_log 供稽核後存檔，exit 2。
related： 由變更檔案清單找出相關測試檔（測試檔命名慣例 + grep 引用），輸出路徑清單。

run_id 未指定時讀 eval_state.json 的 run_id。
exit 0 = gate 通過；exit 2 = 有新增穩定失敗（stderr 列清單）；exit 1 = 使用錯誤。
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

# 常見測試框架的失敗行樣式；比對不到且 exit != 0 時，整個 suite 當一個單位
FAIL_PATTERNS = [
    re.compile(r"^FAILED (\S+)", re.M),        # pytest
    re.compile(r"^ERROR (\S+)", re.M),         # pytest（collection error）
    re.compile(r"^--- FAIL: (\S+)", re.M),     # go test
    re.compile(r"^FAIL (\S+)", re.M),          # jest / vitest（檔案層級）
    re.compile(r"^\s*[✕×✗] (.+?)(?: \(\d+ ?m?s\))?$", re.M),  # jest / vitest / mocha
]

TEST_FILE_RE = re.compile(
    r"(^test_.*|.*_test\.\w+$|.*\.test\.\w+$|.*\.spec\.\w+$|.*Tests?\.\w+$)"
)
TEST_DIR_NAMES = {"test", "tests", "__tests__"}  # 不含 "spec"——與 eval-flow 自產的 spec/ 產出物目錄衝突
TEST_CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}


def fail(msg, code=1):
    print(f"[test-gate] {msg}", file=sys.stderr)
    sys.exit(code)


def _parse_fails(out, returncode):
    fails = set()
    for pat in FAIL_PATTERNS:
        fails.update(m.strip() for m in pat.findall(out))
    if returncode != 0 and not fails:
        fails.add("__suite__")
    return fails


def run_tests(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    return _parse_fails(out, p.returncode), p.returncode


def run_tests_argv(argv):
    """list argv 版本的 run_tests，不經 shell，用於 mine 子命令。"""
    p = subprocess.run(argv, capture_output=True, text=True)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    return _parse_fails(out, p.returncode), p.returncode


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
        fail(f"未指定 --cmd 且 {manifest} 無 test_command：請先把全套測試指令寫入 manifest，或用 --cmd 指定")
    return cmd


def git_head():
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return p.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None  # 非 git repo：不重用，照常全新建立


def find_reusable_baseline(run_id, cmd, head):
    """掃既有 baseline 檔，找「head_sha == 目前 HEAD 且 cmd 相同」者供沿用。
    多個符合時取排序最後者——契約：run_id 以可字典序排序的日期開頭
    （YYYY-MM-DD-slug），字典序即時序；命名慣例若變，此處要換排序鍵。
    找不到回 None。"""
    if not head:
        return None
    own = baseline_path(run_id)
    candidate = None
    for path in sorted(glob.glob("run/*.test_baseline.json")):
        if path == own:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("head_sha") == head and data.get("cmd") == cmd:
            candidate = data
    return candidate


def cmd_baseline(args):
    run_id = resolve_run_id(args)
    cmd = resolve_cmd(args, run_id)
    head = git_head()
    if not args.fresh:
        prev = find_reusable_baseline(run_id, cmd, head)
        if prev:
            os.makedirs("run", exist_ok=True)
            _save(baseline_path(run_id), {
                "run_id": run_id,
                "cmd": cmd,
                "head_sha": head,
                "reused_from": prev.get("run_id"),
                "stable_failures": prev.get("stable_failures", []),
            })
            print(
                f"[test-gate] 沿用 {prev.get('run_id')} 的 baseline"
                f"（HEAD 未變、cmd 相同），免重跑全套建基準；要強制重建用 --fresh"
            )
            return
    fails, _ = run_tests(cmd)
    stable = fails
    os.makedirs("run", exist_ok=True)
    data = {
        "run_id": run_id,
        "cmd": cmd,
        "head_sha": head,
        "stable_failures": sorted(stable),
    }
    with open(baseline_path(run_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(
        f"[test-gate] baseline 已寫入 {baseline_path(run_id)}："
        f"stable(既有壞測試，不擋) {len(stable)} 個"
    )
    if stable:
        print("[test-gate] 既有壞測試（欠帳，僅記錄）：" + ", ".join(sorted(stable)))


def cmd_check(args):
    run_id = resolve_run_id(args)
    path = baseline_path(run_id)
    if not os.path.exists(path):
        fail(f"{path} 不存在：先跑 baseline 子命令建立基準，再跑 check")
    with open(path, encoding="utf-8") as f:
        base = json.load(f)
    known = set(base.get("stable_failures", []))
    cmd = resolve_cmd(args, run_id)
    key = args.strike_key or "_default"

    fails, _ = run_tests(cmd)
    new = fails - known

    if new:
        print(f"[test-gate] 出現 {len(new)} 個非 baseline 的失敗，重跑一次確認可重現…")
        fails2, _ = run_tests(cmd)
        real = sorted(new & fails2)
        non_reproducible = sorted(new - fails2)
        if non_reproducible:
            print(f"[test-gate] 非確定性失敗，未阻擋：{', '.join(non_reproducible)}")
    else:
        real = []

    if real:
        failure_log = base.setdefault("failure_log", [])
        failure_log.append({"key": key, "tests": real})
        _save(path, base)
        print(f"[test-gate] BLOCK: 真實新失敗 {len(real)} 個，停止自修，回報使用者裁決", file=sys.stderr)
        for t in real:
            print(f"  - {t}", file=sys.stderr)
        sys.exit(2)

    ignored = fails & known
    print(
        f"[test-gate] PASS: 無新增穩定失敗"
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
            capture_output=True, text=True, check=True,
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


def _append_mine_log(run_id, strike_key, test_files, fails):
    """每次 mine 執行 append 一筆留痕（震盪稽核用：次數、失敗集合、測試檔內容 hash）。
    純記帳，失敗不得阻擋測試流程。回傳本次序號（記錄失敗時回 None）。"""
    path = f"run/{run_id}.mine_log.json"
    try:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {"run_id": run_id, "runs": []}
        hashes = {}
        for tf in test_files:
            try:
                with open(tf, "rb") as f:
                    hashes[tf] = hashlib.sha1(f.read()).hexdigest()[:10]
            except OSError:
                hashes[tf] = None
        seq = len(data["runs"]) + 1
        data["runs"].append({
            "seq": seq,
            "strike_key": strike_key,
            "fails": sorted(fails),
            "test_hashes": hashes,
        })
        os.makedirs("run", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return seq
    except OSError:
        return None


def cmd_mine(args):
    run_id = resolve_run_id(args)
    changed = git_changed_files()
    test_files = [f for f in changed if is_test_file(f)]

    if not test_files:
        print("[test-gate] 本次變更無測試檔（測試建立與否由 DoD 決定）")
        return

    cmd = resolve_cmd(args, run_id)
    mine_argv = build_mine_argv(cmd, test_files)

    fails, rc = run_tests_argv(mine_argv)
    seq = _append_mine_log(run_id, args.strike_key or "_default", test_files, fails)
    seq_note = f"（第 {seq} 次執行，已留痕 run/{run_id}.mine_log.json）" if seq else ""

    if rc == 0 and not fails:
        print(f"[test-gate] mine PASS: {len(test_files)} 個測試檔全部通過{seq_note}")
        return

    print(f"[test-gate] mine BLOCK: {len(fails)} 個失敗{seq_note}：", file=sys.stderr)
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
