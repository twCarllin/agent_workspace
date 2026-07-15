# TODO — Agent Flow 改進事項

> 來源：2026-07-08 agent flow 架構檢視（基於 commit 8a06bc6 這一版）。
> 建議執行順序：#2 → #4 → #3，#1 可隨時獨立進行。

## 1. 用 hooks 把硬性 gate 落地（最大槓桿）— ✅ 2026-07-09 完成

以 PreToolUse hook 實作（`.claude/hooks/gate-check.sh` + `eval_gates.py`，設定於 `.claude/settings.json`，隨 init.sh 部署）：

- [x] 檢查 `run/<run_id>.json` 存在且 `spec_path`／`spec_inline` 至少一個非空（intent gate）
- [x] 確認測試指令已執行且通過（`local_test_passed` 欄位，對應循環步驟 5 的本地測試 gate）
- [x] 擋住 `eval_state.json` 尚存在時的 commit（防跳過歸檔）
- [x] 追加：eval 歸檔檔不變量驗證（扣分總和 = 10 − score、run_id 一致）

## 2. 把 Eval Flow 執行細節抽成 project skill — ✅ 2026-07-13 完成

CLAUDE.md 每個 session 全文載入，但約七成內容（前置 0–3、循環 1–8、兩個 JSON schema、操作規則）只在實際執行 Tier 2 run 時需要。

- [x] 新建 `eval-flow` skill，承載流程執行細節（含 Tier 1 精簡路徑、manifest／eval_state 格式、gate 清單、中斷恢復指引）
- [x] CLAUDE.md 只留：部署規則、Router 分級表、防濫用規則、「判為 Tier 1/2 → 載入 eval-flow skill 執行」的指引（另保留 Task Principle 等一般性原則），277 行 → 64 行
- 效果：常駐 context 變小、按需載入時遵循率更高、漂移面縮小（與 task-decomposition skill 同一原則）

## 3. 解決雙語文件漂移（做個決定）— ✅ 2026-07-10 完成

`CLAUDE.eng.md` 曾落後中文版好幾代而無人發現；兩份手工維護的等價文件必然漂移。三選一：

- [x] (a) 刪除英文版（推薦——若無明確讀者，僅是維護成本）→ 採用，`CLAUDE.eng.md` 與 `CLAUDE.gl.md` 皆已刪除，中文版為唯一 source of truth
- ~~(b) 明定中文版為唯一 source of truth，英文版標「generated, do not edit」、由同步指令產生~~
- ~~(c) 只留英文版~~

## 4. 修「commit 後回填」的慢一拍問題 — ✅ 2026-07-09 完成

改為 commit 前歸檔：評分通過 → 歸檔 eval_state、manifest 標 `completed` → 才 commit，同批進 git。`commit_sha` 欄位移除，溯源改用 commit message 的 `Run-Id: <run_id>` trailer（`git log --grep` 反查）。順序由 hook 強制（見 #1）。

## 5. 讓「測試存在」成為要求，closing the loop — ✅ 2026-07-14 完成（採風險分級，非一刀切）

循環步驟 5 允許「無測試框架時實際運行驗證」——專案只要一直沒測試，gate 就一直走後門。討論後決定不強制全面測試（測試斷言過細會跟不上程式碼變化），改為風險分級：

- [x] **Tier 2**：引入新行為的 task 強制含測試 item（task-decomposition skill 硬性要求＋task-reviewer 把關），step 5 必須跑測試
- [x] **Tier 1**：維持自動化測試或實際運行驗證皆可（高風險面已被 Router 排除）；Tier 0 不變
- [x] **不分 tier 補「驗證證據」**：step 5 須在 eval_state 記 `local_test_evidence`（指令＋結果摘要），hook 於 commit 時強制非空
- [x] **防改弱測試**：既有測試失敗先分類（code 錯 vs 測試過時）；無 Spec/task 依據的放寬斷言／刪 case／加 skip，code-reviewer 視同 🔴

## 6. 持續追蹤項

- [ ] **Tier 分佈統計**：manifest 已記 `tier`，跑一陣子後統計——若 Tier 1 幾乎為零，代表分級未發揮省成本作用，門檻應放寬
- [x] **RETRO.md 增長控制**：加一條「超過 N 條時，retro agent 合併同根因條目」→ 已併入第 8 節完成（retro agent 定義，N=30）
- [ ] **豁免率統計**：manifest 已記 `test_policy`，跑一陣子後統計 waive 率——比例異常升高代表豁免窗口變質為常態後門（同 tier 分佈統計的邏輯）
- [ ] **baseline 欠帳彙報**：retro 時彙報 `run/<run_id>.test_baseline.json` 的 stable_failures／flaky 數量走勢，讓記錄級欠帳看得見

