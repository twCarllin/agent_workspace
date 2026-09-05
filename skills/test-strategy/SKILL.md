---
name: test-strategy
description: Eval Flow step 5 本地測試 gate 的執行細節：baseline「無新增穩定失敗」機制（script 判定，單次跑快照既有失敗）、真失敗即回報使用者（人是計數器）、相關測試選擇（累積聯集）、假測試 lint、mutation self-check、commit 前全套檢查與重開 passed sub_task 的路徑、零測試專案處置、全 tier 驗證豁免窗口。觸發語：Eval Flow 循環進入 step 5 時、「測試失敗怎麼辦」、「建測試 baseline」。不適用於：測試框架選型（Tier B bootstrap 的 HITL 決定）。
---

# Test Strategy（本地測試 gate 執行細節）

> 核心原則：**測試是 pipeline 的護欄，不是路障**——gate 擋的是「你新弄壞的東西」，不是「專案裡所有壞掉的東西」。gate 條件不是「全綠」，而是「**無新增穩定失敗**」。
> 判定一律由 script `.claude/hooks/test_baseline.py` 執行（baseline 比對、重跑確認可重現都是確定性邏輯，**不留給模型憑感覺判**）；本文件規範何時跑、結果怎麼處置。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Baseline（run 的測試基準，第一次 step 5 前建立）

```
python3 .claude/hooks/test_baseline.py baseline
```

- **全套測試指令從 manifest 的 `test_command` 讀**（single source of truth；`--cmd` 僅供覆寫）。manifest 尚無此欄時，先確認指令並寫入 manifest 再跑——不要每個 run 各猜一套，baseline 與 check 範圍不一致就會出現「無關的既有失敗」
- **跑一次**：所有失敗記為 `stable_failures`（進場既有壞測試，之後不擋 gate）。非確定性（flaky）失敗不在 baseline 階段預先分類——scoped 測試架構下每輪跑的測試面積小、噪音低，改由 check 在**出現新失敗時**才重跑一次確認可重現（惰性驗證，成本只在有訊號時付）
- **自動沿用**：既有 baseline 檔中存在「`head_sha` == 目前 HEAD 且 cmd 相同」者 → script 直接沿用其 `stable_failures`（baseline 記的是**進場 HEAD 的既有失敗快照**，同進場 HEAD 即可沿用、免重跑全套；本 run 工作樹的新變更由 check 把關）；測試環境變了但 HEAD 沒變時用 `--fresh` 強制重建
- 寫入 `run/<run_id>.test_baseline.json`（`run_id` 自動讀 `eval_state.json`）。此檔隨 commit 進 git，`stable_failures` 就是本 run 進場時的**既有欠帳快照**
- **既有壞測試 = 記錄級欠帳，不是攔截級**：與 hotfix `debt` 不同——不擋新 run、本 run 不修（修它是 scope 偏移），但 retro 時彙報數量與清單，讓債看得見
- 無任何測試框架的專案不建 baseline，改走「零測試專案」節

## Writer 層 mine 模式（code-writer 內迴圈的測試範圍）

```
python3 .claude/hooks/test_baseline.py mine --strike-key <sub_task 標識>
```

- **用途與分工**：code-writer 自驗**只准**用 mine——只跑自己未提交變更範圍內的測試檔；step 5 的 `check`（累積聯集＋baseline 扣除）是主 flow 的事。失敗歸因不留給弱 model：mine 範圍內的失敗全屬呼叫者（不做 baseline 扣除），範圍外的歸因由 script 與主 flow 仲裁
- **範圍推導原理**：每 sub_task 結尾 commit ⇒ writer 開工時樹乾淨 ⇒ 當下 git 未提交變更（staged＋unstaged＋untracked）全屬該 writer，其中的測試檔即其管轄範圍——機械推導，零判斷
- **抓不到的破壞是 by design**：writer 改 source 弄壞既有測試但沒碰測試檔時 mine 不會抓到——這類失敗由 step 5 的 check 現形（baseline 在其開工前是乾淨的，歸因必然準確），主 flow 拿具體失敗清單回派修正
- **`[P]` item 的 mine 模式均適用**：`[P]` item 在 fan-out（各開 worktree，隔離樹）或門檻不足的循序退回（逐個執行）下，mine 範圍推導**均成立**（未提交變更只屬當前 item）；兩路徑均無多 writer 並發共樹，舊「指定測試檔清單」workaround 不再需要
- **執行留痕（震盪稽核）**：mine 每次執行 append 一筆到 `run/<run_id>.mine_log.json`（seq、strike_key、失敗集合、測試檔內容 hash），script 端零 token。writer 交付時主 flow 對照工作報告的「仲裁記錄」稽核：執行次數異常多＋測試檔 hash 在失敗未清時反覆變動＋失敗集合遊走＝「改測試湊綠」的機器指紋（震盪在最終 diff 裡是隱形的，只有這裡照得出來）。此檔為熱 scratchpad，收尾隨 eval_state 清除、不進 git
- writer 端的行為約束（先實作後測試、範圍外失敗照抄不修、仲裁三選一先判再動手、2 次上限帶失敗交付）住在 `.claude/agents/code-writer.md` 的「測試管轄規則」節，不在此重述

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
   - 本步跑過的每一條驗證指令另以 `add-verification` 逐條記入 `verification_commands`（純記錄、無 gate；與 `local_test_evidence` 並存，語義與操作見 `eval-flow` skill，此處不重述）
   - exit 2 → 有真的（可重現）新增失敗，進下方分類決策樹
