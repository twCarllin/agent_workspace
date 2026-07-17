#!/usr/bin/env python3
"""部署健檢：在目標專案根目錄執行，驗證 flow 基礎設施完整且未過期。

用法：
  python3 .claude/hooks/doctor.py

檢查：
  1. hooks 檔案齊全（5 個 script ＋ VERSION）且 Python 檔可編譯
  2. .claude/settings.json 的 PreToolUse 含 gate-check（防線真的接上）
  3. 核心 skill 已部署到 ~/.claude/skills/
  4. retro/RETRO.md 存在（seed 或累積）
  5. 殘留狀態：eval_state.json 存在 → 提示有 in_progress run（resume 或收尾）

exit 0 = 全過；exit 1 = 有問題（逐條列出）。修法：重跑 agent_workspace 的 init.sh。
"""
import json
import os
import py_compile
import sys

HOOKS = ["eval_gates.py", "test_baseline.py", "test_lint.py", "eval_state.py", "stats.py"]
CORE_SKILLS = ["eval-flow", "eval-flow-resume", "test-strategy", "task-decomposition"]


def main():
    hooks_dir = os.path.dirname(os.path.abspath(__file__))
    issues = []
    ok = []

    for name in HOOKS:
        path = os.path.join(hooks_dir, name)
        if not os.path.exists(path):
            issues.append(f"hooks 缺 {name}")
            continue
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as e:
            issues.append(f"{name} 無法編譯：{e}")
    version_path = os.path.join(hooks_dir, "VERSION")
    version = None
    if os.path.exists(version_path):
        with open(version_path, encoding="utf-8") as f:
            version = f.read().strip()
        ok.append(f"framework 版本：{version}")
    else:
        issues.append("hooks 缺 VERSION（無法判斷部署版本）")

    settings_path = os.path.join(os.path.dirname(hooks_dir), "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
        entries = json.dumps(settings.get("hooks", {}).get("PreToolUse", []))
        if "gate-check" in entries:
            ok.append("settings.json PreToolUse 含 gate-check")
        else:
            issues.append("settings.json 的 PreToolUse 沒接 gate-check——gate 防線未生效")
    except (OSError, json.JSONDecodeError) as e:
        issues.append(f"settings.json 讀不到或非法 JSON（{e}）")

    skills_dir = os.path.join(os.path.expanduser("~"), ".claude", "skills")
    missing = [s for s in CORE_SKILLS if not os.path.isdir(os.path.join(skills_dir, s))]
    if missing:
        issues.append(f"~/.claude/skills 缺核心 skill：{', '.join(missing)}")
    else:
        ok.append(f"核心 skill 已部署（{len(CORE_SKILLS)} 個）")

    if os.path.exists("retro/RETRO.md"):
        ok.append("retro/RETRO.md 存在")
    else:
        issues.append("retro/RETRO.md 不存在（seed 未部署？retro 前置步驟會落空）")

    if os.path.exists("eval_state.json"):
        state = None
        try:
            with open("eval_state.json", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        rid = state.get("run_id") if isinstance(state, dict) else "?"
        ok.append(f"⚠ eval_state.json 存在（run_id: {rid}）——有 in_progress 的 run，依 eval-flow-resume 續跑或收尾")

    for line in ok:
        print(f"[doctor] OK: {line}")
    for line in issues:
        print(f"[doctor] ISSUE: {line}", file=sys.stderr)
    if issues:
        print(f"[doctor] {len(issues)} 個問題——修法：重跑 agent_workspace 的 ./init.sh", file=sys.stderr)
        sys.exit(1)
    print("[doctor] 健檢通過")


if __name__ == "__main__":
    main()