## 7. 實測回饋第一輪落地 — ✅ 2026-07-15 完成（未 commit）

來源：另一 agent 跑完整 flow 的七條結構性回饋（詳見 memory / git log）。

- [x] `eval_gates.py` MANIFEST_RE 誤擋 `run/<id>.test_baseline.json` 修正（排除規則寫進 pattern 本身），根因記入 `retro/RETRO.md`
- [x] 新增 `test_lint.py` 假測試 AST lint（if-guard 藏斷言／無斷言／恆真斷言；`# testlint: allow` 豁免）：test-strategy step 5 ＋ commit gate 4 雙防線
- [x] 新增 `eval_state.py` helper（init／set-step／set-files／set-test／set-status／append-round／list-files／archive，寫入前驗不變量），eval-flow 規定不再手動 Edit
- [x] 2(a) 設計反轉：單元測試綁進實作 item 的 DoD（同 writer 同 diff），整合測試 item 只做跨 item 驗證＋ mutation self-check（task-decomposition 全面改寫）
- [x] retro 前置：主 flow 把 RETRO.md 相關條目原文貼進 writer prompt 硬性約束區（eval-flow 循環 step 1 硬性步驟）
- [x] 行數估算 ×2 校準（naive 粗估系統性低估 2–3 倍；估算含 docstring／錯誤路徑／常數表／測試）
- [x] step 5 相關測試改「本 run 全部 sub_task files 累積聯集」（跨 item 破壞在肇因 item 當場爆、歸因免費；收尾全套保留為輻射範圍外兜底）
- [x] mutation self-check 制度化為整合測試 item DoD（sabotage 須 FAIL、恢復須 PASS、每次清 `__pycache__`）
- [x] review-checklist 加「關鍵資料流至少實跑一次」
- [x] harness 紀律：寫驗證程式前先 `inspect.signature`，驗證碼落成該 item 測試不丟棄（test-strategy step 0）

## 8. 收口：retro 生產端對齊消費端 — ✅ 2026-07-15 完成

第 7 節把 retro 消費改成「前置貼 prompt 約束區」，但生產端三處還是舊模型，會持續產出貼不進 prompt 的散文：

- [x] `report-format` skill 的「Retro 記錄」模板改為**約束句式**（背景一句＋約束一句，格式同 `retro/RETRO.md` 檔頭說明），廢除敘事型表格＋教訓段落
- [x] `retro` agent 定義：產出改約束句式；定位從「供 code-writer 參考」改為「供主 flow 前置進 writer prompt」；加合併規則「超過 N 條時合併同根因條目」（吸收第 6 節的 RETRO.md 增長控制，該項就地完成）
- [x] `code-writer` agent 定義：刪「讀取 retro/RETRO.md」步驟，改為「以 prompt 硬性約束區的 retro 條目為準，不自行通讀」（實測證明通讀無效且浪費 token）

## 9. 規則補洞 — ✅ 2026-07-15 完成

- [x] test-strategy 失敗分類決策樹加分支：累積聯集下，失敗**肇因非本 item**（前面已 passed 的 item 潛伏 bug 被照到）→ 走重開路徑重開肇事 sub_task，**不吃本 item 的 strike**
- [x] `task-verify-checklist` 加：逐 item 核對「DoD 宣稱的測試真的存在、涵蓋宣稱的 case」（O2／O7 型覆蓋缺口的檢查點）
- [x] HITL 留痕：usage 確認／Tier 1 輕量確認時，manifest 記 `hitl_confirmed_at` ＋確認範圍一句話（resume／換手時可驗證 gate 真的過過，不只信 phase 欄位）

## 10. Seed RETRO：跨專案通用約束庫 — ✅ 2026-07-15 完成（seed/RETRO.seed.md，init.sh 第 6 步部署）

RETRO.md 是 per-project，但實測的 🔴 全是通用類別（外部回應體洩進 log／reason、cache-hit 重打付費 API、rate-limit、假測試）。新專案 RETRO 是空的，同類錯誤每個專案重付學費。

- [x] 整理通用約束庫作為 seed RETRO（約束句式），init.sh 部署到目標專案（專案自己的條目往下累積）
- [x] 來源：本 repo `retro/RETRO.md` ＋實測回饋中列舉的可預測 🔴 類別

## 11. Tier 1 並行的 script driver（等 parallel-run 實戰後）

構想：確定性 driver（`parallel_run.py`）＋每 worktree 一個完整 headless agent session。分層原則——順序編排、worktree 生命週期、初始化、狀態輪詢、彙整是機械 → script；判級、HITL、循環內判斷（🔴／失敗分類／升級逃生門）留在 agent session 內。session-per-worktree 讓 hook 防線原封不動（settings.json 隨 worktree 部署）。