4. **非確定性失敗由 script 自動放行**：非 baseline 的新失敗會自動重跑一次確認可重現——重跑通過（不可重現）→ 印警示「非確定性失敗，未阻擋」、不擋、**不持久化任何名單**；重跑仍失敗（可重現）→ 真新失敗，script append 一筆 `failure_log`（供稽核「紅過就有痕」）並 exit 2

## Mutation self-check（每 run 抽樣一次，Tier 2）

測試會跑不代表斷言有效——實測靠事後補做 mutation test 才確認斷言真的抓得到破壞（sabotage 後測試真的 FAIL），此步制度化為整合測試 item 的收尾動作。

**執行頻率：每 run 抽一個整合測試 item 做完整版（含下方第 6 步的主 flow 獨立重放），其餘整合測試 item 的 `local_test_evidence` 記「沿用本 run mutation 結論（抽樣 item：<id>）」即可**——斷言鑑別力是同一個 run 內測試撰寫習慣的性質，item 間高度相關，逐個重做的邊際資訊低。抽樣對象取**斷言最密集或行為點最關鍵的那個** item（不是最先做完的那個）。

**抽樣不適用、須逐個做完整版的情況**：抽樣 item 的 sabotage 出現任一沒讓測試 FAIL（代表本 run 的斷言品質不可信，不能外推）；或各整合測試 item 由不同 code-writer 產出、撰寫習慣不同源。

1. 挑本 task 至少 2 個**關鍵行為點**（計算邏輯、防呆條件——被弄壞會直接造成錯誤結果的那種）
2. 逐一 sabotage（改壞實作的一行）→ 跑對應測試，**必須 FAIL**；恢復原狀 → 跑測試，**必須 PASS**
3. **每次 sabotage 與恢復後清 `__pycache__`**（`find . -name __pycache__ -type d -exec rm -rf {} +`）——stale `.pyc` 會讓判定失真（實測誤判 2 個測試壞掉）
4. 任一 sabotage 沒讓測試 FAIL → **第一步先質疑需求，不是加壓**：追該行為點的最終消費點，確認該性質被破壞時可觀察輸出真的會變——輸出不變＝該性質非 load-bearing（假需求，典型如「下游依 key／name 重新定位，中間順序根本不影響輸出」），回報使用者建議自 Spec／DoD 移除，探針作廢不補。確認是真需求 → 斷言無效，修測試後重做
5. **停損（硬性）**：同一行為點 **2 次 sabotage 仍綠即停手回報使用者**，禁止繼續加時序延遲／調並發數／加壓力硬湊 FAIL（實測：為一條假保序需求反覆調時序空轉數十輪——探針一直綠的最常見原因不是壓力不夠，是需求是假的）；結果（sabotage 了哪些點、FAIL/PASS 確認、作廢的探針與理由）記入 `local_test_evidence`
6. **獨立重放（主 flow 執行，不採信自報）**：**抽樣** item 的 step 5 收尾時，**主 flow 親自重放至少一組 sabotage→FAIL→恢復→PASS**，不採信 writer 的自報結果（實測「主 flow 重放」抓到自報遺漏）。重放主體是主 flow 而非 code-reviewer——reviewer 是只讀角色，不改檔；重放同樣遵守第 3 步清 `__pycache__`，做完恢復原狀

