#!/usr/bin/env python3
"""eval-flow 循環 step 1「知識前置」的 retro 條目篩選執行端。

用法：
  python3 .agent-flow/scripts/retro_select.py --files src/a.py tests/test_a.py
  python3 .agent-flow/scripts/retro_select.py --files .agent-flow/scripts/eval_gates.py --retro retro/RETRO.md

為什麼要 script：篩選是三個機械步驟（以模組名片段比對標籤 → 排除 retired → 對帶錨點的條目 grep
錨點是否仍存在），每次派工都要重做一遍；留給模型逐次手做既費 token 又會漏步（R-011 的教訓是
知識必須原文前置進 prompt，而「選哪幾條」這一步本身是確定性的）。

輸出三節，可直接取用：
  1. 選中條目——逐條原文，貼進 code-writer prompt 的硬性約束區
  2. retire 候選——錨點已不存在於 codebase 的條目（不貼，於收尾回報使用者）
  3. 未命中——retro 源無相關條目時的留痕句

exit 0 = 正常（含零命中，選擇器不是 gate）；exit 1 = 使用錯誤（RETRO.md 讀不到等）。
"""
import argparse
import os
import re
import subprocess
import sys

# 條目格式（RETRO.md 檔頭的 ID 規則與 retired 生命週期節為單一枚舉點）：
#   - R-NNN [［retired YYYY-MM-DD <run_id>］ ]YYYY-MM-DD［標籤／標籤／run_id］背景…**約束：…**[［錨點: X］]
ENTRY_RE = re.compile(
    r"^- (?P<id>R-\d{3})\s*"
    r"(?:［retired (?P<retired>[^］]*)］)?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"［(?P<tag>[^］]*)］"
)
ANCHOR_RE = re.compile(r"［錨點: (?P<anchor>[^］]*)］")
# 看起來像路徑的錨點：含 / 或以短副檔名結尾（`legacy_helper.py`、`skills/eval-flow/SKILL.md`）。
# 刻意不含 `eval_state.append_event` 這種 dotted 符號名（尾段長度 >5）——它要用內容搜。
PATHLIKE_ANCHOR_RE = re.compile(r"^[\w./\-]+(?:/|\.\w{1,5})$")

# 模組名片段的長度下限：2 字元以下的片段會在標籤中大量假命中。
# 已知取捨：**真實的 2 字元模組名（db、ui、ai）會被丟棄**；若某 item 的 files 只剩這類名稱，
# script 會 exit 1（推導不出片段）而非靜默選出全部條目——寧可要求呼叫者明示，不可假裝篩過。
MIN_FRAGMENT_LEN = 3
# 路徑中不具模組意義的通用名，不當片段用（避免 skills/*/SKILL.md 全部互相命中）。
# 不列副檔名（md、py）——splitext 已去除，且長度 2 本就被 MIN_FRAGMENT_LEN 濾掉，列了是死項。
# 已知取捨：專案若真有名為 lib／src 的模組，該片段會被濾掉；其餘目錄與檔名主幹仍會產生片段。
GENERIC_PARTS = {"skill", "skills", "claude", "src", "lib"}


def fail(msg, code=1):
    print(f"[retro-select] {msg}", file=sys.stderr)
    sys.exit(code)


def module_fragments(paths):
    """由檔案路徑推導模組名片段：目錄名＋檔名主幹，去掉前導點與通用名。

    依 eval-flow 循環 step 1：「grep 篩選的對象是模組名片段（取自 files 路徑的目錄／檔名，
    如 eval_gates、hooks），不是整段路徑」——retro 標籤慣用全形 ／，整段半形路徑會靜默零命中。
    """
    frags = set()
    for p in paths:
        p = p.strip()
        if not p:
            continue
        head, tail = os.path.split(p)
        parts = [x for x in head.split(os.sep) if x] + [os.path.splitext(tail)[0]]
        for part in parts:
            part = part.lstrip(".")
            if len(part) >= MIN_FRAGMENT_LEN and part.lower() not in GENERIC_PARTS:
                frags.add(part)
    return sorted(frags)


