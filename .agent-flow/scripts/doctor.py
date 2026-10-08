#!/usr/bin/env python3
"""部署健檢：在目標專案根目錄執行，驗證 flow 基礎設施完整且未過期。

用法：
  python3 .agent-flow/scripts/doctor.py

檢查：
  1. 共用核心檔案齊全（依 HOOKS 清單＋VERSION）且 Python 檔可編譯
  2. 依 harness 檢查 Claude hooks 或 Codex 角色設定
  3. 專案 .agents/skills 核心 skill 齊全（舊部署退回 ~/.claude/skills）
  4. retro/RETRO.md 存在（seed 或累積）
  5. 殘留狀態：eval_state.json 存在 → 提示有 in_progress run（resume 或收尾）

exit 0 = 全過；exit 1 = 有問題（逐條列出）。修法：重跑 agent_workspace 的 init.sh。

用法：
  python3 .agent-flow/scripts/doctor.py            完整輸出（OK＋ISSUE 逐條，全過再印健檢通過）
  python3 .agent-flow/scripts/doctor.py --brief    僅輸出異常行；全綠時無任何輸出（供其他 hook 內嵌呼叫）
"""
import argparse
import json
import os
import py_compile
import sys
import tomllib

HOOKS = ["eval_gates.py", "flow_rules.py", "run_evidence.py", "test_baseline.py", "test_lint.py", "eval_state.py", "stats.py", "session_start.py",
         "dispatch.py", "retro_select.py", "cite_check.py", "skill_eval.py", "harness_adapter.py", "harness_smoke.py", "flow.py", "flow_preflight.py", "review_packet.py"]
CORE_SKILLS = ["eval-flow", "eval-flow-resume", "test-strategy", "task-decomposition"]


def _non_dotfile(name):
    """排除 dotfile（.DS_Store 等），集中判定點。"""
    return not name.startswith(".")


def check_skills_sync(repo_skills_dir, deploy_skills_dir):
    """比對 repo skills/ 與部署層的存在性與內容一致性，回傳 (ok, issues) 兩個字串 list。"""
    ok = []
    issues = []

    if not os.path.isdir(repo_skills_dir):
        ok.append(f"repo skills/ 不存在，略過同步健檢（{repo_skills_dir}）")
        return ok, issues

    if not os.path.isdir(deploy_skills_dir):
        ok.append(f"部署層 skills/ 不存在，略過同步健檢（{deploy_skills_dir}）")
        return ok, issues

    def list_skills(d):
        return {n for n in os.listdir(d) if _non_dotfile(n) and n != "_deprecated" and os.path.isdir(os.path.join(d, n))}

    def dirs_equal(a, b):
        a_entries = {n for n in os.listdir(a) if _non_dotfile(n)}
        b_entries = {n for n in os.listdir(b) if _non_dotfile(n)}
        if a_entries != b_entries:
            return False
        for name in a_entries:
            ap, bp = os.path.join(a, name), os.path.join(b, name)
            if os.path.isdir(ap) and os.path.isdir(bp):
                if not dirs_equal(ap, bp):
                    return False
            elif os.path.isfile(ap) and os.path.isfile(bp):
                with open(ap, "rb") as f:
                    ac = f.read()
                with open(bp, "rb") as f:
                    bc = f.read()
                if ac != bc:
                    return False
            else:
                return False
        return True

    repo_skills = list_skills(repo_skills_dir)
    deploy_skills = list_skills(deploy_skills_dir)
    repo_only = repo_skills - deploy_skills
    deploy_only = deploy_skills - repo_skills
    common = repo_skills & deploy_skills

    for skill in sorted(repo_only):
        issues.append(f"skill '{skill}' 在 repo 有但未部署到部署層")

    for skill in sorted(deploy_only):
        issues.append(f"skill '{skill}' 在部署層有但未納入版控")

    for skill in sorted(common):
        if not dirs_equal(os.path.join(repo_skills_dir, skill), os.path.join(deploy_skills_dir, skill)):
            issues.append(f"skill '{skill}' 兩邊都有但內容不同步")

    if not issues:
        ok.append(f"skills 同步一致（{len(common)} 個 skill）")

    return ok, issues


