---
name: test-strategy
description: Eval Flow step 5 本地測試 gate 的執行細節：baseline「無新增穩定失敗」機制（script 判定）、flaky 過濾、失敗四分類決策樹、兩次舉手上限、相關測試選擇（累積聯集）、假測試 lint、mutation self-check、commit 前全套檢查與重開 passed sub_task 的路徑、零測試專案處置、全 tier 驗證豁免窗口。觸發語：Eval Flow 循環進入 step 5 時、「測試失敗怎麼辦」、「建測試 baseline」。不適用於：測試框架選型（Tier B bootstrap 的 HITL 決定）、eval 評分（住在 eval-scorer agent 定義）。
---

# Test Strategy（本地測試 gate 執行細節）

> 核心原則：**測試是 pipeline 的護欄，不是路障**——gate 擋的是「你新弄壞的東西」，不是「專案裡所有壞掉的東西」。gate 條件不是「全綠」，而是「**無新增穩定失敗**」。
> 判定一律由 script `.claude/hooks/test_baseline.py` 執行（baseline 比對、flaky 過濾、失敗計數都是確定性邏輯，**不留給模型憑感覺判**）；本文件規範何時跑、結果怎麼處置。

## Baseline（run 的測試基準，第一次 step 5 前建立）

```
python3 .claude/hooks/test_baseline.py baseline
```

- **全套測試指令從 manifest 的 `test_command` 讀**（single source of truth；`--cmd` 僅供覆寫）。manifest 尚無此欄時，先確認指令並寫入 manifest 再跑——不要每個 run 各猜一套，baseline 與 check 範圍不一致就會出現「無關的既有失敗」
- 預設**跑兩次**：兩次都失敗 → `stable_failures`（既有壞測試）；只失敗一次 → `flaky`。兩者之後都不擋 gate——用兩次交集換 baseline 不被 flaky 汙染
- 寫入 `run/<run_id>.test_baseline.json`（`run_id` 自動讀 `eval_state.json`）。此檔隨 commit 進 git，`stable_failures` 就是本 run 進場時的**既有欠帳快照**
- **既有壞測試 = 記錄級欠帳，不是攔截級**：與 hotfix `debt` 不同——不擋新 run、本 run 不修（修它是 scope 偏移），但 retro 時彙報數量與清單，讓債看得見
- 無任何測試框架的專案不建 baseline，改走「零測試專案」節

## 前端／UI 實機驗證的定位（best-effort，非阻塞）

> 阻塞 gate 是**功能正確性的自動化測試**（下方 step 5 的 baseline check），**不是**前端 UI 的瀏覽器實機驗證。

- **前端 UI 實機驗證屬 best-effort**：能備妥環境就做，備不妥就記 best-effort、以功能測試為準，**不阻塞收尾**。目前現況下前端實機驗證成本高、不易穩定備妥，驗證重心明確放在功能正確性
- **不從零手刻平行 runtime**：起 app 前先找專案既有的啟動把手（`start-dev.sh`／`Makefile`／`package.json` scripts），有就一鍵起（正確 port／JWT secret／DB 已內建）。沒有或起不來 → 記 best-effort，**不自訂 port／secret／DB 手搭一套平行環境**——那是鑽牛角尖，不是驗證
- **實測教訓**：一次 run 的「測試鬼打牆」全在 UI 實機環境（docker 缺、port 被 dev server 佔、JWT secret 沒帶導致 server 崩、Playwright 選擇器對不上、npx 誤裝套件 500），自動化 gate 反而一次就過。問題從來不是測試邏輯，是 UI runtime 環境——所以把力氣放在功能正確性測試，不放在前端實機

## Step 5 執行順序（每個 sub_task）

0. **行為驗證紀律**：寫任何驗證程式（含臨時 harness）前，先確認實際介面——`inspect.signature`、讀函式定義，**不憑印象寫**（實測：憑印象的 harness 連錯 5 次，每次都反證實作是對的、純浪費輪次）。驗證碼不是 throwaway：它就是本 sub_task 單元測試的草稿，直接寫進該 item 的測試檔（單元測試隨實作 item，見 task-decomposition skill）
1. **選相關測試（累積聯集）**：
   ```
   python3 .claude/hooks/test_baseline.py related --files $(python3 .claude/hooks/eval_state.py list-files)
   ```
   `--files` 餵的是**本 run 至今所有 sub_task 的 files 聯集**（`eval_state.py list-files` 直接輸出），不是只有本 item——跨 item 破壞幾乎都落在本 run 碰過的檔案輻射範圍內，累積回歸集讓破壞在**肇因 item 當場爆、歸因免費**（唯一的新變數就是現在這個 item，在循環內修即可），而不是拖到收尾全套才發現、走昂貴的重開路徑。script 用「測試檔命名慣例 + grep 引用」找；**輸出只是候選起點**，agent 要補上：本 sub_task 新寫的測試、以及改到 shared module 時自己判斷的追加範圍。寧可多選不可少選