RUNID_SEGMENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def match_tag(tag):
    """標籤中可用於模組比對的部分：去掉尾端的 run_id 段。

    step 1 寫「標籤第一段＝模組路徑」，run_id 是尾段。拿整段標籤比對會讓片段命中 run_id
    （實測：`tests` 命中 run_id `2026-07-17-writer-scoped-tests`），把無關條目貼進 prompt。
    不只取第一段——部分條目的模組資訊跨前兩段（如 `hooks/test_baseline.py｜skills/test-strategy`）。
    """
    segs = [x for x in re.split(r"[／|｜]", tag) if x.strip()]
    return "／".join(x for x in segs if not RUNID_SEGMENT_RE.match(x.strip()))


def parse_entries(text):
    """逐行解析 RETRO.md 的條目；非條目行（檔頭說明、格式範例）一律跳過。

    以 `- R-` 開頭卻解析不出格式的行會印警告——靜默略過會讓「條目 N 條」少算而無人知道。
    """
    entries, unparsed = [], []
    for no, line in enumerate(text.splitlines(), 1):
        m = ENTRY_RE.match(line)
        if not m:
            if line.startswith("- R-"):
                unparsed.append((no, line[:60]))
            continue
        anchor = ANCHOR_RE.search(line)
        entries.append({
            "lineno": no,
            "id": m.group("id"),
            "retired": m.group("retired"),
            "tag": m.group("tag"),
            "match_tag": match_tag(m.group("tag")),
            "anchor": anchor.group("anchor") if anchor else None,
            "text": line.rstrip(),
        })
    for no, snippet in unparsed:
        print(f"[retro-select] 警告：第 {no} 行以 `- R-` 開頭但不符條目格式，已略過：{snippet}",
              file=sys.stderr)
    return entries


# 錨點 grep 的排除清單：**記錄性檔案不算 codebase**。
# 不排除會讓鮮度檢查整條失效——條目自己就寫著錨點字串（RETRO.md），而 HISTORY.md／run/ 等
# 冷溯源檔的存在目的正是記載已消失的機制；把它們算進去，每個錨點都「仍存在」。
EXCLUDED_FROM_ANCHOR_SCAN = ("HISTORY.md", "retro/", "run/", "task/", "spec/",
                             "usage/", "impact/", "risk/")


def _anchor_scan_excludes(retro_path, root):
    """回傳要排除的 repo 相對路徑（記錄性檔案＋--retro 指到的那份條目檔本身）。

    用 realpath 不用 abspath：abspath 只做字串正規化，兩種輸入會讓排除失效（實測重現）——
    ①`--retro` 是 symlink 時只排除 link、目標檔仍被掃到，條目錨點誤判「仍存在」而被選中；
    ②macOS 的 `/tmp` 是 `/private/tmp` 的 symlink，`--retro /tmp/...` 與來自 getcwd 的 root
    拼法不同，relpath 得到 `../..` 被當 repo 外而不排除。兩層（pathspec 與退路掃描）共用
    此 rel，故一處解錯兩層都失效。
    """
    excludes = list(EXCLUDED_FROM_ANCHOR_SCAN)
    try:
        rel = os.path.relpath(os.path.realpath(retro_path), os.path.realpath(root))
    except (ValueError, OSError):
        return excludes
    if not rel.startswith(".."):
        excludes.append(rel)
    return excludes


