#!/usr/bin/env python3
"""SessionStart hook：把「靠記得」變機械事實。

註冊於 `.claude/settings.json`，matcher `startup|resume|compact`（全新啟動／resume／
compaction 後 session 重建三種進入點皆觸發）。stdout 純文字，會被注入 Claude context。

輸出兩部分（無則各自略過，皆無則輸出空）：
  ①殘留 in_progress run 提示（`eval_state.json` 存在，或 `run/*.json` 中有
    `status: in_progress` 的 manifest，`MANIFEST_RE` 同源判定）
  ②`doctor.py --brief` 的異常行

輸出上限 10 行（進 context 的成本要小；官方硬上限 10,000 字元）。
stdin payload 解析失敗一律靜默 exit 0（hook 壞掉不可拖垮 session）。
解析成功後以 `eval_gates._resolve_root(payload)` 解出 worktree 根再 chdir，
與姊妹 hook（`eval_gates.run_hook()`）一致，避免 worktree session 下誤掃主 repo 的 run/。
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402  重用 MANIFEST_RE／load_json_quiet（單一判定點鐵律）

MAX_OUTPUT_LINES = 10


def _residual_run_id_and_phase():
    """判定是否有殘留未收尾的 run，回傳 (run_id, phase) 或 None（無殘留）。
    `eval_state.json` 存在（Tier 2 常規進行中）優先取其 run_id；否則掃 `run/*.json`
    找 `status == in_progress` 的 manifest（Tier 1 或孤兒 eval_state 情境）。"""
    run_id = None
    if os.path.exists("eval_state.json"):
        state = eval_gates.load_json_quiet("eval_state.json")
        if isinstance(state, dict):
            run_id = state.get("run_id")
    if run_id is None:
        for path in sorted(glob.glob("run/*.json")):
            if not eval_gates.MANIFEST_RE.match(path):
                continue
            m = eval_gates.load_json_quiet(path)
            if isinstance(m, dict) and m.get("status") == "in_progress":
                run_id = m.get("run_id") or eval_gates.MANIFEST_RE.match(path).group("run_id")
                break
    if run_id is None:
        return None
    phase = None
    manifest = eval_gates.load_json_quiet(f"run/{run_id}.json")
    if isinstance(manifest, dict):
        phase = manifest.get("phase")
    return run_id, phase


def _doctor_brief_lines():
    """跑 `doctor.py --brief`，回傳其輸出行（去空行）；doctor 呼叫失敗則回空清單
    （旁路容錯——doctor 健檢是加值資訊，不可讓 hook 本身炸掉）。"""
    hooks_dir = os.path.dirname(os.path.abspath(__file__))
    doctor_path = os.path.join(hooks_dir, "doctor.py")
    try:
        p = subprocess.run(
            [sys.executable, doctor_path, "--brief"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = (p.stdout + p.stderr).strip()
    return [line for line in out.splitlines() if line]


def build_output():
    lines = []
    residual = _residual_run_id_and_phase()
    if residual is not None:
        run_id, phase = residual
        lines.append(
            f"有未收尾的 run：{run_id}（phase={phase}），"
            f"依 eval-flow-resume skill 從檔案恢復，不靠記憶；或標 aborted 收尾"
        )
    lines.extend(_doctor_brief_lines())
    return lines[:MAX_OUTPUT_LINES]


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # payload 解析失敗，靜默不擋 session
    if not isinstance(payload, dict):
        payload = {}

    # 與姊妹 hook（eval_gates.run_hook()）一致：不信任 getcwd()，以 payload.cwd
    # 解析 worktree 根後才 chdir（BUGLOG 2026-07-28 worktree-root gate 靜默失效同源修正）。
    os.chdir(eval_gates._resolve_root(payload))

    lines = build_output()
    if lines:
        print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
