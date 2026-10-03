<!-- agent-workspace managed -->
# Claude Code adapter

先讀 HARNESS.md。Claude Code 入口為 CLAUDE.md，角色設定為 .claude/agents/*.md，hooks 為 .claude/settings.json。專案 .claude/skills/ 連結至 .agents/skills/，不再覆蓋個人 skills。

角色所需的讀取、搜尋、寫入、命令能力對應 Read、Grep、Glob、Write／Edit、Bash。角色可用 Task／Agent 工具；審查者只讀。PostToolUse 可檢查 agent 回報信封，主 flow 仍須檢查。

使用原生 Agent 工具時：只有使用者明示 auto-mode，writer／reviewer 才可用 run_in_background: true。未明示時以前景執行，保留 Bash 權限確認。無 Bash 需求的規劃與 retro 可背景產出，但必須等待交付與必要的 HITL gate，才可續跑。

dispatch.py 的 Claude CLI 相容路徑沿用既有 claude -p --agent 與全放行旗標。只有目前 session 已授權該方式時使用；未授權時用原生工具與目前權限。

worktree 的 tool payload cwd 由共用 _resolve_root 解析。CLAUDE_PROJECT_DIR 固定於 session 起點；不要直接用它讀 worktree 的 run。起點是 Git 子目錄的舊 Claude 路徑仍不支援 fan-out。模型由 harnesses/models.json 的 Claude 設定產生。用量解析僅適用 Claude transcript；session_id/config_dir 的環境變數細節屬此適配層。SessionStart 透過 AGENT_FLOW_HARNESS=claude 明示 harness。

## Claude worktree 相容限制

使用原生 Agent 工具時，worktree 由 isolation: worktree 建立，啟動時釘定 cwd。不得從 repo root 啟動後才叫 agent 進 worktree，EnterWorktree 會拒絕；不得以 cd 代替工具 cwd 隔離（R-005）。branch 名由 harness 提供，回報須附實際名稱。

原生 worktree 起點使用 .claude/settings.json 的 worktree.baseRef: head，含本地未 push commit。設定未套用時可能退回 origin 而落後；共用 parallel-run 的起手同步與驗證步驟不可移除。主 session 須在 main，避免其他 branch 的未合併工作進入批次。