- [ ] **前提**：先照 parallel-run skill 手動跑一次真實並行，拿到「哪些步驟真機械、模型在哪出錯」的實測資料，才動工（不重演制度超前於使用量）
- [ ] 先行低風險項（可先做）：worktree 開設／收拾＋批次 manifest／eval_state 初始化的小 script（純機械、單獨可測，手動並行時就能用）
- [ ] driver 設計要點（實戰後定案）：吃「已批次 HITL 確認」的需求清單才啟動；headless 權限靠 allowedTools 白名單（git／測試指令／既有 script），不可全放行；輪詢見 manifest `tier` 翻 2 或 `status: failed` → 凍結該 worktree、彙報標紅；merge 一律回主 session HITL
- [ ] **不採用**的路徑（已評估）：編排層直接 spawn 流程管制的 subagent（Workflow／背景 Task）——會繞過 PreToolUse hook 防線，且背景 Bash 批准問題已有前案

## 12. 觀察項（等實測資料，不先動）

- [ ] ×2 估算校準是否過矯——下輪 run 用「估算 vs 實際」回歸
- [ ] 2(a) 後 item 間測試檔共用變多 → [P] 機會變少；先靠「每 item 獨立測試檔」慣例，實測受限再加規則
- [ ] 累積聯集在長 run 的 step 5 時長線性成長——實測嫌慢再分層（如聯集超 N 檔時只跑本 item ＋上輪失敗過的）
- [ ] mutation self-check 要不要 script 化（`test_baseline.py mutate`：sabotage→跑→恢復→跑→清 pycache 的機械序列）——等第一次實際執行的體感再決定

## 13. P0 儀表板：讓系統看得見自己 — ✅ 2026-07-15 完成

來源：L6 視角檢視——系統最大風險是「看不見自己」＋「每次失敗反射性加規則」。measurement 先於一切優化。

- [x] `stats.py`：掃 `run/` 彙總 tier 分佈、waive 率、HITL 打回率、rework 率、scorer 獨立貢獻、扣分維度分佈、baseline 欠帳走勢、gate 命中
- [x] gate 命中日誌：`eval_gates.py` 攔截時 append `run/gate_hits.log`（僅 hook 模式、run/ 已存在時；從不觸發的 gate 是修剪候選）
- [x] 框架版本化：`.claude/hooks/VERSION`＋manifest 記 `framework_version`（鑑識「哪一版規則下跑的」）
- [x] `doctor.py` 部署健檢：hooks 齊全可編譯、settings 接上 gate-check、核心 skill 已部署、retro 存在、殘留 eval_state 提示
- [x] 文件一致性測試（`tests/test_docs_consistency.py`）：hook script 引用存在、skill 引用存在、agent frontmatter skills 存在、helper 子命令文件↔實作一致、gate 編號區間↔清單一致（防這輪抓到的那類漂移）
- [x] 審計資料欄位：manifest `hitl_rejections`、round `review_reds`（scorer 獨立貢獻審計的資料來源）
- [x] 去相關化驗證：code-reviewer 改 opus-4-8（與 writer 的 sonnet 異質；同顆腦互審抓不到共同盲點，亦符合「審查→強 model」原則）

## 14. 治理規則（給維護者自己的，機制化防流程無限長大）

- [ ] **規則凍結**：在累積下 5 個真實 run 的 stats 數據前，不新增流程規則（measurement 先於 rules；本節之後的投資應是「跑 run」不是「改 flow」）
- [ ] **eval-scorer 存廢審計**：5 個 run 後看 stats 的「scorer 獨立貢獻」——趨近 0% 則砍掉 scorer 層（全系統最大單筆成本削減候選），reviewer 結論直接驅動重跑
- [ ] **Game day**：故意在 step 5 中途 kill 一個 run，換乾淨 session 純照 eval-flow-resume skill 恢復——沒演練過的恢復程序等於不存在。順便驗重開路徑與升級逃生門
- [ ] **修剪審查**：每 5 個 run 看一次 gate_hits——從不觸發的 gate、打回率 0% 的 HITL、沒被 retro 前置引用過的約束條目，逐一裁決降級或刪除
- [ ] **實測選題多樣化**：下幾個 run 刻意換 domain（前端／infra／資料處理），驗證規則泛化（現有 17 條改動全來自同一 agent 同一 domain 的 n=2）
- [ ] **收斂判準**：連續 5 run 無新規則＋gate 全有命中記錄＋stats 趨勢平穩 → 框架進維護模式（框架的健康狀態是變得無聊）
