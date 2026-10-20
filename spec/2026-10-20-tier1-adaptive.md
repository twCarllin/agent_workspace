# Tier 1 依具體問題觸發審查與 HITL

## 使用者裁決與範圍

2026-10-20 使用者：「好，按照這樣執行吧」。核定上一則提案：報告格式鬆綁；
一般 Tier 1 由主 flow 選方法並以實際證據交付，驗證缺口、影響面不明或具名疑點才
派獨立 reviewer；HITL 有決策才問。權限、公開契約與難以還原的操作維持較強確認。
此裁決授權修改上述既有硬性規則，不是純文件語義保持壓縮。

本次 Tier 2：理由碼為「跨子系統協調」「公開介面／落地資料契約」。修改 manifest
契約、CLI、commit gate、item 對帳與載入文件，預估主動工時 100 分鐘。
本次自身仍依原 Tier 2 做獨立審查與測試。此核定範圍拆成 2 tasks／6 items；
不新增未經核定的產品決策，不重問同一核定問題。

## 現況與依據

- `eval_state.py:164（cmd_init_run，修改前 bb1ec55）/cmd_hitl_confirm`：新 Tier 1 先 init，再經 HITL 推進
  decomposed。`item_accounting.py:45（confirm_plan，修改前 bb1ec55）/validate_plan` 的 scope 綁 HITL 時間。
- `flow_rules.py:56（validate_credentials，修改前 bb1ec55）`、`run_evidence.py:125（check_manifest，修改前 bb1ec55）`：Tier 1／2
  仍需測試及審查四欄憑據；schema 2 的最後驗證與目前來源快照相同才可提交。
- `review_packet.py:81（collect，修改前 bb1ec55）`：writer 報告章節及每 item 的 file:line 字面格式會進 missing。
- 前次實測依據：`run/2026-10-20-flow-cost-audit/decision-evidence.json`。
  79 次 Tier 1 packet build 中，15 次只列報告章節／item 標示問題；可能仍包含真正
  缺少憑據，不能把它們全部視為無效退件。

## 新契約

### A. 新 Tier 1 的開始

1. 新 `init-run` 記 `tier1_policy: "adaptive-v1"`；舊 manifest 缺此欄時沿用舊路徑。
2. 新 `start-run RUN_ID --authorization '<使用者需求與已授權範圍>'` helper，僅適用
   adaptive Tier 1。驗 intent、task 與 item 清單後記 `plan_recorded_at`、
   `plan_authorization`，推進 decomposed，凍結 item_plan；不得偽填 hitl_confirmed_at。
   plan_authorization 是「依使用者要求開始」的紀錄，不是虛構已有人逐條確認計畫。
3. 有真正未決問題時停下請使用者裁示，仍用 `hitl-confirm` 記實際確認。該命令與
   headless 禁止偽確認的既有防線保留；adaptive 無問題的已授權工作可用 start-run。
4. item 計畫 timestamp 來源統一為共用 helper：adaptive 有 plan_recorded_at 時採它，
   否則採真實 hitl_confirmed_at。範圍變更、移除／部分交付仍需既有對帳與使用者裁示。
5. 權限、公開契約或難以還原的操作不因 adaptive 而取得額外授權；Tier 2／all-in
   不可走此捷徑。角色與寫入 gate 的 phase 判定保留。

### B. 有問題才派獨立審查

1. 預設由主 flow 實作及選驗證。需求清楚、變更可還原、驗證涵蓋主要行為時可自查。
2. 新 `require-review RUN_ID --reason '<具名原因>'` helper 讓缺口、影響面不明、
   具名疑點或使用者要求獨立審查的原因單向累加到 review_reasons，清除先前通過；
   不提供清空原因或回退自查的捷徑。也可由 start-run 的 --review-reason 建立。
3. `review-run ... --checked-by self --evidence '逐項完成度與驗證範圍' --passed` 僅
   接受 adaptive Tier 1、無 review_reasons、有效且目前來源相同的成功驗證。
   記錄為主 flow 自查，不宣稱獨立審查，也不把歷史缺資料記成自查。
4. 自查完成後綁目前來源快照；之後改檔、測試失敗、原因升級或 scope 變動時不可
   沿用通過。prepare／Git commit gate／finish 均須走同一判定，不能只在 CLI 擋。
5. 有 review_reasons 的 adaptive run 直接派 code-reviewer，一次核對 staged diff、
   原始 DoD 與實際證據；不先派 checker。必須有獨立審查者與非空證據才可通過。
   Tier 2 及舊 run 原有獨立審查要求維持。`self` 不得用於 Tier 2 的 set-review。
6. 統計／status 要明確區分 self 與獨立審查，不把 self 算 checker 升級。

### C. 報告格式鬆綁

1. packet 仍需非空原始 task、writer 報告、實際驗證命令／結果、staged 範圍與來源雜湊。
2. 不再因 writer 缺固定章節或逐 item file:line 字面格式而把 readiness 設 missing。
   不以格式齊全推定實作或覆蓋通過。獨立核對者仍按原 DoD 查逐項證據。
3. 可保留格式建議為 advisory，但不觸發模型重試或掩蓋失敗／未完成項。
4. 來源／query／index 漂移、缺測試命令／結果及未stage範圍等實質檢查保持阻擋。

## 完成條件

- 真實子程序覆蓋 start-run → 實作 → run_verify → self review → prepare → commit
  → finalize，以及 require-review 的獨立路徑；Claude 相容入口與 Codex 工具 gate 一致。
- headless 的已授權 adaptive start 可用；舊 run/Tier 2/headless hitl-confirm 不會被放寬。
- 自查後改來源／失敗驗證、缺憑據、升級原因與未結清 item 均阻擋。
- packet 等價報告可用，但缺實質證據或來源改變仍擋。
- 文件、skill 來源、角色說明、安裝輸出與代表行為情境一致；保留舊 run 相容測試，
  不刪除未受新契約取代的斷言。新預設的舊斷言依本 Spec 精確改寫。
- 最後以 `python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd
  "python3 -m unittest discover -s tests"` 留實證；獨立 code-reviewer、prepare、commit
  （Run-Id）、finalize 完成。不得宣稱已減少 token 或美元。

## 非本次範圍

不修復前次分析發現的 token_usage 重複計數、stats manifest 誤計或逾時程序樹回收；
它們不影響本次自查／人工確認政策的功能，另留待後續處理。不部署到其他專案或遠端。