2. **假測試 lint**（跑測試前先驗測試本身）：
   ```
   python3 .claude/hooks/test_lint.py <本 sub_task 新增/修改的測試檔>
   ```
   抓機械可辨的假測試模式：if-guard 藏斷言、無斷言測試、恆真斷言（實測：這類模式寫 60+ 測試時必然重現，retro 散文擋不住，只有 lint 擋得住）。exit 2 → 修測試；確認誤報（如「不拋例外即通過」型測試）→ 行尾加 `# testlint: allow` 並在 `local_test_evidence` 註明理由。commit 時 hook 會對 staged 測試檔再跑一次（硬防線）
3. **跑 gate 判定**：
   ```
   python3 .claude/hooks/test_baseline.py check --cmd "<相關測試指令>" --strike-key sub_task_<id>
   ```
   - exit 0（無新增穩定失敗）→ gate 通過：`local_test_passed: true`，`local_test_evidence` 填 script 輸出摘要（指令＋PASS 行＋略過的 baseline 失敗數）
   - exit 2 → 有真的新增失敗，進下方分類決策樹
4. **flaky 由 script 自動處置**：非 baseline 的失敗會自動重跑一次，重跑通過 → 判定 flaky、併入名單放行（不為它空轉）。flaky 名單累積在 baseline 檔裡，retro 時一併彙報

## Mutation self-check（整合測試 item 的 DoD 一部分，Tier 2）

測試會跑不代表斷言有效——實測靠事後補做 mutation test 才確認斷言真的抓得到破壞（sabotage 後測試真的 FAIL），此步制度化為整合測試 item 的收尾動作：

1. 挑本 task 至少 2 個**關鍵行為點**（計算邏輯、防呆條件——被弄壞會直接造成錯誤結果的那種）
2. 逐一 sabotage（改壞實作的一行）→ 跑對應測試，**必須 FAIL**；恢復原狀 → 跑測試，**必須 PASS**
3. **每次 sabotage 與恢復後清 `__pycache__`**（`find . -name __pycache__ -type d -exec rm -rf {} +`）——stale `.pyc` 會讓判定失真（實測誤判 2 個測試壞掉）
4. 任一 sabotage 沒讓測試 FAIL → 斷言無效，修測試後重做；結果（sabotage 了哪些點、FAIL/PASS 確認）記入 `local_test_evidence`

## 失敗分類決策樹（script 過濾後剩下的真新失敗才進這裡）

| 分類 | 判定 | 處置 |
|---|---|---|
| **code 錯（本 item）** | 測試斷言的是 Spec 要的行為，本 item 的 diff 沒做到 | 修 code，回循環步驟 3 |
| **肇因非本 item** | 累積聯集照出的失敗，肇因是**先前已 passed 的 sub_task**（潛伏 bug 被本 item 新測試或新路徑照到；用 `git diff --cached -- <各 sub_task 的 files>` 定位肇事者） | 走「重開路徑」重開肇事 sub_task（同 commit 前全套檢查的處置）；本 item 不動。**strike 不算本 item 的**：script 的計數不分肇因，若因此累計到 2 次觸發舉手，回報時註明肇因歸屬，由使用者裁決是否續跑 |
| **測試過時** | 測試斷言的是被 Spec **有意**改掉的舊行為 | 可更新測試，但必須在 `local_test_evidence` 註明：改了哪個測試、舊斷言為何不再成立、對應的 Spec／task 依據。**無依據的放寬斷言／刪 case／加 skip 視同 🔴**（code-reviewer 審查重點） |
| **無關的既有失敗** | 理論上不會出現（baseline 已濾）；出現代表 baseline 漏建或測試指令範圍不一致 | 檢查 baseline 是否涵蓋該測試範圍，必要時重建 baseline |
| **flaky** | script 已自動重跑過濾 | 不需人工處置；若懷疑 script 誤判（例如依時間才觸發的失敗），記錄後照「code 錯」保守處理 |

## 兩次舉手上限（防無限迴圈）

