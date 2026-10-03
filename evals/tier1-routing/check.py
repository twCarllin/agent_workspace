#!/usr/bin/env python3
"""S1 判級＋觸發：模型拿到一個理由碼空集合的小需求後，應判 Tier 1、載入 eval-flow、建出 manifest。

綁定欄位（改欄位名時一併改此檔）：manifest `tier`、`tier_rationale`（run/<run_id>.json）；`run/<run_id>.events.jsonl` 的 `cmd: init` 事件（eval-flow Tier 1 精簡路徑第 1 步寫入，是「照 skill 程序走」的機械證據——首跑實測模型照做了卻沒在回應裡點名 skill，文字比對會誤判）。
用法：python3 check.py <fixture_dir> <result_json>   exit 0＝全部 PASS、1＝任一 FAIL。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _common import Checker, load_result, manifests  # noqa: E402


def main(fixture, result_path):
    c = Checker()
    data = load_result(result_path)
    text = c.result_text(data)

    ms = manifests(fixture)
    c.check("manifest 已建立", bool(ms), f"run/ 下的 manifest 數：{len(ms)}（排除 .eval／baseline／events）")
    if ms:
        m = ms[0]
        c.check("tier 判為 1", m.get("tier") == 1, f"tier={m.get('tier')!r}")
        tr = m.get("tier_rationale")
        c.check("tier_rationale 非空", isinstance(tr, str) and tr.strip() != "", f"tier_rationale={str(tr)[:80]!r}")
        ev = os.path.join(fixture, "run", f"{m.get('run_id')}.events.jsonl")
        has_init = False
        try:
            with open(ev, encoding="utf-8") as f:
                for line in f:
                    try:
                        if json.loads(line).get("cmd") == "init":
                            has_init = True
                            break
                    except (json.JSONDecodeError, AttributeError):
                        continue
        except OSError:
            pass
        c.check("events.jsonl 含 init 事件（Tier 1 第 1 步留痕）", has_init, f"{os.path.relpath(ev, fixture)} 不存在或無 init 事件")
    return c.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法：check.py <fixture_dir> <result_json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