def run_checks(harness=None):
    """跑全部健檢項目，回傳 (ok, issues) 兩份字串 list（不印出）。"""
    hooks_dir = os.path.dirname(os.path.realpath(__file__))
    script_root = os.path.dirname(os.path.dirname(hooks_dir))
    project_root = os.path.realpath(os.getcwd())
    # Legacy calls retain their script-root deployment checks. Explicit adapters
    # check the payload-resolved cwd project, including worktrees.
    settings_root = project_root if harness else script_root
    if harness is None:
        has_claude = os.path.isfile(os.path.join(project_root, ".claude", "settings.json"))
        has_codex = os.path.isfile(os.path.join(project_root, ".codex", "config.toml"))
        if has_claude or has_codex:
            harness = "both" if has_claude and has_codex else ("claude" if has_claude else "codex")
            settings_root = project_root
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

    if harness in (None, "claude", "both"):
        settings_path = os.path.join(settings_root, ".claude", "settings.json")
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
            entries = json.dumps(settings.get("hooks", {}).get("PreToolUse", []))
            if "gate-check" in entries or "eval_gates.py" in entries:
                ok.append("settings.json PreToolUse 含 gate-check")
            else:
                issues.append("settings.json 的 PreToolUse 沒接 gate-check——gate 防線未生效")
        except (OSError, json.JSONDecodeError) as e:
            issues.append(f"settings.json 讀不到或非法 JSON（{e}）")

    if harness in ("codex", "both"):
        config_path = os.path.join(settings_root, ".codex", "config.toml")
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            agents = config.get("agents", {})
            if not isinstance(agents, dict) or not isinstance(agents.get("code-writer"), dict):
                issues.append(".codex/config.toml 缺 code-writer 角色設定")
            elif not os.path.isfile(os.path.join(os.path.dirname(config_path), agents["code-writer"].get("config_file", ""))):
                issues.append(".codex/config.toml 的 code-writer config_file 不存在")
            else:
                ok.append("Codex 角色設定已部署")
            hooks_path = os.path.join(settings_root, ".codex", "hooks.json")
            with open(hooks_path, encoding="utf-8") as stream:
                codex_hooks = json.load(stream)
            entries = json.dumps(codex_hooks.get("hooks", {}).get("PreToolUse", []))
            if "eval_gates.py" not in entries:
                issues.append(".codex/hooks.json 的 PreToolUse 沒接 eval_gates.py")
            else:
                ok.append("Codex PreToolUse gate 已設定（仍須客戶端信任）")
            # 入口可在 .codex/config.toml 的 developer_instructions（安裝器預設）或 AGENTS.md（本 repo 自身）
            marker = "<!-- agent-workspace codex instructions -->"
            notes = config.get("developer_instructions")
            agents_md = os.path.join(settings_root, "AGENTS.md")
            in_agents = os.path.isfile(agents_md) and marker in open(agents_md, encoding="utf-8").read()
            if not (isinstance(notes, str) and marker in notes) and not in_agents:
                issues.append("Codex 流程入口未部署（.codex/config.toml developer_instructions 與 AGENTS.md 皆無 Eval Flow 區塊）")
        except (OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as e:
            issues.append(f".codex/config.toml 讀不到或非法 TOML（{e}）")

    project_skills = os.path.join(settings_root, ".agents", "skills")
    skills_dir = project_skills if harness else os.path.join(os.path.expanduser("~"), ".claude", "skills")
    repo_skills_dir = os.path.join(script_root, "skills")
    sync_ok, sync_issues = check_skills_sync(repo_skills_dir, skills_dir)
    ok.extend(sync_ok)
    issues.extend(sync_issues)

    missing = [s for s in CORE_SKILLS if not os.path.isdir(os.path.join(skills_dir, s))]
    if missing:
        issues.append(f"{skills_dir} 缺核心 skill：{', '.join(missing)}")
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

    return ok, issues


def report(ok, issues, brief=False):
    """印出 ok/issues 兩份清單，回傳 exit code（0 全過、1 有問題）。
    brief=True 時只印異常行；全綠時無任何輸出（供 SessionStart hook 內嵌呼叫的快路徑）。"""
    if not brief:
        for line in ok:
            print(f"[doctor] OK: {line}")
    for line in issues:
        print(f"[doctor] ISSUE: {line}", file=sys.stderr)
    if issues:
        if not brief:
            print(f"[doctor] {len(issues)} 個問題——修法：重跑 agent_workspace 的 ./init.sh", file=sys.stderr)
        return 1
    if not brief:
        print("[doctor] 健檢通過")
    return 0


def main():
    parser = argparse.ArgumentParser(description="部署健檢")
    parser.add_argument("--brief", action="store_true",
                         help="僅輸出異常行；全綠時無任何輸出")
    parser.add_argument("--harness", choices=("claude", "codex", "both"), default=None,
                        help="檢查指定 harness；省略時依專案配置偵測")
    args = parser.parse_args()
    ok, issues = run_checks(harness=args.harness)
    sys.exit(report(ok, issues, brief=args.brief))


if __name__ == "__main__":
    main()