- 定義：**同一 sub_task 的 `check` 真失敗累計 2 次，不論失敗的是不是同一個測試**（最不可鑽的版本；乒乓修壞 A/B 也會被計到）。計數由 script 的 `strikes` 記錄（通過即歸零），不靠 agent 自己數
- 達 2 次 → **停止自行修復**，把「卡在哪些測試、每次試了什麼修法、為什麼沒用」回報使用者裁決。塞住時的正確行為是舉手，不是空轉

## Commit 前全套檢查與重開路徑（跨 sub_task 破壞的最後防線）

step 7 收尾**之前**（歸檔 eval_state 前）跑一次全套：

```
python3 .claude/hooks/test_baseline.py check --strike-key full_suite
```

（省略 `--cmd` → 讀 manifest 的 `test_command`，與 baseline 同源同範圍）

- exit 0 → 照常收尾
- exit 2 → 相關測試沒抓到的跨 sub_task 破壞。處置：
  1. 用 `git diff --cached -- <各 sub_task 的 files>` 定位是哪個 sub_task 的變更弄壞的
  2. **重開該 sub_task**（即使已 `passed`）：`status` 改回 `"in_progress"`、`local_test_passed` 改回 `false`、`step` 設 `"fixing"`
  3. 修正後從循環**步驟 3** 重走（review → verify → test → score 照常，不可只補測試就標回 passed）
  4. hook 的歸檔 gate 自然擋住未重過的 commit（任一 sub_task 非 passed 即擋），順序不可能被跳過

## 零測試專案

| 情況 | 處置 |
|---|---|
| 新專案 | 不會發生——Tier B bootstrap 的 DoD 硬性含測試框架＋示範測試 |
| legacy、Tier 1 | 實際運行功能驗證＋`local_test_evidence` 照填（現行規則），不強制建測試 |
| legacy、Tier 2 | **第一個 Tier 2 run 順路建框架**：分拆時第一個 task 加「建立最小測試框架＋本功能的測試」item（比照共用基礎抽前置 task 的慣例）。「最小」＝能跑單元測試＋覆蓋本次新行為，不要求 e2e、不補歷史覆蓋。建完立刻跑 `baseline`（此時 baseline 天然乾淨） |
| 連最小框架都建不起來 | 這本身就是舉手訊號：停下回報，由使用者裁決走運行驗證＋manifest 記 `debt: ["test-framework"]`（攔截級，還清前 hook 擋新 run——防「建不起來」變永久後門） |

## 驗證豁免窗口（全 tier 通則，總則住在 CLAUDE.md）

- 跳過本地驗證**僅限使用者明示豁免**；agent 不可自行認定、**不可主動建議豁免**（與 hotfix 宣告緊急同一防濫用原則）
- **豁免單次有效**：只管當次需求，不延續、不存在口頭的專案級常態豁免
- 留痕方式按 tier：
  - **Tier 1／2**：manifest 記 `test_policy: "waived_by_user"` ＋一句豁免範圍與使用者原話，隨 commit 進 git。waive 率可統計（比照 tier 分佈統計）——豁免比例異常升高是制度失效的警報
  - **Tier 0**：不為豁免建檔（維持零建檔哲學）。豁免記在 Tier 0 本來就要交付的**變更回報**裡：驗證欄寫「使用者豁免（引用原話）」。此為**弱留痕，屬有意取捨**（Tier 0 已排除高風險面，稽核價值低）
- 豁免不改變 Tier 準入條件：高風險面照樣進不了 Tier 0／1

## 硬 gate 與誠實回報的邊界（明寫取捨）

- **script 判定可稽核**：baseline 檔、strike 計數、check 結果都落在 `run/<run_id>.test_baseline.json`，事後可驗
- **hook 不重跑測試**：`eval_gates.py` 於 commit 時強制的是 `local_test_passed`／`local_test_evidence` 欄位與歸檔順序，無法驗證「失敗清單是真的」。「跑了 check 且如實記錄」這一段靠 agent 誠實＋baseline 檔留痕的事後稽核——這是已知且接受的邊界，不假裝它是硬 gate

## 適用範圍

用於 Eval Flow 循環 step 5、step 7 收尾前的全套檢查、以及任何「測試失敗怎麼處置」的判斷。不適用：
- 測試框架**選型**——Tier B bootstrap 的 HITL 由使用者決定
- 評分——`quality_score` 的 Testability 維度住在 eval-scorer agent 定義（本 skill 管「過不過」，那邊管「好不好」）
