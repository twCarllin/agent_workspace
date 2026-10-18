# Eval Flow 回饋紀錄與統計

## 目標

讓新 run 的審查、驗證與 gate 回饋可追查，讓統計明確標出缺資料，並把事後 bug 連回原 run。既有 run 保持可讀。

## 現況來源

- `run_verify.py` 已記錄指令、結果、是否重用、快照及耗時；事件只寫部分欄位（`.agent-flow/scripts/run_verify.py:80-146`）。
- `stats.py` 以有歸檔 task 數作 rework 分母，缺少有效首輪資料的 task 仍入分母；gate 以訊息前 40 字分類（`.agent-flow/scripts/stats.py:313-326,409-420`）。
- gate 目前以時間與訊息首行寫入文字檔（`.agent-flow/scripts/eval_gates.py:77-88`）。
- BUGLOG 目前只有日期、模組、根因與選填 checker-passed（`retro/BUGLOG.md:1-9`）。

## 驗收

1. 新審查結果保留逐輪結果、審查者與是否通過；統計以有首輪資料者作分母，缺資料獨立計數。舊資料仍可讀，不能由最終結果推定首次結果。
2. 驗證紀錄自動保留耗時與結果。相同指令重跑時，記錄原因：輸入變更、前次失敗、使用者要求重跑或未知；未提供原因不應偽造推論。統計呈現原因與缺資料數。
3. gate 命中採固定 ID，記完整訊息、時間、run ID（若可取得）與處置；統計按 ID 彙總，舊文字行照常讀取並標為 legacy。
4. BUGLOG 條目可附原 run ID、原審查方式、漏查點及回歸測試位置；格式與記錄規則讓後續 bugfix 可照做。既有條目不改寫。
5. 新增 CLI／真實子程序路徑測試。`python3 -m unittest discover -s tests` 通過，獨立審查通過，最後由 `run_verify.py` 留證。

## 開放問題

無。沿用使用者已確認的五項改善方向；未取得的資料一律標無記錄。
