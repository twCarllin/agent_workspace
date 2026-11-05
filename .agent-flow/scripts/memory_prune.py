#!/usr/bin/env python3
"""Claude Code 自動記憶的整理候選：列出、或把結案記錄搬到 _archive/。

用法：
  python3 .agent-flow/scripts/memory_prune.py              # dry-run，列候選
  python3 .agent-flow/scripts/memory_prune.py --apply a.md b.md   # 整理過的候選指名搬到 _archive/；不指名不搬
  python3 .agent-flow/scripts/memory_prune.py --notice     # 供 SessionStart hook：有候選印一行，否則不印

記憶目錄＝`~/.claude/projects/<slug>/memory`，slug＝專案根路徑非英數字元轉 `-`；
`CLAUDE_MEMORY_DIR` 環境變數可覆寫（測試與非標準佈局用）。
三類候選：①MEMORY.md 超過 INDEX_LIMIT 字元；②type project 且超過 STALE_DAYS 未修改；
③內文含否決句（VETO_RE）——這類不搬，要改寫成「條件→動作」。
沒有記憶目錄一律靜默 exit 0。
"""
import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

INDEX_LIMIT = 4096
STALE_DAYS = 30
VETO_RE = re.compile(r"效果不穩|擋不住|區分力弱|效果不佳|沒有用|行不通")
TYPE_RE = re.compile(r"^\s*type:\s*(\S+)", re.M)


def memory_dir(root):
    override = os.environ.get("CLAUDE_MEMORY_DIR")
    if override:
        return Path(override)
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))
    return Path.home() / ".claude" / "projects" / slug / "memory"


def candidates(directory, now=None):
    """回傳 [(kind, path, reason)]；kind ∈ index／stale／veto。"""
    now = time.time() if now is None else now
    found = []
    index = directory / "MEMORY.md"
    if index.is_file() and len(index.read_text(encoding="utf-8", errors="replace")) > INDEX_LIMIT:
        found.append(("index", index, f"索引超過 {INDEX_LIMIT} 字元，每個 session 全載"))
    for path in sorted(directory.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = TYPE_RE.search(text)
        kind = match.group(1) if match else ""
        age_days = (now - path.stat().st_mtime) / 86400
        if kind == "project" and age_days > STALE_DAYS:
            found.append(("stale", path, f"結案記錄 {int(age_days)} 天未修改"))
        elif VETO_RE.search(text):
            found.append(("veto", path, "含否決句，改寫成「條件→動作」或移除"))
    return found


def archive(directory, items, names):
    """只搬指名且在候選清單內的檔（agent 讀過、抽完仍有效內容後才指名）；從 MEMORY.md 移除索引行。"""
    target = directory / "_archive"
    moved = []
    wanted = set(names)
    for kind, path, _ in items:
        if kind == "index" or path.name not in wanted:
            continue
        target.mkdir(exist_ok=True)
        shutil.move(str(path), str(target / path.name))
        moved.append(path.name)
    index = directory / "MEMORY.md"
    if moved and index.is_file():
        lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not any(f"({name})" in line for name in moved)]
        index.write_text("".join(kept), encoding="utf-8")
    return moved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", nargs="*", metavar="FILE", help="整理後要搬的檔名；不指名不搬")
    parser.add_argument("--notice", action="store_true", help="hook 用：一行或無輸出")
    args = parser.parse_args()
    directory = memory_dir(args.root)
    if not directory.is_dir():
        return 0
    items = candidates(directory)
    if args.notice:
        if items:
            print(
                f"記憶可整理 {len(items)} 項（{directory}）："
                f"python3 .agent-flow/scripts/memory_prune.py 看清單"
            )
        return 0
    if not items:
        print("[memory-prune] 無候選")
        return 0
    for kind, path, reason in items:
        print(f"[{kind}] {path.name}：{reason}")
    if args.apply:
        unknown = sorted(set(args.apply) - {path.name for _, path, _ in items})
        if unknown:
            print(f"[memory-prune] 不在候選清單，不搬：{', '.join(unknown)}", file=sys.stderr)
            return 2
        moved = archive(directory, items, args.apply)
        print(f"[memory-prune] 已搬到 _archive/：{', '.join(moved) or '無'}")
    elif args.apply is not None:
        print("[memory-prune] --apply 須指名整理過的檔案；先讀、把仍有效的條件→動作併入長期記憶，再搬")
    else:
        print("[memory-prune] dry-run；整理後用 --apply <檔名> 搬，不刪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
