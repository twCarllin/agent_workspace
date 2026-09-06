# Spec — baseline `__suite__` 毒化修復（套件層失敗的重跑確認＋失明警告）

> run_id: 2026-09-06-baseline-suite-guard。本 Spec 自足：不依賴對話上下文，引用檔案以路徑＋行號指向。
> 工作型態：bugfix（診斷先行已完成，本 Spec 由診斷結論擴寫）。改動標的為循環 step 5 測試 gate 的判定 script 本體（`.claude/hooks/test_baseline.py`）——可執行邏輯＋高風險機制本體同時成立 → Tier 2。
> 修法方向已經使用者確認（2026-09-06：「baseline 遇 rc≠0 且無可解析失敗時比照 check 重跑一次確認，或至少大聲警告」——本 Spec 兩者都做）。

## 1. 背景與診斷結論

- **現象**（2026-09-06 checker 首戰 game day 實測）：目標專案的全套測試指令在本機約半數執行出現**暫時性非零退出**；baseline 一次執行就把 `__suite__` 記入 `stable_failures`，使用者重建三次才取得乾淨 baseline。
- **根因**：`.claude/hooks/test_baseline.py` 的 `_parse_fails()`（:58-64）在 rc≠0 且無任何可解析個別失敗時記 sentinel `__suite__`（設計正確——check 端靠它抓全套崩潰）；但 `cmd_baseline()`（:143-181）**單次執行即快照、無重跑確認**——與 `cmd_check()` 對新失敗的惰性重跑確認（:197-203）不對稱，暫時性套件層失敗被永久記為 stable。
- **影響面**：`__suite__` 進入 `stable_failures` 後，`cmd_check()` 的 `new = fails - known` 把**任何**「全套崩潰且無個別失敗可解析」的後續情況靜默扣除——gate 對全套層級失敗永久失明，且無任何警告。`find_reusable_baseline()`（:121-140）會把毒化的 baseline 沿用給同 HEAD 的後續 run，失明面跨 run 傳染。
- **性質判定**：`__suite__` 只會單獨出現——`_parse_fails` 僅在「解析不出任何個別失敗」時記入，故 `fails` 含 `__suite__` ⟺ `fails == {"__suite__"}`（實作可依此簡化判斷）。

## 2. 行為變更（契約層）

- **B1 baseline 重跑確認**：`cmd_baseline` 實跑路徑（非沿用路徑）取得 `fails == {"__suite__"}` 時，重跑一次：
  - 第二次結果**不含** `__suite__` → 以第二次的 `fails` 為 `stable_failures`（暫時性套件層失敗不記錄；第二次若解析出個別失敗則照記那些個別失敗），stdout 印一行說明「套件層非零退出未重現，以重跑結果為準」
  - 第二次**仍含** `__suite__` → 照記（環境真的壞，記錄是事實），但 stderr **大聲警告**：baseline 含 `__suite__`，gate 將對全套層級失敗失明，建議修環境後 `--fresh` 重建
  - 只在 `__suite__` 場景重跑；個別可解析失敗照舊單次快照（被否決的更大替代：所有失敗都重跑——成本 ×2，且 stable 個別失敗本來就不擋 gate、毒化面不同）
- **B2 check 端失明警告**：`cmd_check` 讀入 baseline 後，`stable_failures` 含 `__suite__` → 印一行警告（提示本次判定對全套層級失敗失明），**不改變判定邏輯與 exit code**。此警告同時覆蓋「沿用毒化舊 baseline」的路徑（B1 管不到沿用），與既有毒化檔的向後場景。
- **B3 文件同步**：`skills/test-strategy/SKILL.md` baseline 節補一句行為描述（`__suite__` 重跑確認＋失明警告），指向式、不重述實作細節。

## 3. 測試（契約素材，供拆分者推導契約表）

`tests/test_test_baseline.py` 補案（沿該檔既有測試慣例）：
1. 暫時性套件失敗：首跑 rc≠0 且無可解析失敗、重跑 rc=0 → `stable_failures` 不含 `__suite__`
2. 可重現套件失敗：兩次皆 rc≠0 無可解析 → `stable_failures` 含 `__suite__`，且警告輸出含失明提示
3. check 失明警告：baseline 檔含 `__suite__` → check 輸出含警告字樣，exit code 行為不變（無新失敗仍 0）
4. 邊界：首跑 rc≠0 但可解析出個別失敗 → 不重跑（執行次數 1），單次快照照舊

## 4. 範圍排除

- 不改 `_parse_fails` 的 sentinel 設計本身（check 端依賴它抓全套崩潰，是正確防線）
- 不改 `mine` 路徑與 `related` 路徑（與 baseline 快照無關）
- 不做「所有失敗都重跑」（見 B1 括號）
- 不回填清理歷史 run 的毒化 baseline 檔（冷溯源不回改；後續 run 由 B2 警告現形）

## 5. 非功能

- baseline 最壞情況多跑一次全套（僅 `__suite__` 場景）；正常路徑零額外成本。B2 為純輸出行，零成本。
