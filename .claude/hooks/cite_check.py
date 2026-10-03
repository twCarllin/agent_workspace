#!/usr/bin/env python3
"""eval-flow 循環 step 3「引文核實」的執行端：對 staged 內容逐條核實審查發現的引文。

用法：
  python3 .claude/hooks/cite_check.py --citations cites.tsv
  python3 .claude/hooks/cite_check.py --citations -        # 由 stdin 讀

輸入格式：每行 `檔案<TAB>行號<TAB>引文片段`（`#` 開頭與空行跳過）。

分工（刻意只做後半）：**模型負責從審查報告擷取引文三元組**（讀理解），**script 負責核實與判定**。
R-012 的教訓是這個判定留「臨場裁量」空間時實測被繞過三次，所以判定不留給模型：

  引文不存在於 staged 內容        → 駁回（照修等於為幻覺改 code）
  引文存在、行號相符              → ok
  引文存在、行號不符（文字為真）  → 不駁回，輸出實得行號供主 flow 改寫
  檔案不在 index                  → 駁回（無 staged 憑據可核）

比對一律**字面**（非 regex）——引文常含 `.` `*` `[` `$` 等字元。

exit 0 = 本批可用（逐條判定見輸出）；exit 2 = 行號修正達門檻、整份退回 reviewer 重審；
exit 1 = 使用錯誤（輸入格式、讀不到檔）。
"""
import argparse
import subprocess
import sys

# 「同一份審查報告需行號修正 ≥3 條 → 整份報告視為未經核對，退回 reviewer 重審」
# 數字來源：eval-flow 循環 step 3「機械退件門檻」（該節為單一枚舉點，改此處須同步該節）。
REWRITE_REJECT_THRESHOLD = 3

VERDICT_OK = "ok"
VERDICT_MISSING = "駁回（引文不存在）"
VERDICT_UNSTAGED = "駁回（檔案不在 staging）"


def fail(msg, code=1):
    print(f"[cite-check] {msg}", file=sys.stderr)
    sys.exit(code)


def read_citations(src):
    """讀 TSV 引文三元組；格式錯誤即中止（使用錯誤），不默默跳過。"""
    text = sys.stdin.read() if src == "-" else _read_file(src)
    cites = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            fail(f"第 {no} 行格式錯誤（需 檔案<TAB>行號<TAB>引文片段）：{line[:80]}")
        path, lineno, fragment = parts[0].strip(), parts[1].strip(), "\t".join(parts[2:])
        if not fragment.strip():
            fail(f"第 {no} 行的引文片段為空：{line[:80]}")
        try:
            lineno = int(lineno)
        except ValueError:
            fail(f"第 {no} 行的行號不是整數：{parts[1][:40]}")
        cites.append({"path": path, "line": lineno, "fragment": fragment})
    if not cites:
        fail("輸入沒有任何引文（空輸入）")
    return cites


def _read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        fail(f"讀不到引文檔 {path}（{e}）")


def require_git_repo():
    """先確認在 git 工作區內——否則每條引文都會被誤判成「檔案不在 staging」。

    把環境錯誤降級成逐條駁回，會讓一份完好的審查報告整份被丟掉；環境錯誤屬使用錯誤（exit 1）。
    """
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as e:
        fail(f"git 無法執行（{e}）")
    if r.returncode != 0 or r.stdout.strip() != "true":
        fail("當前目錄不在 git 工作區內——引文核實的對象是 staged 內容（git index）")


