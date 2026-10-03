> 本檔由 skills/eval-flow/SKILL.md 的指向句按需載入，不單獨作為 skill 入口。流程文件（CLAUDE.md、skills、.claude/agents）一詞一義，以本表為準；「禁用變體」欄是 `tests/test_prose_lint.py` 術語 lint 的單一枚舉點——**純英數變體由 lint 機械強制**（行內 code 中的 CLI 旗標與識別字不受限），**中文變體靠審查者人審**。

# 術語表

| 正式詞 | 定義 | 禁用變體 |
|---|---|---|
| run | 一次 Tier 1／2 需求的完整執行，以 `run_id` 貫穿 manifest、task 檔、commit trailer | 工作、作業 |
| manifest | `run/<run_id>.json`，run 的冷溯源檔與憑據載體 | run 檔、清單檔 |
| task | task 檔中的一組 item；eval_state 以 task 為一筆、審查以 task 為單位 | 子任務（指 task 時） |
| sub_task | `eval_state.json` 的一筆，對應一個 task | sub-task、subtask |
| item | task 內的最小可驗收單位，帶四要素（估計行數、files、DoD、情境） | 子項、小項 |
| DoD | item 的可驗斷言清單（Definition of Done） | 驗收條件（指 DoD 時）、完成定義 |
| 契約表 | item 的行為契約表（輸入 → 可觀察效果），測試的上下限與仲裁基準 | 契約清單、行為表 |
| 退場行 | item 的 `退場:` 行，列本 item 作廢行為對應的既有測試 | 退役行、淘汰行 |
| 主 flow | 執行 eval-flow 的協調者（Claude Code 主對話或 Codex 主 session） | coordinator、主程序、主代理 |
| 主 session | 與 worktree 背景 agent 相對的那個 session 本體；只在 parallel-run／fan-out 語境使用 | 母 session、父 session |
| checker | 審查層預設位的角色名；agent 名為 `task-verifier` | 驗證員、核對員 |
| reviewer | 升級輪全 diff 審查的角色名；agent 名為 `code-reviewer` | 審查員（單獨使用時）、審核者 |
| writer | 實作角色名；agent 名為 `code-writer` | 開發者、實作者 |
| HITL | 使用者裁示閘門（human in the loop） | 人工確認、人閘（單獨使用時） |
| 理由碼 | Router 的 complexity_reasons 五碼 | 複雜度碼、分級碼 |
| 直寫捷徑 | 主 flow 不派 code-writer、自行寫 code 的路徑 | 直做、自寫 |
| 知識前置 | 派工前把 retro 條目／慣例／契約原文貼進 prompt 硬性約束區 | 知識注入、前置知識 |
| 冷溯源檔 | 留在工作目錄、永不清除、不進版控的 run 記錄（manifest、events、baseline、task 檔） | 歷史檔、溯源日誌 |
| 熱 scratchpad | `eval_state.json`，commit 後清除 | 暫存檔、工作檔 |
| 報告信封 | subagent 報告的首行戳記＋末行 `Self-check:` | 報告格式（指信封時）、信封格式 |
| 升級 | checker 四類觸發之一成立後改派 reviewer | 提升、提級 |
| 收尾 | 循環 step 6：收尾檢查、歸檔、prepare、commit、finalize | 結案、收工 |
