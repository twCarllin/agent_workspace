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

CLI 與事件適配由 `.agent-flow/scripts/harness_adapter.py` 提供 build_argv、parse_result、normalize_hook、capabilities。CLI 回報統一為 result、session_id、usage、is_error 等欄位；錯誤輸出不得當成驗收通過。Codex CLI 無美元預算能力，成本未知記 null，執行以次数與 timeout 限制。

安裝器先在暫存區產生計畫，--dry-run 不修改目標。ownership manifest 記已安装內容雜湊；使用者修改與更新衝突時停止。可捕捉的寫入失敗會還原檔案、連結與 Git hook；斷電或強制終止不在 rollback 保證內。

驗證分兩層：本地確定性整合測試，以及 harness_smoke.py --live 的原生 CLI 證據。後者涵蓋檔案修改、hook 阻擋、測試失敗留痕與恢復定位；完整 skill 行為用 skill_eval.py 評測。CLI、帳號、模型或 trust 不可用時記 blocked，不宣稱 pass。

本地操作入口為 `python3 .agent-flow/scripts/flow.py`：`preflight` 檢查環境，`status/watch` 讀取進度，`finish` 串接既有驗證與提交。用法與能力邊界見 [FLOW_CLI.md](FLOW_CLI.md)。