def staged_lines(path, cache):
    """取 staged 內容（`git show :<path>`）的行清單；不在 index 回 None。

    - 不經 shell（list argv）——路徑可能含空白或特殊字元（R-003）
    - **行號語義與 `grep -n` 一致**：只在 b"\n" 斷行。不可用 str.splitlines()——它額外在
      \x0c、\x1c-\x1e、\x85、\u2028/\u2029 與孤立 \r 斷行，行號會比 grep -n 多算，
      輸出錯誤的「行號修正」而主 flow 會照著改（實測：含 \x0c 的檔 grep -n 得 3、splitlines 得 4）
    - 讀 bytes 後逐行 errors="replace" 解碼：staged 檔可能不是 UTF-8，text=True 會拋
      UnicodeDecodeError（未捕捉的 traceback，違反契約「不拋例外」）
    """
    if path in cache:
        return cache[path]
    try:
        r = subprocess.run(["git", "show", f":{path}"], capture_output=True)
    except (OSError, subprocess.SubprocessError) as e:
        fail(f"git show :{path} 無法執行（{e}）")
    if r.returncode != 0:
        cache[path] = None
        return None
    raw = r.stdout.split(b"\n")
    if raw and raw[-1] == b"":
        raw.pop()          # 尾端換行不算一行（與 grep -n 的行數一致）
    lines = [chunk.decode("utf-8", errors="replace") for chunk in raw]
    cache[path] = lines
    return lines


def verify(cite, cache):
    """回傳 (verdict, 實得行號清單)。字面比對，不用 regex。"""
    lines = staged_lines(cite["path"], cache)
    if lines is None:
        return VERDICT_UNSTAGED, []
    hits = [i for i, text in enumerate(lines, 1) if cite["fragment"] in text]
    if not hits:
        return VERDICT_MISSING, []
    if cite["line"] in hits:
        return VERDICT_OK, hits
    return f"行號修正: {cite['line']}→{'／'.join(map(str, hits))}", hits


class _ArgParser(argparse.ArgumentParser):
    """argparse 預設把參數錯誤當 exit 2。

    cite_check 的 exit 2 專指「整份退回 reviewer 重審」，撞碼會讓呼叫者把命令列寫錯
    誤讀成退件；兩個 script 的 DoD 都寫「使用錯誤 exit 1」，故改走 fail(…, 1)。
    """

    def error(self, message):
        fail(f"參數錯誤：{message}", 1)


def main():
    ap = _ArgParser(description="審查引文核實（eval-flow 循環 step 3）")
    ap.add_argument("--citations", required=True,
                    help="引文 TSV 檔（檔案<TAB>行號<TAB>片段），`-` 表示 stdin")
    args = ap.parse_args()

    # 門檻刻意**不提供旗標**：R-012 的教訓是這個判定留裁量空間就會被繞過，
    # 可調的門檻等於可關掉的 gate。要改門檻就改常數（並同步 eval-flow step 3）。
    threshold = REWRITE_REJECT_THRESHOLD
    require_git_repo()
    cites = read_citations(args.citations)
    cache, rows = {}, []
    for c in cites:
        verdict, hits = verify(c, cache)
        rows.append((c, verdict, hits))

    rejected = [r for r in rows if r[1] in (VERDICT_MISSING, VERDICT_UNSTAGED)]
    rewrites = [r for r in rows if r[1].startswith("行號修正")]

    print(f"[cite-check] 引文 {len(rows)} 條：ok {len(rows) - len(rejected) - len(rewrites)}、"
          f"駁回 {len(rejected)}、行號修正 {len(rewrites)}（門檻 {threshold}）")
    print()
    for c, verdict, _ in rows:
        print(f"{c['path']}:{c['line']}\t{verdict}\t{c['fragment'][:60]}")
    print()
    if rejected:
        print("## 駁回（不得進 fixing；記入該輪處置摘要）")
        for c, verdict, _ in rejected:
            print(f"- {c['path']}:{c['line']} {verdict}：{c['fragment'][:80]}")
        print()
    if rewrites:
        print("## 行號修正（不駁回；以實得行號改寫該條後照常處置）")
        for c, verdict, _ in rewrites:
            print(f"- {c['path']} {verdict}：{c['fragment'][:80]}")
        print()
    if len(rewrites) >= threshold:
        print(f"## 判定：整份退回 reviewer 重審（行號修正 {len(rewrites)} 條 ≥ 門檻 {threshold}）")
        print("重審 prompt 須明列上方漏核對的條目；該輪不計入修正迭代上限。")
        return 2
    print("## 判定：本批可用（逐條依上方處置；駁回的不進 fixing）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
