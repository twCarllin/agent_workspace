"""各情境 check.py 共用的斷言工具（純檔案斷言，不呼叫任何 agent）。

結果 JSON 來自共用 harness adapter，欄位格式不可信任（R-003／R-018）：缺鍵、非字串一律當 FAIL 不拋例外。
"""
import glob
import json
import os
import subprocess

MANIFEST_SUFFIX_EXCLUDE = (".eval.json", ".test_baseline.json", ".events.jsonl", ".dispatch.jsonl", "tier0.jsonl")


class Checker:
    def __init__(self):
        self.failed = 0
        self.total = 0

    def check(self, name, ok, reason=""):
        tag = "PASS" if ok else "FAIL"
        self.total += 1
        if not ok:
            self.failed += 1
        # 理由只在 FAIL 時印：呼叫端的 reason 寫的是「為什麼不符合」
        print(f"{tag} {name}" + (f" — {reason}" if (reason and not ok) else ""))

    def result_text(self, data):
        """取回應正文；缺 result 鍵 → 記 FAIL 並回 None（呼叫端跳過依賴文字的斷言）。"""
        if not isinstance(data, dict) or data.get("is_error") or not isinstance(data.get("result"), str):
            self.check("輸出含 result", False, "結果 JSON 缺 result 鍵或非字串")
            return None
        return data["result"]

    def finish(self):
        if self.total == 0:
            print("[check] FAIL 0 條，但沒有任何斷言被執行——視為檢查器錯誤")
            return 3
        print(f"[check] FAIL {self.failed} 條")
        return 1 if self.failed else 0


def load_result(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def manifests(fixture):
    """fixture 內 run/*.json 的 manifest（排除歸檔／baseline／事件檔），解析失敗者略過。"""
    out = []
    for p in sorted(glob.glob(os.path.join(fixture, "run", "*.json"))):
        if p.endswith(MANIFEST_SUFFIX_EXCLUDE):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and "run_id" in d:
            out.append(d)
    return out


def git(fixture, *args):
    r = subprocess.run(["git", *args], cwd=fixture, capture_output=True, text=True)
    return r.stdout


def commit_count(fixture):
    out = git(fixture, "rev-list", "--count", "HEAD").strip()
    return int(out) if out.isdigit() else -1


def changed_paths(fixture):
    """工作區＋索引相對 baseline commit 的變更路徑（含未追蹤）。"""
    paths = []
    for line in git(fixture, "status", "--porcelain").splitlines():
        if len(line) > 3:
            paths.append(line[3:].strip())
    return paths
