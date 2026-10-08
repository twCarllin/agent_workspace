# 循環 step 5–7：測試、收尾與回顧

5. **本地測試驗證（硬性 gate，對應 .agent-flow/ROUTER.md「部署規則」）**：依 **test-strategy** skill 執行。gate 條件＝**無新增穩定失敗**（以 `.agent-flow/scripts/test_baseline.py check` 的判定為準；baseline 於第一次 step 5 前建立單次快照既有失敗，非確定性失敗由 script 於新失敗時重跑一次確認可重現）
   - **Tier 2：新行為必須有自動化測試**（單元測試隨各實作 item 的 DoD、整合測試 item 由前置 1 分拆時建立，見 task-decomposition skill）；**Tier 1**：自動化測試或實際運行功能驗證皆可
   - `run_verify.py` 依實際驗證結果更新 `local_test_passed` 與 `local_test_evidence`；主 flow 另補仲裁、豁免等必要說明。hook 於 commit 時核對憑據。
   - **另**：本步的每一條驗證指令以 wrapper 一次完成「跑＋留痕」：`python3 .agent-flow/scripts/run_verify.py --run-id <run_id> [--sub-task <id>] --cmd "<指令>"`——Tier 2 給 `--sub-task` 記入該 sub_task；Tier 1 免給，自動記 manifest 同名欄並寫 verify_cmd 事件。底層 `add-verification` 保留，直接呼叫仍合法。
     - `verification_commands` 與測試摘要並存；提交快照的判定條件以 `SKILL.md「資料格式與操作規則」` 為準。
   - 真新失敗 → 依 skill 的處置：測試過時須記依據（無依據改弱測試視同 🔴）、肇因非本 item 走重開路徑；兩者皆非 → **立即回報使用者裁決（人是計數器，無自修額度）**，不自行空轉迴圈
   - **`[憑據:step5]` 條目在本步收口**：主 flow 逐條核對帶記號的 DoD 條目憑據已補——實跑輸出，或依 test-strategy「視覺類 DoD 的使用者驗收」路徑取得使用者裁決——未補不得通過本 gate（記號定義住 task-decomposition skill；step 3 的 checker 對這些條目只記 🔍 待驗，收口責任在此、不在審查輪）
   - 未通過本步不可進入收尾與 commit。細則（相關測試選擇、零測試專案、豁免窗口）住在 test-strategy skill，不在此重述