## 真新失敗的處置（script 確認可重現後才進這裡）

script 重跑確認可重現的真新失敗，先判是否屬下列兩種**確定性處置**（不是「卡住」、不需 HITL）：

| 分類 | 判定 | 處置 |
|---|---|---|
| **測試過時** | 測試斷言的是被 Spec **有意**改掉的舊行為 | 更新測試，並在 `local_test_evidence` 註明：改了哪個測試、舊斷言為何不再成立、對應的 Spec／task 依據。**無依據的放寬斷言／刪 case／加 skip 視同 🔴**（code-reviewer 審查重點）。（有意行為變更的舊測試批次同步走 task-decomposition 的「測試同步段」，在實作 item 內、check 之前完成）。**並行 worktree run 例外（parallel-run）**：既有測試只增不改，需要更新既有測試＝獨立性假設已破，觸發卡住退出並行，不在 worktree 內同步 |
| **肇因非本 item** | 累積聯集照出的失敗，肇因是**先前已 passed 的 sub_task**（潛伏 bug 被本 item 新測試或新路徑照到；用 `git diff --cached -- <各 sub_task 的 files>` 定位肇事者） | 走「重開路徑」重開肇事 sub_task（同 commit 前全套檢查的處置）；本 item 不動 |
| **疑似既有失敗（baseline 盲區）** | 失敗的測試檔與本 run 變更檔聯集（`eval_state.py list-files`）**無交集**，或一眼可見與本 run 變更無關 | **不調查、不修，直接回報使用者裁決**。已知盲區成因：related 全 repo 掃可選到 `test_command` 範圍外的測試、環境／日期漂移、參數化 ID 變動——baseline 快照照不到不代表是新失敗。使用者裁定為既有 → 把該測試 ID 補進 baseline 檔的 `stable_failures`（直接編輯 `run/<run_id>.test_baseline.json`），之後的 check 不再回鍋；**裁決不持久化就會每個 sub_task 重複誤報一次** |

**三分類的判定上限是一次機械比對**（對 list-files 聯集、看 `git diff --cached`）——需要讀測試實作、追 import 鏈、跑額外測試才能歸因的，一律視同塞住，立即 HITL，**禁止自行調查歸因**（實測：這種調查燒大量 token 後結論多半是「與本 run 無關」，白查）。

**三者皆非（真的是本 item 的 code 錯）→ 立即回報使用者裁決（人是計數器）**：不再有「自修 N 次才舉手」的額度——script 不記 strike、不設上限。把「卡在哪些測試、失敗原文、已試過什麼」回報使用者，由使用者決定續修或改路。塞住時的正確行為是舉手，不是自行空轉迴圈。（真失敗已由 script append 進 baseline 檔的 `failure_log`，稽核時「紅過卻無回報」即抓吞失敗）

## Commit 前全套檢查與重開路徑（跨 sub_task 破壞的最後防線）

step 6 收尾**之前**（歸檔 eval_state 前）跑一次全套：

```
python3 .claude/hooks/test_baseline.py check --strike-key full_suite
```

（省略 `--cmd` → 讀 manifest 的 `test_command`，與 baseline 同源同範圍）

- exit 0 → 照常收尾
- exit 2 → 相關測試沒抓到的跨 sub_task 破壞。處置：
  1. 用 `git diff --cached -- <各 sub_task 的 files>` 定位是哪個 sub_task 的變更弄壞的
  2. **重開該 sub_task**（即使已 `passed`）：`status` 改回 `"in_progress"`、`local_test_passed` 改回 `false`、`step` 設 `"fixing"`
  3. 修正後從循環**步驟 3** 重走（review → verify → test 照常，不可只補測試就標回 passed）
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

- **script 判定可稽核**：baseline 檔、`failure_log`（真失敗留痕）、check 結果都落在 `run/<run_id>.test_baseline.json`，事後可驗——「`failure_log` 有紀錄卻無對應的使用者回報」即抓 agent 吞失敗
- **hook 不重跑測試**：`eval_gates.py` 於 commit 時強制的是 `local_test_passed`／`local_test_evidence` 欄位與歸檔順序，無法驗證「失敗清單是真的」。「跑了 check 且如實記錄」這一段靠 agent 誠實＋baseline 檔留痕的事後稽核——這是已知且接受的邊界，不假裝它是硬 gate
