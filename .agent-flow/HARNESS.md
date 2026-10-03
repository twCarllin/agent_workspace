<!-- agent-workspace managed -->
# Harness 契約

共用流程不指定模型、工具名稱或權限機制。執行前讀取目前 harness 的適配層：Claude Code 用 CLAUDE_ADAPTER.md；Codex 用 CODEX_ADAPTER.md。

| 共用來源 | 用途 |
|---|---|
| .agent-flow/ROUTER.md | 分級與工作入口 |
| skills/ → .agents/skills/ | 按任務載入的流程 |
| .agent-flow/roles/ | 角色職責與交付契約 |
| .agent-flow/scripts/ | gate、狀態、驗證與派工核心 |
| .agent-flow/harnesses/models.json | 各 harness 的模型與角色設定 |

AGENTS.md 與 CLAUDE.md 是簡短入口。安裝器由共用角色產生 .codex/agents/ 與 .claude/agents/，不以其中一方產生另一方。生成設定的修改應回到共用來源；自訂角色檔由安裝器保留並回報。

新 Tier 1／2 manifest 記 harness: claude 或 codex 與 evidence_schema: 2。舊 manifest 缺 harness 時沿用 Claude 相容行為。兩者都以 run_verify.py 記錄最後驗證，以 run_commit.py prepare、commit、finalize 收尾。

派工可用目前 harness 的角色工具，或 dispatch.py CLI 適配層。交付契約、獨立審查、信封檢查與狀態順序相同。工具 hook 支援範圍依 harness 設定；Git commit-msg hook 核對實際提交訊息。不能把設定已生成當作 hook 已啟用的證據。

並行執行須有獨立 Git worktree、index、run manifest 與已啟用 gate。無法滿足時改為循序執行。權限與背景方式由目前 harness 適配層決定；流程本身不授予額外權限。

舊 .claude/hooks/ 使用相對連結指向共用核心。新增指令使用 .agent-flow/scripts/。
