# 風險分析 — 2026-09-06-baseline-suite-guard

> Spec: spec/2026-09-06-baseline-suite-guard.md。六面向逐一評估（task-risk-analysis skill）。

不適用：安全、資料、效能、部署

## 技術風險

- 🟡 **改動 gate 判定 script 本體**（`.claude/hooks/test_baseline.py`）：cmd_baseline／cmd_check 是 step 5 gate 的判定來源，改壞會讓所有後續 run 的測試 gate 失真。對策：Spec §3 四條測試案綁實作 item 同 diff；§4 明列範圍排除（不動 `_parse_fails` sentinel、不動 mine／related）；改動收斂在兩個函式的窄路徑（`fails == {"__suite__"}` 分支＋check 端一行警告）。
- 🟡 **重跑語義的邊界**：B1 以「第二次結果為準」——若第二次解析出個別失敗，記那些個別失敗是否正確？判定：正確（第二次是更完整的觀測；個別失敗本來就是 stable 快照的對象），Spec B1 已明文。對策：契約表含此路徑的 row（拆分者從 Spec §2 B1 第一子條推導）。
- 🟢 本檔自我測試時的遞迴面：test_test_baseline.py 測的是 script 自身，既有測試慣例已處理（隔離 run 目錄），沿用即可。

## 業務與維護風險

- 🟡 **向後場景：既有毒化 baseline 檔**：歷史 run 的 baseline 含 `__suite__` 時，B1 管不到（只作用實跑路徑）。對策：B2 的 check 端警告覆蓋沿用與歷史檔兩路（Spec §2 B2 明文）；不回改冷溯源檔（§4）。
- 🟢 輸出行為變更對既有測試的擾動：新增 stdout/stderr 行可能碰到既有測試對輸出的斷言。對策：writer 先跑 mine 確認，check 會照出。

## 結論

無 🔴。兩條 🟡 對策已內建於 Spec 的範圍排除與測試案設計，分拆時帶入對應 item 備註。可進前置 2。
