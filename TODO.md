# TODO — Agent Flow 改進事項

> 來源：2026-07-08 agent flow 架構檢視（基於 commit 8a06bc6 這一版）。
> 已完成節壓成一行索引（2026-09-06 清理）；細目見 git 歷史（`git log --follow TODO.md`）。

## 1. 用 hooks 把硬性 gate 落地 — ✅ 2026-07-09 完成（PreToolUse hook：gate-check.sh＋eval_gates.py，intent／測試／歸檔／不變量四 gate）

## 2. 把 Eval Flow 執行細節抽成 project skill — ✅ 2026-07-13 完成（eval-flow skill；CLAUDE.md 277→64 行）

## 3. 解決雙語文件漂移 — ✅ 2026-07-10 完成（刪英文版，中文版唯一 source of truth）

## 4. 修「commit 後回填」的慢一拍問題 — ✅ 2026-07-09 完成（commit 前歸檔；溯源改 Run-Id trailer）

## 5. 讓「測試存在」成為要求 — ✅ 2026-07-14 完成（風險分級：Tier 2 強制測試 item、Tier 1 可實跑驗證、不分 tier 驗證證據、防改弱測試 🔴）

## 6. 持續追蹤項

- [ ] **Tier 分佈統計**：manifest 已記 `tier`，跑一陣子後統計——若 Tier 1 幾乎為零，代表分級未發揮省成本作用，門檻應放寬
- [x] **RETRO.md 增長控制**：加一條「超過 N 條時，retro agent 合併同根因條目」→ 已併入第 8 節完成（retro agent 定義，N=30）
- [ ] **豁免率統計**：manifest 已記 `test_policy`，跑一陣子後統計 waive 率——比例異常升高代表豁免窗口變質為常態後門（同 tier 分佈統計的邏輯）
- [ ] **baseline 欠帳彙報**：retro 時彙報 `run/<run_id>.test_baseline.json` 的 stable_failures／flaky 數量走勢，讓記錄級欠帳看得見

## 7. 實測回饋第一輪落地 — ✅ 2026-07-15 完成（MANIFEST_RE 修正、test_lint、eval_state helper、測試綁實作 item、retro 前置、×2 校準、累積聯集、mutation self-check 制度化等十項）

## 8. 收口：retro 生產端對齊消費端 — ✅ 2026-07-15 完成（約束句式、前置進 prompt、合併規則）

## 9. 規則補洞 — ✅ 2026-07-15 完成（重開路徑不吃 strike、verify-checklist 測試存在核對、HITL 留痕）

## 10. Seed RETRO：跨專案通用約束庫 — ✅ 2026-07-15 完成（seed/RETRO.seed.md，init.sh 第 6 步部署）

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

## 13. P0 儀表板：讓系統看得見自己 — ✅ 2026-07-15 完成（stats.py、gate_hits、VERSION、doctor、docs_consistency 測試、審計欄位、去相關化驗證）

## 14. 部署 2026.07.17.2（移除 eval-scorer）到外層專案前

- [ ] 確認該專案無 in_progress 的 run（有則先收尾——舊 run 停在 scoring 依 eval-flow-resume 的相容列處置）
- [ ] 手動刪外層 `.claude/agents/eval-scorer.md` 與 `~/.claude/skills/eval-scoring/`（init.sh 只覆蓋不刪除的孤兒）

## 15. 治理規則（給維護者自己的，機制化防流程無限長大）

- [x] **規則凍結（已廢止）**：在累積下 5 個真實 run 的 stats 數據前，不新增流程規則（measurement 先於 rules；本節之後的投資應是「跑 run」不是「改 flow」）——已到期並廢止（2026-09-05，33 completed run ≥ 5，見 stats.py 輸出），由以下證據閘取代
- [ ] **eval-scorer 存廢審計**：5 個 run 後看 stats 的「scorer 獨立貢獻」——趨近 0% 則砍掉 scorer 層（全系統最大單筆成本削減候選），reviewer 結論直接驅動重跑
- [ ] **出生證制**：新流程規則須引用證據——BUGLOG／RETRO 條目（recurring 或 severe one-off）或使用者明示決策；單發 observation 留證據層不成規則（BUGLOG 兩層制從 bug 擴及所有規則來源，含 reviewer/checker catch）
- [ ] **Minimality 逐筆**：新規則附「被否決的更小替代」一句；同一規則家族第 2 次被修 → 重開設計而非就地補丁
- [ ] **修剪啟動**：stats 已點名的兩批進第一次修剪審查（細節見下方「修剪審查」條，不重列）——HITL 打回率 0%（0/33）的人閘門（降級候選；註記：33 run 幾乎全為框架自我改進 domain，外部專案未驗證，修剪保守）、從未命中的 gate
- [ ] **Game day**：故意在 step 5 中途 kill 一個 run，換乾淨 session 純照 eval-flow-resume skill 恢復——沒演練過的恢復程序等於不存在。順便驗重開路徑與升級逃生門
- [ ] **修剪審查**：每 5 個 run 看一次 gate_hits——從不觸發的 gate、打回率 0% 的 HITL、沒被 retro 前置引用過的約束條目，逐一裁決降級或刪除
- [ ] **實測選題多樣化**：下幾個 run 刻意換 domain（前端／infra／資料處理），驗證規則泛化（現有 17 條改動全來自同一 agent 同一 domain 的 n=2）
- [ ] **收斂判準**：連續 5 run 無新規則＋gate 全有命中記錄＋stats 趨勢平穩 → 框架進維護模式（框架的健康狀態是變得無聊）
