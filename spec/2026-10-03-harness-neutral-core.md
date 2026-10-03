# Harness 共用核心

## 需求
讓同一套 Eval Flow 可由 Codex 或 Claude Code 使用。共用流程、角色職責與 gate 不以任何 harness 為來源。

## 現況
init.sh 預設 Claude；install_codex.py 從 CLAUDE.md 與 .claude/agents 轉換共用流程與角色。核心 Python 放在 .claude/hooks。已安裝 .agent-flow/ROUTER.md 與 .agents/skills 副本可能落後來源。

## 設計
1. .agent-flow/ROUTER.md 是 Router 唯一來源；skills/ 是流程來源；.agent-flow/roles/ 是共用角色來源；.agent-flow/scripts/ 是核心工具來源。
2. Claude 與 Codex adapter 各自定義工具對應、hook 載荷、權限、模型、session 與 worktree 差異。共用流程只用角色名稱與能力，不要求 Claude 工具名、背景旗標或權限批准方式。
3. 安裝入口接受 --harness claude|codex|both；保留 --platform、--p 與 install_codex.py 相容入口。預設 both。兩種安裝都部署同一份核心、專案 skills 與角色契約，再產生各自設定。
4. 舊 .claude/hooks 路徑保留相容入口；不可建立第二套可獨立修改的核心。保留使用者既有 AGENTS.md、CLAUDE.md 內容與自訂 hooks。重裝不得重複 hook。
5. 新 Tier 1/2 run 均記 harness 與 evidence_schema: 2；兩種 harness 使用同一套驗證、提交與 finalize 規則。既有 run 仍可讀取。
6. 保留既有模型值與審查獨立性。未知用量仍記 unknown，不改成 0。

## 驗收
- Claude-only、Codex-only、both 在臨時 Git 專案安裝與重装均成功。
- 兩種 harness 的設定都指向共用核心；Codex 安裝不再以 Claude 檔案當流程或角色來源。
- 共用文件不要求使用 Claude Task、Bash、run_in_background 或 Claude 權限行為。
- 舊工具入口可用；自訂指令與 hook 保留；既有 run 與 gate 測試通過。
- README 說明來源、適配層、安裝、更新與相容方式。
- 最後全套測試由 run_verify.py 執行，提交後由 run_commit.py finalize 收尾。

## 開放問題與建議
建議預設安裝 both，讓使用者可切換 harness。相容入口保留，避免既有專案立即失效。此計畫等待使用者確認。

## 既有工作
TODO.md、run/gate_hits.log、run/tier0.jsonl 是進場前修改，排除本 run 的變更與提交範圍。測試若追加遙測，只視為运行記錄。

## 指南對應（2026-10-03）
來源：https://learn.chatgpt.com/guides/best-practices
- 入口保持短小，列出目錄、測試指令與完成條件；細節按需載入。
- 派工輸入統一為目標、背景、限制、完成條件。
- 複雜需求先規劃；重複工作放在單一職責 skill；並行工作隔離 worktree。
- 外部資料有實際需求才接 MCP；穩定後才考慮自動排程，本次不建立外部整合或排程。
- 保留現有模型設定；指南的模型建議不覆蓋已裁決政策。
- 驗收：兩種入口引用共用指南，來源更新後重裝能同步，入口不複製完整流程。
