---
name: test-strategy
description: Eval Flow step 5 本地測試 gate 的執行細節：baseline「無新增穩定失敗」機制、writer 相關自驗、累積聯集相關測試、假測試 lint、具名盲點驗證、分 tier 的 commit 前收尾檢查與重開路徑、零測試專案處置、驗證豁免窗口。觸發語：Eval Flow 循環進入 step 5 時、「測試失敗怎麼辦」、「建測試 baseline」。不適用於：測試框架選型（Tier B bootstrap 的 HITL 決定）。
---

# Test Strategy（本地測試 gate 執行細節）

> 核心原則：**測試是 pipeline 的護欄，不是路障**——gate 擋的是「你新弄壞的東西」，不是「專案裡所有壞掉的東西」。gate 條件不是「全綠」，而是「**無新增穩定失敗**」。
> 判定一律由 script `.agent-flow/scripts/test_baseline.py` 執行（baseline 比對、重跑確認可重現都是確定性邏輯，**不留給模型憑感覺判**）；本文件規範何時跑、結果怎麼處置。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## 依變更選擇驗證（全 tier，單一枚舉點）

**Tier 決定分析與獨立審查深度；變更內容決定驗證方式。** 主 flow 在規劃時列出每條 DoD／契約的驗證方法、可接受結果與證據位置，原文貼進 writer 的硬性約束區。下方 baseline、相關自驗、lint、具名盲點驗證、整合與完整回歸規則只適用其對應的程式／測試部分。

- **純基礎設施設定**（例如 nginx、SSL）：使用設定檢查與必要操作驗證；這是有效驗證，不是 `test_policy` 豁免。不得僅因 Tier 2 強制新增 Docker、測試框架、單元／整合測試或 mutation。
- **程式行為變更**：保留相關行為測試與既有失敗處置。**混合任務**逐部分取證，設定檢查不能替代程式測試，不能藉分類隱藏既有相關測試失敗。
- **純重構**：動手前確認既有行為契約與適用證據，完成後以相同契約核對可觀察結果。沿用有效證據與既有驗證程序，不另設固定的前後雙跑或逐項新增測試。
- **SSL 範例**：準備設定可用語法、憑證網域／有效期／憑證鏈等檢查交付，列出部署後待驗項目；實際部署另須授權範圍內的載入結果、目標環境 TLS 連線與指定 HTTPS 端點回應。只做語法檢查不能宣稱部署成功。需求授權不明時不得執行遠端變更。
- **擴大驗證**前記錄具體缺口、現有證據不足理由、最小驗證手段與停止條件；使用既有工具優先。新環境只有在必要驗證無法由既有手段完成時才建立。不得因成本把必要驗證移到後續；反覆修理設施時停止自動擴充、回報阻礙並重新評估範圍。
- **收尾**：全部必要證據齊全、適用驗證通過且必要的獨立審查或主 flow 自查完成，就進入收尾。必要環境／權限缺失時記錄受阻原因與未驗項目，依 eval-flow `references/formats.md` 的 manifest item 對帳狀態規則保留未完成狀態；必要證據缺失不得標通過或完成。設定準備與實際部署的 DoD 必須分開。
- **證據**記錄實際命令、執行時間、目標環境、可接受結果、實際輸出與限制，遮蔽秘密。exit 0 不足以證明符合契約，須核對實際結果與預期；複合收尾命令任一必要檢查失敗須回傳非零，不得以最後一條成功覆蓋先前失敗。主 flow 用 `run_verify.py` 執行適用命令並保存成功快照；保留 schema 2、prepare → Run-Id commit → finalize。遠端／實際環境狀態不在本地快照內，不得僅因本地輸入相同自動 `--reuse`，須重新確認目標狀態。

## 測試取捨（全 tier，單一枚舉點）

