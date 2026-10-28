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

Codex 的 AGENTS.md 管理區段與 `.codex/config.toml` developer_instructions、Claude 的 CLAUDE.local.md 是簡短入口（本 repo 自身為 AGENTS.md 與 CLAUDE.md）。安裝器保留專案 AGENTS.md 的其餘文字；Codex 專案設定未載入時，AGENTS.md 仍提供 Router 入口。安裝器由共用角色產生 .codex/agents/ 與 .claude/agents/，不以其中一方產生另一方。生成設定的修改應回到共用來源；自訂角色檔由安裝器保留並回報。

新 Tier 1／2 manifest 記 harness: claude 或 codex 與 evidence_schema: 2。舊 manifest 缺 harness 時沿用 Claude 相容行為。兩者都以 run_verify.py 記錄最後驗證，以 run_commit.py prepare、commit、finalize 收尾。

派工可用目前 harness 的角色工具，或 dispatch.py CLI 適配層。交付契約、獨立審查、信封檢查與狀態順序相同。工具 hook 支援範圍依 harness 設定；Git commit-msg hook 核對實際提交訊息。不能把設定已生成當作 hook 已啟用的證據。

並行執行須有獨立 Git worktree、index、run manifest 與已啟用 gate。無法滿足時改為循序執行。權限與背景方式由目前 harness 適配層決定；流程本身不授予額外權限。

舊 .claude/hooks/ 使用相對連結指向共用核心。新增指令使用 .agent-flow/scripts/。

共用核心的相依方向：CLI 與 hook → 證據讀取服務 → 純規則。`flow_rules.py` 定義共用判準與 `RuleViolation`，不讀寫檔案、不輸出訊息、不退出程序；`run_evidence.py` 讀取 manifest、歸檔與驗證快照，使用純規則檢查。兩者均不引用 hook 模組。一般 CLI 直接使用共用核心，`eval_gates.py` 保留相容入口並將規則例外轉為原有 BLOCK 訊息與退出碼。平台 hook 的解析與攔截責任維持在適配層。

CLI 與事件適配由 `.agent-flow/scripts/harness_adapter.py` 提供 build_argv、parse_result、normalize_hook、capabilities。CLI 回報統一為 result、session_id、usage、is_error 等欄位；錯誤輸出不得當成驗收通過。Codex CLI 無美元預算能力，成本未知記 null，執行以次数與 timeout 限制。

呼叫端明確指定的選項，適配層須按其語義執行或在執行前明確拒絕，指出選項與原因；不得靜默忽略或替換。能力宣告與執行檢查使用同一判準。平台支援、設定已存在與目前 session 已生效分開表示，未知不得記為已支援或已啟用；未知狀態沿用既有處置，不一律增加阻擋。

安裝器先在暫存區產生計畫，--dry-run 不修改目標。ownership manifest 記已安装內容雜湊；使用者修改與更新衝突時停止。可捕捉的寫入失敗會還原檔案、連結與 Git hook；斷電或強制終止不在 rollback 保證內。安裝器把工具鏈路徑（含 `run/`、`task/`、`retro/`、`CLAUDE.local.md`）寫入 Git 的 `info/exclude`，所有 worktree 共用、不進版控；Claude 入口區塊寫入 `CLAUDE.local.md`，Codex 入口區塊寫入 `.codex/config.toml` 的 developer_instructions，不改寫專案 CLAUDE.md 與 AGENTS.md。Codex hook 與 Git commit-msg hook 從主工作區（Git 共用目錄的上層）執行腳本，尚未建立連結的 worktree 也能執行。

驗證分兩層：本地確定性整合測試，以及 harness_smoke.py --live 的原生 CLI 證據。後者涵蓋檔案修改、hook 阻擋、測試失敗留痕與恢復定位；完整 skill 行為用 skill_eval.py 評測。CLI、帳號、模型或 trust 不可用時記 blocked，不宣稱 pass。

本地操作入口為 `python3 .agent-flow/scripts/flow.py`：`preflight` 檢查環境，`status/watch` 讀取進度，`finish` 串接既有驗證與提交。用法與能力邊界見 [FLOW_CLI.md](FLOW_CLI.md)。

新 Tier 1 採 `adaptive-v1`，依 `skills/eval-flow/references/tier1.md` 決定開始、主 flow 自查或獨立審查。Tier 2 仍直接派 reviewer；舊 Tier 1 保留 checker 相容路徑。資料包只供資料與來源核對，不因固定報告章節退件，也不代表審查通過；用法見 [REVIEW_PACKET.md](REVIEW_PACKET.md)。

2026.10.19.1 起的新 Tier 1／2 run 加入 item 對帳。開始時固定 `item_plan`（adaptive 依已授權需求，其餘依 HITL），
逐 item 記 `item_results`；prepare／commit gate 核對 staged 路徑，finalize 核對
實際 commit SHA 與檔案。未結清 item 須暫停；使用者接受部分交付時終態為
`partial`，不得標為 `completed`。舊 manifest 沿用原版本契約。
欄位與命令見 [FLOW_CLI.md](FLOW_CLI.md#item-交付對帳)。
