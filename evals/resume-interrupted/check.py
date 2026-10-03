#!/usr/bin/env python3
"""S3 中斷恢復（Game day）：恢復者只讀檔案狀態，應報出正確 run_id、從 task 2 的 step reviewing 續跑
（eval-flow-resume：reviewing → 一律重派 checker、從循環步驟 3 起），且不重跑已 passed 的 task 1。

恢復後把 run 跑完並 commit 是**正確**行為（首跑實測：恢復者重派 checker→升級 reviewer→step 5／6→commit）；
錯誤行為是重跑 task 1、或 commit 卻沒掛 Run-Id trailer／manifest 沒收尾。

綁定：setup.py 的 RUN_ID；eval_state.json 或歸檔 run/<run_id>.eval.json 的 `sub_tasks[0].status`／`step`；
manifest `status`；commit message 的 `Run-Id:` trailer。
已知限制：「task 1 未被重跑」只偵測經 `eval_state.py` 寫入 events.jsonl 的 id 1 事件；恢復者若繞過 eval_state.py 直接改檔不會被抓到（hook gate 另攔）。
用法：python3 check.py <fixture_dir> <result_json>   exit 0＝全部 PASS、1＝任一 FAIL。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _common import Checker, commit_count, git, load_result, manifests  # noqa: E402
from setup import RUN_ID  # noqa: E402

RESUME_MARKERS = ("checker", "task-verifier", "步驟 3", "step 3")


def main(fixture, result_path):
    c = Checker()
    data = load_result(result_path)
    text = c.result_text(data)
    if text is not None:
        c.check("回應含正確 run_id", RUN_ID in text, f"回應未出現 {RUN_ID}")
        low = text.lower()
        c.check("回應指出從重派 checker／步驟 3 續跑", any(m.lower() in low for m in RESUME_MARKERS),
                f"回應未出現任一標記 {RESUME_MARKERS}")
    # task 1 的狀態：eval_state.json（run 仍進行中）或歸檔 .eval.json（run 已收尾）其一
    state_paths = [os.path.join(fixture, "eval_state.json"), os.path.join(fixture, "run", f"{RUN_ID}.eval.json")]
    st = None
    for sp in state_paths:
        try:
            with open(sp, encoding="utf-8") as f:
                st = json.load(f)
            break
        except (OSError, json.JSONDecodeError):
            continue
    if st is None:
        c.check("task 狀態檔可讀（eval_state.json 或 .eval.json）", False, "兩處皆無法讀取")
    else:
        t1 = next((x for x in st.get("sub_tasks", []) if x.get("id") == 1), None)
        c.check("task 1 終態仍 passed／done／checker",
                t1 is not None and t1.get("status") == "passed" and t1.get("step") == "done" and t1.get("checked_by") == "checker",
                f"task1={None if t1 is None else {k: t1.get(k) for k in ('status', 'step', 'checked_by')}}")
    # 「未被重跑」要看過程不是終態：setup 不產生事件檔，恢復者寫的 events.jsonl 不得有 task 1（id 1）的事件
    ev = os.path.join(fixture, "run", f"{RUN_ID}.events.jsonl")
    t1_events = []
    try:
        with open(ev, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                args = d.get("args") or {}
                if str(args.get("id")) == "1":
                    t1_events.append(d.get("cmd"))
    except OSError:
        pass
    c.check("task 1 未被重跑（events 無 id 1 的事件）", not t1_events, f"task 1 的事件：{t1_events}")
    n = commit_count(fixture)
    if n > 2:
        msg = git(fixture, "log", "-1", "--format=%B")
        c.check("新 commit 掛 Run-Id trailer", f"Run-Id: {RUN_ID}" in msg, f"HEAD message 無 Run-Id: {RUN_ID}")
        ms = [m for m in manifests(fixture) if m.get("run_id") == RUN_ID]
        c.check("commit 後 manifest 已收尾（status completed）", bool(ms) and ms[0].get("status") == "completed",
                f"manifest status={ms[0].get('status') if ms else '<無>'}")
    else:
        ms = [m for m in manifests(fixture) if m.get("run_id") == RUN_ID]
        c.check("未 commit 時 manifest 仍 in_progress／ready_to_commit",
                bool(ms) and ms[0].get("status") in ("in_progress", "ready_to_commit"),
                f"manifest status={ms[0].get('status') if ms else '<無>'}")
    return c.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法：check.py <fixture_dir> <result_json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