def anchor_alive(anchor, root, excludes):
    """錨點（檔案／helper／機制名）是否仍存在於 codebase（排除記錄性檔案）。

    以 git grep 在版控內容中查字面字串；非 git repo 或 git 不可用時退回 os.walk 掃描。
    回傳 True＝仍存在（條目可貼）、False＝已消失（條目轉 retire 候選）。
    """
    if not anchor:
        return True
    probe = anchor.strip()
    if not probe:
        return True
    # 檔名型錨點（prose 明列錨點可以是「檔案」）：先查檔案本身是否存在。
    # 只搜內容會誤判——一個存在但沒被任何檔案提及的 script 會被判「已消失」（實測重現）。
    if PATHLIKE_ANCHOR_RE.match(probe):
        if os.path.exists(os.path.join(root, probe)):
            return True
        try:
            r = subprocess.run(["git", "ls-files", "--error-unmatch", "--", probe],
                               cwd=root, capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        # 檔案不在 → 繼續往下用內容搜（錨點也可能是被引用的機制名）
    try:
        # pathspec 必須用 :(exclude,literal)：`:!` 會把排除路徑當 glob，**過度排除**符合樣式
        # 的兄弟檔。實測（含 `*` 的 --retro 路徑旁有符合該 glob 的檔案、錨點只在兄弟檔中）：
        # literal → 兄弟檔命中（錨點仍存在，正確）；`:!` → 零命中（錨點誤判已消失，產生
        # 錯誤的 retire 候選）。對排除路徑**自身**兩者等價，差異只在兄弟檔。
        # 回歸鎖：tests/test_retro_select.py::test_glob_sibling_file_is_not_over_excluded。
        argv = (["git", "grep", "-l", "-F", "-e", probe, "--"]
                + [f":(exclude,literal){x}" for x in excludes])
        r = subprocess.run(argv, cwd=root, capture_output=True, text=True)
        if r.returncode in (0, 1):
            return bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    # 退路：git 不可用時自行掃描純文字檔（同樣套用排除清單）
    norm = [x.rstrip("/") for x in excludes]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules")]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if any(rel == x or rel.startswith(x + os.sep) for x in norm):
                continue
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    if probe in f.read():
                        return True
            except OSError:
                continue
    return False


def select(entries, fragments, root, excludes):
    """回傳 (選中, retire 候選)：標籤命中任一片段、未 retired，且錨點仍存在者為選中。"""
    chosen, retire = [], []
    for e in entries:
        # `is not None`：`［retired ］`（原因為空）會讓 group 取到 ""，用真值判斷會漏掉它
        # 而把已退役條目貼進 prompt（DoD：標 ［retired］ 一律不選）
        if e["retired"] is not None:
            continue
        if not any(f.lower() in e["match_tag"].lower() for f in fragments):
            continue
        if anchor_alive(e["anchor"], root, excludes):
            chosen.append(e)
        else:
            retire.append(e)
    return chosen, retire


class _ArgParser(argparse.ArgumentParser):
    """argparse 預設把參數錯誤當 exit 2。

    cite_check 的 exit 2 專指「整份退回 reviewer 重審」，撞碼會讓呼叫者把命令列寫錯
    誤讀成退件；兩個 script 的 DoD 都寫「使用錯誤 exit 1」，故改走 fail(…, 1)。
    """

    def error(self, message):
        fail(f"參數錯誤：{message}", 1)


def main():
    ap = _ArgParser(description="知識前置的 retro 條目篩選（eval-flow 循環 step 1）")
    ap.add_argument("--files", nargs="+", required=True,
                    help="本 item 的 files 欄（空白或逗號分隔皆可）")
    ap.add_argument("--retro", default="retro/RETRO.md", help="RETRO.md 路徑（預設 retro/RETRO.md）")
    ap.add_argument("--root", default=".", help="錨點 grep 的 codebase 根目錄（預設當前目錄）")
    args = ap.parse_args()

    paths = [p for chunk in args.files for p in chunk.split(",")]
    if not any(p.strip() for p in paths):
        fail("--files 為空")
    try:
        with open(args.retro, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        fail(f"讀不到 {args.retro}（{e}）")

    fragments = module_fragments(paths)
    if not fragments:
        fail(f"--files 推導不出任何模組名片段（長度 ≥{MIN_FRAGMENT_LEN} 且非通用名）：{paths}")
    entries = parse_entries(text)
    excludes = _anchor_scan_excludes(args.retro, args.root)
    chosen, retire = select(entries, fragments, args.root, excludes)

    print(f"[retro-select] 模組名片段：{'、'.join(fragments)}")
    print(f"[retro-select] {args.retro} 條目 {len(entries)} 條；選中 {len(chosen)}、retire 候選 {len(retire)}")
    print()
    print("## 選中條目（原文貼進 code-writer prompt 的硬性約束區）")
    print()
    if chosen:
        for e in chosen:
            print(e["text"])
    else:
        print("retro 源無相關條目（三源皆無時於 prompt 註明）")
    print()
    print("## retire 候選（錨點已不存在於 codebase，不貼進 prompt，於收尾回報使用者）")
    print()
    if retire:
        for e in retire:
            print(f"{e['id']}（錨點 `{e['anchor']}` 查無）：{e['text'][:120]}")
    else:
        print("無")
    return 0


if __name__ == "__main__":
    sys.exit(main())
