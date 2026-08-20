# 風險分析：2026-08-20-obs-hardening

- Spec：`spec/2026-08-20-obs-hardening.md`
- 分析日期：2026-08-20（前置 1，主 flow 執行）

不適用：無（六面向皆有觸及，見下；效能、資料為 🟢 輕微）

## 1. 技術風險

- 🟡 **事件日誌旁路變主路**（Spec 2a）：append 若實作在狀態寫入之前、或未包例外處理，`events.jsonl` 目錄不可寫時會連帶弄壞所有 helper 子命令——記錄機制反而癱瘓主流程。對策：append 一律在主寫入成功**之後**執行、整段 try/except、失敗僅印 warning 不改 exit code；測試涵蓋「events 檔不可寫」情境（斷言主命令仍成功）。
- 🟡 **SessionStart／PreCompact 的 payload 格式是外部契約**（Spec 4a/4b）：兩事件的 stdin JSON 結構與 PreToolUse 不同，憑印象實作會掛。對策：實作前先查 Claude Code hooks 官方文件確認欄位；script 對解析失敗一律靜默 exit 0（hook 壞掉不可拖垮 session）；hook script 可用假 payload 直接 bash 執行測試。
  - **對策已執行（2026-08-20 查證定案）**：官方文件證實 PreCompact stdout 不進 context，原 PreCompact 構想已從 Spec 移除，改用 SessionStart matcher `startup|resume|compact`（Spec 項目 4 修訂記錄）。SessionStart payload 欄位已取得（session_id／cwd／hook_event_name 等），實作依查證結果，不再憑印象。本條風險降為已緩解。
- 🟡 **init.sh settings 合併擴充**（Spec 4c）：合併邏輯寫壞會破壞既有 PreToolUse 接線——整條 gate 防線靜默消失（比新 hook 沒接上嚴重一個量級）。對策：合併後斷言 PreToolUse 仍指向 gate-check.sh（doctor.py 既有檢查已涵蓋，DoD 綁定跑 doctor）；合併函式加單元測試（冪等：跑兩次結果相同）。

## 2. 安全風險

- 🟡 **args 值洩進事件日誌**（Spec 2a）：`set-test --evidence` 等參數含測試輸出摘要，可能夾帶外部回應體或長 blob（seed RETRO 已有「外部回應體洩進 log」前科類別）。events.jsonl 進 git，寫入即永久。對策：args 記錄採**鍵全記、值截斷**（單值 ≤200 字元，截斷加 `…[truncated]` 標記）；不記錄環境變數類內容。

## 3. 資料風險

- 🟢 無 DB。檔案層一致性：eval_state.json 缺 `run_id`（手動壞檔）時 append 無目標——對策：skip append 並 warning（旁路原則，同技術風險第一條的處置）。

## 4. 效能風險

- 🟢 events.jsonl 每 helper 呼叫 append 一行，量級可忽略。SessionStart 跑 doctor.py 增加 session 啟動延遲——對策：`--brief` 走快路徑（僅異常時輸出），實測超過 1 秒再優化。

## 5. 部署風險

- 🟡 **settings.json 變更延遲生效**（Spec 4c）：hook 接線改動要**下一次 session 載入**才生效，本 session 內無法端到端驗證 SessionStart／PreCompact 真的被觸發。對策：驗證拆兩層——script 層以假 payload 直跑驗證（本 run step 5 內完成）；接線層由 doctor.py 檢查 settings 內容正確；並在收尾回報明確告知使用者「需重載 session 生效，首次載入請驗證 hook 有跑」。
- 🟡 **目標端 `_deprecated` 殘留**（Spec 3c）：doctor.py 排除 `_deprecated` 後，外層專案已部署的舊 `~/.claude/skills/_deprecated/` 變成無人監測的殘留。對策：本 run 收尾時一次性手動清除並在回報留痕（`ls` 前後證據）；init.sh 維持「只覆蓋不刪除」語義不變。

## 6. 業務與維護風險

- 🟡 **eval_gates.py 迴歸**（Spec 1b）：commit gate 新增防刪除檢查，改壞既有判定會擋住所有正常收尾。對策：`tests/test_eval_gates.py` 既有 711 行全綠為底線（baseline gate），新 gate 加正反向測試（刪 manifest 被擋／刪歸檔檔與 baseline 檔不受影響／正常 commit 放行）。
- 🟡 **`aborted` 枚舉的隱性消費者**（Spec 1a）：status 新值可能影響 `check_other_runs`（掃 in_progress）、stats.py（status 分佈）、eval-flow-resume（掃 in_progress）。對策：逐一確認三個消費點——aborted 不得被視為 in_progress（不擋新 run、不觸發 resume）；stats 正確計入分佈；各加斷言測試。
- 🟡 **文件↔實作漂移**（全項目）：step 6 ②清單、manifest 格式節、hook 清單多處文件要同步。對策：`tests/test_docs_consistency.py` 全綠為 DoD 硬性斷言；改任一端須對照另一端（既有規則）。

## 結論

無 🔴。7 條 🟡 全部有對策，於分拆時帶入對應 item 備註。可進前置 2。