依 [Test Desiderata](https://testdesiderata.com/) 的十二項屬性互相衝突，本 repo 只優先四項；writer 寫測試、reviewer 審測試、lint 警示都以本節為準，不在角色檔重述。Predictive 與 Inspiring 是四項的結果，不另設檢查。

| 屬性 | 判準 | 違反的典型樣子 |
|---|---|---|
| **Behavioral** | 斷言回傳值、exit code、檔案與狀態副作用、訊息的 key 或 gate id | 斷言訊息全文、欄位順序、完整輸出形狀（lint `message-literal`） |
| **Structure-insensitive** | 走公開介面；mock 只在系統邊界（外部 API、時鐘、亂數）；改文案或重構時測試不該壞 | mock 專案內部函式、數呼叫次數、讀私有狀態（lint `internal-coupling`） |
| **Writable** | 既有測試能驗就沿用；新增測試須在交付憑據寫 `new:<函式>\|<既有為何不夠>`；本次測試行數不應超過被測程式碼（`run_verify` 記 `test_growth_ratio`） | 每條 DoD 一個新測試、憑據只能靠 grep 新函式名成立 |
| **Specific** | 一個測試一個主題；只差常數的案例合成一個參數化測試；一個行為只在主題測試完整斷言，路過行為只驗存在性／型別／狀態碼 | 同檔多個只差一個值的測試；多個測試同時鎖同一細節 |

lint 的兩條新規則只警示、不擋 commit；writer 把警示列進工作報告，reviewer 對未豁免的警示標 🟡。豁免用行尾 `# testlint: allow` 並在 `local_test_evidence` 記理由。

## adaptive Tier 1 的適用方式

新 Tier 1 的方法與 HITL／獨立審查判斷依 eval-flow 的 Tier 1 路徑。本文件的驗證範圍、
基準可信性、來源新鮮度與誠實證據要求仍適用；不因自查而放寬失敗或補造既有基準。
主 flow 可在已授權範圍修正可定位的程式錯誤並重新驗證，不為每次失敗增加 HITL。
需要業務決策、範圍變更或有未解驗證缺口時才依適用路徑處理；下方固定共用循環的
修正／重審順序適用 Tier 2 與舊 run，不替 adaptive 預設加派 checker。

## 外部答案解析與第二根因（契約與證據的單一枚舉點）

修改外部答案解析、抽取品質或發現第二根因時，規劃、派工與審查前必讀 [外部結果與範圍裁示](references/external-results.md)，並依其規則投放適用條文與取證。

## Baseline（run 的測試基準，第一次產品修改前建立）

使用 baseline／check 扣除既有失敗前，必讀 [基準建立與可信沿用](references/baseline.md)。修改後缺基準或環境改變時也適用；不得補造既有失敗。不需扣除既有失敗時，可直接以 `run_verify.py` 驗證零失敗。

## Writer 相關自驗與 mine 快速模式

writer 須依變更跑相關測試，既有證據足夠時不新增案例。派 writer 或使用 mine 前必讀 [相關自驗與 mine](references/writer-mine.md)；mine 不替代完整相關測試或可重用快照。

## 前端／UI 實機驗證的定位（best-effort，非阻塞）

> 本節只處理前端視覺呈現，不適用 SSL 部署等必要操作驗證。阻塞 gate 是**功能正確性的自動化測試**（下方 step 5 的 baseline check），**不是**前端 UI 的瀏覽器實機驗證。

- **前端 UI 實機驗證屬 best-effort**：能備妥環境就做，備不妥就記 best-effort、以功能測試為準，**不阻塞收尾**。目前現況下前端實機驗證成本高、不易穩定備妥，驗證重心明確放在功能正確性
- **不從零手刻平行 runtime**：起 app 前先找專案既有的啟動把手（`start-dev.sh`／`Makefile`／`package.json` scripts），有就一鍵起（正確 port／JWT secret／DB 已內建）。沒有或起不來 → 記 best-effort，**不自訂 port／secret／DB 手搭一套平行環境**——那是鑽牛角尖，不是驗證
- 定位依據：R-014（測試鬼打牆全在 UI runtime，自動化 gate 一次過）
- **視覺類 DoD 的使用者驗收（`[憑據:step5]` 條目的 best-effort 收口）**：帶 `[憑據:step5]` 記號（定義住 task-decomposition skill）的 DoD 條目，實機環境備妥 → 實跑取證；備不妥 → step 5 列「待使用者驗收」清單回報使用者逐條裁決，裁決記入 `local_test_evidence`（含使用者裁決原話一句）。
  - **本路徑非豁免**——不觸發 `test_policy`、不需使用者明示豁免宣告；自動化功能測試照常硬 gate，交給人的只有「呈現對不對」這一段本來就無自動憑據的判定

## 分段與重用

程式行為變更在 Tier 2 實作期間跑相關測試，提交前跑一次完整回歸；純設定依「依變更選擇驗證」收尾。輸入未變的本地成功結果可明確重用；條件、快照與 live 邊界依 eval-flow `references/efficiency.md`。失敗與輸入改變仍依下列硬性 gate 處置。

## Step 5 執行順序（每個 sub_task）

進入本步先依「分段與重用」核對 writer 已有證據，以相同 target 的 `run_verify.py --reuse` 明確沿用有效紀錄。mine 不落快照，不能當成完整回歸或可重用的 run_verify 紀錄。跨 task 與 manifest 不自動轉用證據；收尾無相符完整回歸紀錄時安全重跑。再依「依變更選擇驗證」選定方法。純設定直接由主 flow 用 `run_verify.py` 跑設定／操作檢查並核對全部必要結果，不走下列測試專用步驟；混合任務同時完成適用的兩部分。

進入本步先按 `.agent-flow/CODE_QUALITY.md` 核對 formatter 與適用 log 證據。對本次 Python 檔執行選定 formatter 的檢查模式，以 `run_verify.py` 留下實際命令與結果；無適用檔案記原因，缺工具或檢查失敗不得記通過。格式化若改動受審內容，先重新 stage 並依 eval-flow 的增量審查規則核對變更，再驗證。log 測試併入下方相關測試，不另建重複案例。格式檢查成功不能代替本步功能測試或最後收尾驗證。

0. **行為驗證紀律**：寫任何驗證程式（含臨時 harness）前，先確認實際介面——`inspect.signature`、讀函式定義，**不憑印象寫**（R-015）。
   - 驗證碼不是 throwaway：缺口需要持續回歸時才加入相關測試；已有足夠測試時沿用，不為每次驗證新增檔案
1. **選相關測試（累積聯集）**：
   ```
   python3 .agent-flow/scripts/test_baseline.py related --files $(python3 .agent-flow/scripts/eval_state.py list-files)
   ```
   `--files` 餵的是**本 run 至今所有 sub_task 的 files 聯集**（`eval_state.py list-files` 直接輸出），不是只有本 item。
   - 跨 item 破壞幾乎都落在本 run 碰過的檔案輻射範圍內，累積回歸集讓破壞在**肇因 item 當場爆、歸因免費**（唯一的新變數就是現在這個 item，在循環內修即可），而不是拖到收尾全套才發現、走昂貴的重開路徑
   - script 用「測試檔命名慣例 + grep 引用」找；**輸出只是候選起點**，agent 要補上：本 sub_task 新寫的測試、以及改到 shared module 時自己判斷的追加範圍。寧可多選不可少選
2. **假測試 lint**（跑測試前先驗測試本身）：
   ```
   python3 .agent-flow/scripts/test_lint.py <本 sub_task 新增/修改的測試檔>
   ```
   抓機械可辨的假測試模式：if-guard 藏斷言、無斷言測試、恆真斷言（機械可辨的模式用 lint 擋，不靠散文約束）。
   - exit 2 → 修測試；確認誤報（如「不拋例外即通過」型測試）→ 行尾加 `# testlint: allow` 並在 `local_test_evidence` 註明理由
   - commit 時 hook 會對 staged 測試檔再跑一次（硬防線）
3. **跑 gate 判定**：
   ```
   python3 .agent-flow/scripts/test_baseline.py check --cmd "<相關測試指令>" --strike-key sub_task_<id>
   ```
   - exit 0（無新增穩定失敗）→ gate 通過：`local_test_passed: true`，`local_test_evidence` 填 script 輸出摘要（指令＋PASS 行＋略過的 baseline 失敗數）
   - 本步驗證以 `run_verify.py` 一次完成執行與留痕，不另補 `add-verification`；紀錄與提交快照的語義以 `eval-flow` skill「資料格式與操作規則」為準。
   - exit 2 → 有真的（可重現）新增失敗，進下方分類決策樹
4. **非確定性失敗由 script 自動放行**：非 baseline 的新失敗會自動重跑一次確認可重現——重跑通過（不可重現）→ 印警示「非確定性失敗，未阻擋」、不擋、**不持久化任何名單**；重跑仍失敗（可重現）→ 真新失敗，script append 一筆 `failure_log`（供稽核「紅過就有痕」）並 exit 2

## 具名盲點的針對驗證

不要求固定逐檔 sabotage、Tier 2 每 run mutation 或主 flow 獨立重放。reviewer 先審需求、實作與現有證據；只有指出具名盲點時，才要求針對該盲點補測試或實驗。已有足夠證據時不新增測試。

判斷測試品質時，關注斷言能否辨識契約中的錯誤結果，而非只看程式是否執行或測試是否通過。例如必要寫入遺漏或邊界判斷錯誤，現有證據能否辨識？這是閱讀既有證據時的判斷方式，不要求逐條實驗或導入 mutation 工具；具體缺口才按本節補驗。既有實驗未使測試失敗時，先區分缺斷言、變異無可觀察差異或路徑不可達，不直接認定測試無效。

採 mutation／sabotage 時，只暫改具名行為點，確認對應測試 FAIL，再恢復並確認 PASS；清除受影響的 `__pycache__`，用 `git diff` 確認沒有實驗殘留。記錄破壞點、實際命令與 FAIL/PASS 輸出。不可只寫預期結果。實驗未能區分行為時先確認需求與最終消費點；同一行為點兩次仍無鑑別力即停止、帶結果交付，不加壓硬湊 FAIL。主 flow 只在證據失效或有具名疑點時補驗，不固定重放。

## 真新失敗的處置（script 確認可重現後才進這裡）

script 重跑確認可重現的真新失敗，先判是否屬下列三類；前兩類可依既定規則處理，第三類須使用者裁決：

| 分類 | 判定 | 處置 |
|---|---|---|
| **測試過時** | 測試斷言的是被 Spec **有意**改掉的舊行為 | 更新測試並在 `local_test_evidence` 註明依據；無依據放寬視同 🔴（詳見表下補充） |
| **肇因非本 item** | 累積聯集照出的失敗，肇因是**先前已 passed 的 sub_task**（潛伏 bug 被本 item 新測試或新路徑照到；用 `git diff --cached -- <各 sub_task 的 files>` 定位肇事者） | 走「重開路徑」重開肇事 sub_task（同 commit 前收尾檢查的處置）；本 item 不動 |
| **疑似既有失敗（baseline 盲區）** | 失敗的測試檔與本 run 變更檔聯集（`eval_state.py list-files`）**無交集**，或一眼可見與本 run 變更無關 | **不調查、不修，直接回報使用者裁決**（詳見表下補充） |

- **測試過時補充**：`local_test_evidence` 註明改了哪個測試、舊斷言為何不再成立、對應的 Spec／task 依據。**無依據的放寬斷言／刪 case／加 skip 視同 🔴**（code-reviewer 審查重點）。
  - 有意行為變更的舊測試批次同步走 task-decomposition 的「測試同步段」，在實作 item 內、check 之前完成
  - **並行 worktree run 例外（parallel-run）**：既有測試只增不改，需要更新既有測試＝獨立性假設已破，觸發卡住退出並行，不在 worktree 內同步
- **疑似既有失敗補充**：已知盲區成因：related 全 repo 掃可選到 `test_command` 範圍外的測試、環境／日期漂移、參數化 ID 變動——baseline 快照照不到不代表是新失敗。
  - 使用者裁定為既有 → 記錄裁決及依據；只有修改前同一測試 ID 的重跑確認證據才可形成可扣除基準，不能直接編輯名單或補造 observations。修復方式依上方 Baseline 節

**三分類的判定上限是一次機械比對**（對 list-files 聯集、看 `git diff --cached`）——需要讀測試實作、追 import 鏈、跑額外測試才能歸因的，一律視同塞住，立即 HITL，**禁止自行調查歸因**（這種調查結論多半是「與本 run 無關」，成本不划算）。

**三者皆非（真的是本 item 的 code 錯）→ 立即回報使用者裁決（人是計數器）**：沒有「自修 N 次才舉手」的額度——script 不記 strike、不設上限。把「卡在哪些測試、失敗原文、已試過什麼」回報使用者，由使用者決定續修或改路。塞住時的正確行為是舉手，不是自行空轉迴圈。

（真失敗已由 script append 進 baseline 檔的 `failure_log`，稽核時「紅過卻無回報」即抓吞失敗）

**裁決後的回修路徑（明文，不靠拼裝）**：使用者裁決「是 bug、要修」（含 step 5 實跑／使用者驗收發現的行為問題）後依序：
- 主 flow 把裁決結果補進該 item 的契約表 row（沿 eval-flow 循環 step 1 的補表機制，表可增補、single source 不變）
- 該 sub_task `step` 設 `fixing`、回派修正（直寫捷徑 item 由主 flow 直修）
- 從循環 **step 3** 重走（審查輪 r+1，r 號規則見 eval-flow step 3）

不新設迴圈——這與審查退回共用同一條 fixing 路，差別只在入口（審查輪發現 vs step 5 發現）與前置動作（先補契約 row 再修）。

## Commit 前收尾檢查與重開路徑（跨 sub_task 破壞的最後防線，分 tier）

step 6 收尾**之前**（Tier 2 歸檔 eval_state 前）跑一次收尾檢查，純設定使用既定設定／操作驗證；以下測試範圍**依 tier**（收尾全套從未抓到累積聯集漏掉的破壞，而全套成本隨測試數線性上漲）：

| Tier | 收尾檢查範圍 | 指令 |
|---|---|---|
| **Tier 1** | **累積聯集**（本 run staged 檔的相關測試），**不跑全套** | `python3 .agent-flow/scripts/test_baseline.py check --cmd 'python3 -m pytest -q $(python3 .agent-flow/scripts/test_baseline.py related --files $(git diff --cached --name-only))' --strike-key wrapup_related`（`--cmd` **必須單引號**：讓 `$(…)` 在 test_baseline 的 sh 內展開才會依換行分詞，外層 shell 先展開會把換行塞進單一字串、pytest 之後的檔名被當命令執行而報 `__suite__`；測試框架指令依專案 `test_command` 的直譯器改寫；Tier 1 無 `eval_state.json`，files 聯集取 staged 清單） |
| **Tier 2** | **全套**（manifest `test_command`） | `python3 .agent-flow/scripts/test_baseline.py check --strike-key full_suite`（省略 `--cmd` → 讀 manifest，與 baseline 同源同範圍） |
| parallel-run merge gate | 全套（規則住 parallel-run skill，不變） | 同 Tier 2 |

- Tier 1 的 related 輸出為空（純 prose 變更等）→ `local_test_evidence` 記「wrapup_related：無相關測試」，以 step 5 既有憑據收尾；**不得改跑全套湊憑據**（全套在 Tier 1 不是憑據要求）
- exit 0 → 照常收尾
- exit 2 → 相關測試沒抓到的跨 sub_task 破壞。處置：
  1. 用 `git diff --cached -- <各 sub_task 的 files>` 定位是哪個 sub_task 的變更弄壞的
  2. **重開該 sub_task**（即使已 `passed`）：`status` 改回 `"in_progress"`、`local_test_passed` 改回 `false`、`step` 設 `"fixing"`
  3. 修正後從循環**步驟 3** 重走（review → verify → test 照常，不可只補測試就標回 passed）
  4. hook 的歸檔 gate 自然擋住未重過的 commit（任一 sub_task 非 passed 即擋），順序不可能被跳過

## 零測試專案

先依「依變更選擇驗證」判定。純設定不建立測試框架；下表只適用程式行為變更或已授權的測試工具 bootstrap。

| 情況 | 處置 |
|---|---|
| 新專案 | 不會發生——Tier B bootstrap 的 DoD 硬性含測試框架＋示範測試 |
| legacy、Tier 1 | 實際運行功能驗證＋`local_test_evidence` 照填（現行規則），不強制建測試 |
| legacy、Tier 2 | **程式新行為需要自動化測試且缺框架時建最小框架**：分拆時第一個 task 加「建立最小測試框架＋本功能的測試」item（比照共用基礎抽前置 task 的慣例）。「最小」＝能跑單元測試＋覆蓋本次新行為，不要求 e2e、不補歷史覆蓋。無修改前可執行測試時，不產生既有失敗名單；新框架與本功能直接驗證零失敗，依 Baseline 節處理 |
| 連最小框架都建不起來 | 這本身就是舉手訊號：停下回報，由使用者裁決走運行驗證＋manifest 記 `debt: ["test-framework"]`（攔截級，還清前 hook 擋新 run——防「建不起來」變永久後門） |

## 驗證豁免窗口（全 tier 通則，總則住在 .agent-flow/ROUTER.md）

- 跳過本地驗證**僅限使用者明示豁免**；agent 不可自行認定、**不可主動建議豁免**（與 hotfix 宣告緊急同一防濫用原則）
- **豁免單次有效**：只管當次需求，不延續、不存在口頭的專案級常態豁免
- 留痕方式按 tier：
  - **Tier 1／2**：manifest 記 `test_policy: "waived_by_user"` ＋一句豁免範圍與使用者原話（manifest 為冷溯源檔，留在工作目錄不進版控）。waive 率可統計（比照 tier 分佈統計）——豁免比例異常升高是制度失效的警報
  - **Tier 0**：不為豁免建檔（維持零建檔哲學）。豁免記在 Tier 0 本來就要交付的**變更回報**裡：驗證欄寫「使用者豁免（引用原話）」。此為**弱留痕，屬有意取捨**（Tier 0 已排除高風險面，稽核價值低）
- 豁免不改變 Tier 準入條件：信任邊界／公開契約的本體變更照樣進不了 Tier 0／1（判準住 .agent-flow/ROUTER.md Router 防濫用規則）

## 硬 gate 與誠實回報的邊界（明寫取捨）

- **script 判定可稽核**：baseline 檔、`failure_log`（真失敗留痕）、check 結果都落在 `run/<run_id>.test_baseline.json`，事後可驗——「`failure_log` 有紀錄卻無對應的使用者回報」即抓 agent 吞失敗
- **hook 不重跑測試**：`eval_gates.py` 於 commit 時強制的是 `local_test_passed`／`local_test_evidence` 欄位與歸檔順序，無法驗證「失敗清單是真的」。「跑了 check 且如實記錄」這一段靠 agent 誠實＋baseline 檔留痕的事後稽核——這是已知且接受的邊界，不假裝它是硬 gate