6. **收尾順序（**hook 強制**，見「Gate 的硬性執行」，完整清單見 `SKILL.md「Gate 的硬性執行」`）**：
   - ⓪先跑**收尾測試檢查**——範圍**分 tier**（Tier 2：全套 `--strike-key full_suite`；Tier 1：累積聯集 `--strike-key wrapup_related`，不跑全套；指令與空集合處置住 test-strategy skill「Commit 前收尾檢查與重開路徑」節，單一枚舉點、此處不重列）；本 run 的最後一條收尾驗證須由 `run_verify.py --run-id <run_id> --cmd "<收尾檢查指令>"` 執行並記錄程式樹快照。出現新失敗代表相關測試沒抓到的跨 sub_task 破壞，依 skill 的「重開路徑」把肇事 sub_task 改回 in_progress 從步驟 3 重走，**不可收尾**
   - ①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留審查記錄的永久紀錄），**清除 `eval_state.json`**（熱 scratchpad，收尾即清；失敗收尾則保留現場）。manifest 此時仍為 `in_progress`；提交前跑 `python3 .agent-flow/scripts/run_commit.py prepare <run_id>`，憑據過關後改為 `ready_to_commit` 並記下原 HEAD
   - ②**冷溯源檔的進版控範圍**（單一枚舉點，分三類）：
     - **不進版控**（只留在工作目錄、永不清除，不 `git add`）：manifest `run/<run_id>.json`、eval 歸檔檔 `run/<run_id>.eval.json`、測試 baseline `run/<run_id>.test_baseline.json`、事件日誌 `run/<run_id>.events.jsonl`、task 檔 `task/YYYY-MM-DD.md`。本次 commit 的 staged 內容＝循環 step 2 已陸續加入的**程式碼與測試檔**，此處不追加上述任何檔案
     - **進版控**：`spec/<run_id>.md`。它是 intent gate 的依據（manifest `spec_path` 指向它），且具名問題觸發 usage-analyzer／impact-analyzer 後答案寫進 Spec（見 `SKILL.md「Tier 2 完整路徑」`「具名問題觸發」節）——Spec 是本 run 需求的唯一來源，換手者必須讀得到，故隨程式碼一併 `git add`、正常 commit
     - **歷史產物**（`usage/`、`risk/`、`impact/` 三目錄）：既有歷史報告（冷溯源）保留在版控中，**不刪**；這三個目錄無新檔產生，無需 `git add`
     - **依據**：所有消費端（`eval_gates.py`／`stats.py`／`test_baseline.py`／`session_start.py`）都以 `glob("run/*.json")` 從工作目錄讀檔，無一從 git 歷史讀，故「不進版控」那組檔案進不進版控不影響任何既有功能
     - **`Run-Id: <run_id>` trailer 是硬要求**（見子項③）：`run/`／`task/` 系列溯源檔不進版控，它是 commit↔run 之間唯一的機械連結，也是 commit gate 的定位依據。漏寫 → gate 退回「工作目錄 in_progress」安全網，該次 commit 的四欄憑據不被核對（判定全貌見 `SKILL.md「Gate 的硬性執行」`）
     - baseline 的處置要求同住 `test-strategy` skill——其 `stable_failures` 是本 run 進場的既有欠帳快照；**本節與該 skill 須一致，改任一端時對照另一端**
     - **部署慣例**：工具鏈路徑（含 `run/`、`task/`、`retro/`、`CLAUDE.local.md`）由安裝器寫入 Git 的 `info/exclude`，所有 worktree 共用、不進版控，不需改目標專案的 `.gitignore`；`retro/RETRO.md` 仍隨框架部署、派工時貼進 writer prompt，同樣不進專案 commit
     - ②之前：Claude 主 flow 跑 `python3 .agent-flow/scripts/token_usage.py <run_id> --write`，由 transcript **實測**回寫 manifest `subagent_usage`（prep／loop／main）與 `token_usage` 明細（subagents＝transcript ∪ `run/<run_id>.dispatch.jsonl` 派工留痕）；Codex run 設 `harness: "codex"`，同指令記 `token_usage_status: "unknown_codex"`，不將未知用量寫成零（欄位語義住 `SKILL.md「資料格式與操作規則」`）
   - ③git commit，message 末尾附 `Run-Id: <run_id>` trailer；成功後跑 `python3 .agent-flow/scripts/run_commit.py finalize <run_id>`，核對 Git 實際提交訊息並回填 SHA、`completed`，再由工具記錄完成事件。中斷在兩者之間時，manifest 保持 `ready_to_commit`，照 resume 程序核對 HEAD 後續跑
7. **有條件** 依「派工機制」節派工 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - code-reviewer 無 🔴 → **不呼叫 retro**（reviewer 一次過即無回顧價值）
   - 本條件僅掛**升級輪**（reviewer 判定；邊界直派輪視同升級輪）——checker 通過輪與升級後零 🔴 輪都**不呼叫 retro**；升級本身是流程正常運作、不是教訓


## 標準收尾入口

執行 step 6 前，必讀 `.agent-flow/FLOW_CLI.md`「收尾」節。標準路徑使用 `flow.py finish --run-id <id> --message <訊息> --files <本次檔案> --verify-command <依 tier 選定的實際測試命令>`；只有明確要求才用 `--reuse`，只有已授權推送且明確加 `--push` 才推送。工具不推定審查通過、不自動 stage、不使用全樹 git add；測試欄位由驗證結果產生。先完成獨立審查與 step 5，再只 stage 本 run 的檔案。

此入口執行本文件 step 6 的順序與 gate，不改冷溯源檔範圍。舊 run 或入口不可用時，依上方原手動 prepare → commit（Run-Id）→ finalize 路徑執行；中斷恢復依根入口「中斷恢復」節核對現場，不重複提交。
