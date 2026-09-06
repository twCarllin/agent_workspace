---
name: eval-flow
description: Eval Flow 的完整執行細節：Tier 2 前置 0–3（初始化、風險分析、使用情境、分拆 task）、循環步驟 1–7（code-writer → review（含完成度節）→ 本地測試 → commit）、Tier 1 精簡路徑、run manifest 與 eval_state.json 格式與操作規則、hook gate 清單。觸發語：Router 判定需求為 Tier 1 或 Tier 2 時（執行前必須載入本 skill）、「跑 Eval Flow」、「照流程實作這個需求」。不適用於：Tier 0 微調（直接改，收尾僅 append 一行 tier0 留痕，見 CLAUDE.md Router）、非實作類的問答。
---

# Eval Flow（Tier 1／2 執行細節）

> 本 skill 由主 flow 在 Router 判定 **Tier 1 或 Tier 2** 後載入執行。Router 分級表與防濫用規則住在 CLAUDE.md，不在此重述。Tier 2 走完整路徑（前置 0–3 ＋循環）；Tier 1 走文末「Tier 1 精簡路徑」（跳過部分前置，共用循環）。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Tier 2 完整路徑

當一個需求被 Router 判為 **Tier 2**（需實作的完整 Spec）時，執行以下流程。**Model 不在 flow 層級統一指定**，由每個 agent 依任務性質自行決定（見下「Model 指派原則」）。

### 前置 0：初始化（進入點，必須是第一個動作）

- **進場檢查（建 manifest 之前）**：跑 `git status --porcelain`。非空 → 列出檔案清單問使用者歸屬（納入本 run／擱置不動），裁決一句寫入 manifest `dirty_tree_ruling`（選填欄；乾淨樹免記）。孤兒變更不先裁決，staging 與 commit 範圍會在收尾才爆（實測教訓，2026-09-06）
- 接收本次要實作的 **Spec**（來源：Stage A intent→spec 的產出，或使用者手動指定的路徑）
- 決定 `run_id`：`YYYY-MM-DD-<spec-slug>`（例如 `2026-07-06-partial-settlement`），作為本次 run 貫穿各檔的關聯鍵
- **建立 run manifest** `run/<run_id>.json`（**冷溯源檔，commit 時隨 code 進 git、永不清除**），填入：
  - `run_id`、`created_at`
  - `spec_path`：指向這份 Spec 的實際路徑（進入點在此把 Spec **記錄下來**）
  - `usage_report_path`、`task_file`：先設 `null`
  - `phase`：`"init"`
  - `status`：`"in_progress"`
- **建立 `eval_state.json`**（**熱 scratchpad，commit 後清除**），填入 `run_id`（指回 manifest）、空的 `sub_tasks`
- **Gate（硬性）**：manifest 的 `spec_path` 未寫入前，**不可進入前置 1（風險分析）**。沒有被記錄的 Spec，等於整條 pipeline 沒有輸入來源
- 各後續步驟一律用 `eval_state.json.run_id` 定位 `run/<run_id>.json`，從 manifest 讀 `spec_path` / `usage_report_path`，**不重組日期 / 檔名**

### 前置 1：多面向風險分析（必須在第一次呼叫 code-writer 之前完成）

- 使用 **task-risk-analysis** skill，讀取 manifest `run/<run_id>.json` 的 `spec_path` 指向的 Spec，從 6 大面向（技術、安全、資料、效能、部署、業務維護）逐一思考任務風險
- **只寫觸及的面向**：有風險者標註等級（🔴 重大 / 🟡 中等 / 🟢 輕微）並寫風險描述與對策；與本任務無關者不逐節填寫，改在報告開頭以一行 `不適用：<面向清單>` 帶過
  - **面向未寫不等於已評估為無風險——判為不適用者仍須列名，漏列即視同未做**（六面向須全部出現在「有風險節」或「不適用」行之一）
- 產出「風險分析報告」，內容包含：不適用面向一行、各有風險面向的判斷、風險描述、對應對策
- **報告存檔（不可只留在對話裡）**：寫入 `risk/<run_id>.md`，並回寫 manifest 的 `risk_report_path`——中斷在前置 1 與前置 2 之間時，接手者才有報告可讀
- **判斷規則**：
  - 有 🔴 重大風險 → **不可進入任何後續步驟（含使用情境分析）**。必須先修改 **Spec**（補上前置條件 / 縮小範圍 / 釐清描述），再重新分析，直到無 🔴
  - 🟡 中等風險 → 記錄於風險報告，並在「分拆 task」時帶入對應 item 的備註，由 code-writer 實作時注意
  - 🟢 輕微 / 無風險 → 可進入下一步「使用情境分析」
- 無 🔴 確認後，將 manifest 的 `phase` 更新為 `"risk_done"`（hook 憑此放行 usage-analyzer 呼叫）
- 風險分析報告先以 **Spec 為單位**產出；待「分拆 task」完成、`sub_tasks` 建立後，再把對應風險映射到 `eval_state.json` 各 sub_task 的 `risk_analysis` 欄位

### 前置 2：使用情境分析（必須在分拆 task 之前完成）

- 呼叫 **`usage-analyzer` subagent**。它讀 Spec、產出使用情境報告，並在自己的定義與 `usage-scenario-analysis` skill 中規範報告內容、情境 id、邊界盤點與存檔位置。
- **flow 層級 gate**：報告需經**使用者確認**；未確認前不進入前置 3（usage-analyzer 在確認後才回寫 `manifest.usage_report_path`，並將 `phase` 更新為 `"usage_confirmed"`）。
- **確認留痕**：確認當下主 flow 把「時間＋確認範圍一句話」寫入 manifest 的 `hitl_confirmed_at`（留痕，接手者可驗證），並把**裁示條數**寫入 `hitl_rulings`（int，選填；無裁示填 0）——人閘門的價值信號是裁示數不是打回率（實測：打回率 0% 的 HITL 曾單次產出 11 條裁示含推翻設計），消費端見 stats.py。

### 前置 2.5：影響面盤點（預設執行）

- 呼叫 **`impact-analyzer` subagent**。它讀 Spec 與使用情境報告，用 Grep／Glob／Bash 自行掃 codebase，產出 `impact/<run_id>.md`（五節：觸及模組清單、各模組既有慣例、可重用既有元件、被改介面的呼叫端清單、跨模組風險點），並回寫 `manifest.impact_report_path`。
- **skip 條件**：全新模組（codebase 無對應目錄或相關程式碼）或無既有呼叫端。符合時 impact-analyzer 不產出報告，manifest 記 `impact_report_path: "skipped: <理由>"`。
- **不新增 phase 值**：本步驟完成後 phase 仍保持 `usage_confirmed`；下一步前置 3 的 task-decomposer 呼叫 prompt 須含 impact report 路徑（拆分依模組邊界切 item files 與 DoD）。
- **防跳過（編排層 gate）**：前置 3 呼叫 task-decomposer 前，主 flow 須確認 `impact_report_path` 非 `null`（`null` → 先補跑本步）。hook 只強制 impact-analyzer 的呼叫時序（AGENT_MIN_PHASE），不強制「必跑」——本步在 Tier 2 是預設步驟、靠編排保證，非 hook 硬防線，接手者勿誤以為已被強制。

### 前置 3：分拆 task（必須在第一次呼叫 code-writer 之前完成）

- 呼叫 **`task-decomposer` subagent**。它讀 usage 報告與 Spec、拆成 task 與 item、寫入 `task/YYYY-MM-DD.md`、回寫 `manifest.task_file`、並執行交付前自檢。拆分粒度、上限、五要素等規則住在它的定義與 `task-decomposition` skill。
- **flow 層級 gate**：`manifest.usage_report_path` 為 `null` 不可進入本步（task-decomposer 會自我中止）。
- task-decomposer 交付前自檢通過後，將每個 task 展開為 `eval_state.json` 的 `sub_tasks`，並將 manifest 的 `phase` 更新為 `"decomposed"`（hook 憑此放行 code-writer），才進入下方循環。

## 循環（每輪結果寫入 `eval_state.json`）

> **循環中的升級逃生門（Tier 2 也適用）**：循環執行中若冒出 🔴 重大風險、或發現需求歧義（DoD 講不清、Spec 有洞）→ 中止循環，回前置 1 修改 Spec 並重新風險分析；若影響使用情境或拆分，一併重跑前置 2／3。

1. 呼叫 `code-writer` subagent 產出程式碼
   - **知識前置（硬性步驟）**：呼叫前，主 flow 把三個來源的相關內容**原文貼進 writer prompt 的硬性約束區**——不是叫 writer「自己去讀」，知識只有以明文約束前置進 prompt 才有效（R-011）。三源：
     - **retro 條目**：先以本 item `files` 的模組路徑 grep `retro/RETRO.md` 的標籤篩選（標籤第一段＝模組路徑，見 retro agent 規範），主 flow 再補判同類操作／同類風險面的條目
     - **模組 conventions**：本 item 觸及模組的子目錄 `CLAUDE.md`（存在則摘錄相關段）
     - **impact report 慣例段**：前置 2.5 有跑時，摘錄該模組的「各模組既有慣例」與「可重用既有元件」節（節名見 impact-analyzer 定義）
     - grep 篩選的對象是**模組名片段**（取自 files 路徑的目錄／檔名，如 `eval_gates`、`hooks`），不是整段路徑——retro 標籤慣用全形 `／`，整段半形路徑會靜默零命中
     - 三源皆無相關內容時在 prompt 註明「知識前置：三源均無相關內容」（留痕，防跳步）
   - **測試管轄註記**：派工 prompt 附一句「測試自驗只准跑 `python3 .claude/hooks/test_baseline.py mine --strike-key sub_task_<id>`，依你定義中的測試管轄規則」（writer 層 mine 模式細節住 test-strategy skill，不重述）
     - `[P]` item 在 fan-out（各開 worktree）或循序退回下 mine 模式均適用——隔離樹或逐個執行時未提交變更範圍可正確推導，不再需要「指定測試檔清單」舊 workaround
   - **契約前置與仲裁句（硬性）**：派工 prompt 必須把本 item 的**行為契約表原文**（task 檔的 `契約:` 行，含邊界 row）貼進硬約束區作為仲裁基準——不是叫 writer 自己翻 task 檔（與知識前置同一教訓，R-011）。
     - 並附一句：「測試紅時先仲裁再動手，對到契約表 row 判哪邊錯；**契約表沒答案 → 帶失敗交付是正確行為，硬湊綠燈才是違規**」
     - 無契約表的 item（Tier 1 無表 fallback）仲裁句改指 DoD
     - writer 以「表沒答案」帶失敗交付時，**主 flow 裁決**：讀 Spec／usage 報告判該行為的預期，把裁決結果補進契約表（表可增補、single source 不變）再回派；Spec 本身有洞才走升級逃生門問使用者
   - **交付稽核（writer 交付時，兩個對照）**——正常交付（次數合理、記錄對得上）瞄一眼即過，不展開：
     - ①工作報告的「仲裁記錄」：紅過的測試每條都要有仲裁行，判「測試超出契約」者核對 row 引文與 task 檔原文一致（對不上＝假仲裁，退件）
     - ②`run/<run_id>.mine_log.json`：mine 執行次數異常多、測試檔 hash 在失敗未清的情況下反覆變動、失敗集合遊走＝「改測試湊綠」的機器指紋，退件重派並要求逐條補仲裁依據
2. 將變更檔案 `git add` 進 staging area（確保 checker／code-reviewer 可透過 `git diff --cached` 讀取）。
   - **預設派 task-verifier（checker）時，prompt 附 `git diff --cached --stat -- <files>` 輸出**（僅檔名與行數統計，checker 不讀 diff 內容）
   - **升級為 code-reviewer 全 diff 審時，prompt 硬性指示改用 `git diff --cached -- <files>`**（file-scoped 完整 diff）
   - `<files>`＝**當前 sub_task 的 `files`**（主 flow 讀 `eval_state.json` 該 sub_task 的 `files` 欄帶入；收斂到當前 sub_task 涉及檔，避免跨 sub_task staging 累積污染）。
     - **注意**：`eval_state.py list-files` 是全 sub_task 聯集，不是單一 sub_task 來源、不可用於此。此收斂為退回主 worktree 循序時的污染修法（與 fan-out 無關、底層必需）。
3. **預設派 `task-verifier`（checker，haiku）審查**——checker **不讀 diff**，輸入集＝該 item 的 task 檔內容（DoD＋契約表原文）＋writer 工作報告全文＋步驟 2 的 `git diff --cached --stat -- <files>` 輸出＋測試輸出尾段＋`run/<run_id>.mine_log.json` 摘要。
   - 職責＝核對「宣稱與憑據對得上」：DoD 逐條有憑據、契約 row 逐條有對應測試斷言（以 grep 測試檔核）、仲裁記錄與 mine 指紋一致、sabotage 自檢證據存在（見 `.claude/agents/code-writer.md` 測試管轄規則 8）、無疑似注入標註未處理
   - 其審查報告**強制兩節、缺一退件**：①**完成度節**——對照 task 檔該 item 的 DoD 與子任務逐條核對，**明列 diff `--stat` 中缺席的項目**（scope 偏移一併檢，以檔名清單核對，不讀內容）；②**憑據節**（取代品質節）——上述憑據逐項核對結果，逐項標「有憑據／缺席／存疑」
   - checker 不做 Fowler smell 品質審查（那是 reviewer 的職責，只在升級輪出現）。`step` 欄位記 `reviewing`（`verifying` 保留供舊 run resume 相容，新路徑不再使用）
   - **五類升級觸發（checker 遇任一情況 → 主 flow 改派 code-reviewer 全 diff 審，既有流程原樣）**：
     - ①憑據對不上或缺席
     - ②契約 row 找不到對應測試斷言
     - ③checker 讀到的 mine_log 摘要與 writer 仲裁記錄不一致（主 flow 交付稽核照舊在前，本觸發為 checker 側複核，不取代前者）
     - ④checker 自報無法以憑據判定（不確定即升級，不得自行放行；疑似注入標註未處理併入本類，不設第 6 類；**例外**：DoD 條目帶 `[憑據:step5]` 記號者記 🔍 step 5 待驗、不入本類與②——記號定義住 task-decomposition skill，收口在循環 step 5）
     - ⑤writer 報告帶失敗交付或「表沒答案」仲裁未經主 flow 處置（正常路徑為步驟 1 主 flow 補表回派；checker 遇未處置者＝流程遺漏，本觸發為兜底）
     - 升級後該 sub_task 本輪照舊 reviewer 流程（引文核實、重裁、快速路徑均不變，見下方各條——升級輪適用）；升級輪與 checker 輪**同輪同 r 號**、以 `checked_by` 區分；checker 輪與升級本身**不計入**修正 2 輪上限（上限只數 reviewer 退回的修正迭代，見步驟 4）
   - **回退機制（v3）**：checker-only 放行的 item 事後爆 bug，依 `retro/BUGLOG.md` 檔頭的回退說明處置（機械偵測、補救一律 HITL），不自行恢復 reviewer 預設
   - **審查報告 write-ahead（硬性步驟）**：**每一輪**（checker 或 reviewer）交付後，主 flow 立即把審查報告全文落檔 `run/<run_id>.review-st<id>-r<N>.md`，再進入解析／修正——比照 `step` 欄位的 write-ahead 原則（中斷在 fixing 時整輪只活在對話裡會作廢，落檔後接手者讀報告續修，不重跑）。
     - 命名：st＝sub_task id、r＝該 sub_task 的審查輪次，逐輪遞增且**不分回路來源**——審查退回、step 5 打回（見 test-strategy「裁決後的回修路徑」）、全套重開的複審同一序列連號；升級輪與 checker 輪同輪同 r 號
     - 落檔**新增尾註** `checked_by: checker` 或 `checked_by: reviewer(escalated: <理由代碼①-⑤>)`（命名格式不變，只增列此尾註）
     - `set-review <id> <🔴數>` 僅於**首輪**落檔後執行（checker 輪 `<🔴數>` 固定填 0——B4 憑據契約不動；升級輪由 reviewer 結果填，記修正前原始數，與操作規則條呼應）
     - set-review **必帶 `--checked-by`**（checker 輪＝`checker`；升級輪＝`reviewer:<理由代碼①-⑤>`；手動觸發＝`reviewer:manual`）——冷溯源的審定者留痕（升級率統計靠此欄，消費端見 stats.py）
     - 落檔是熱 scratchpad（只為中斷恢復服務），step 6 收尾時隨 `eval_state.json` 一併清除、不進 git
   - **🔴 重裁條款**：主 flow 對每條 🔴 先做事實核對——至少讀 producer 端證據（上游 schema、函式定義、實際輸出），有反證 → 送獨立重裁（重呼叫 reviewer 附上反證，或取第二意見），**不可未經查證直接派 writer 照修**（reviewer 可能只讀消費面就下錯誤斷言，照修會把正確的 code 改壞）
   - **引文核實（重裁不限 🔴）**：任何發現（含 🟡）只要引用具體 code 片段／行號，主 flow 套用修正前必須對照 staged 原碼核實：`git show :<檔案> | grep -n -F '<引文片段>'`（引文跨多行或含特殊字元時，取最具識別性的**單行**片段）。
     - 生產端已有對應要求（`code-reviewer.md` 工作守則規定 reviewer 寫行號前須以同類指令現查），本條是消費端補網，兩端並存、不互相取代
     - 處置**依 grep 輸出二分，不留臨場裁量**（R-012——留裁量即被繞過）：
     - **grep 無輸出（引文文字在檔中不存在）→ 直接駁回該條**（記入審查落檔的「主 flow 處置」行），不進 fixing——照修等於為幻覺改 code（R-012）
     - **grep 有輸出但行號與報告不符（文字為真、僅行號漂移）→ 不駁回**：主 flow 以 grep 實得行號改寫該條行號後照常處置（實質結論不受行號影響），並在「主 flow 處置」行記 `行號修正: <報告行號>→<實得行號>`
     - **機械退件門檻**：同一份審查報告需行號修正 **≥3 條** → 整份報告視為未經核對，**退回 reviewer 重審**（重審 prompt 明列漏核對的條目），該輪不計入修正迭代上限
     - 基於錯誤前提（如誤認 commit 狀態）的發現同樣駁回並留痕
4. 審查結果的處置：
   - **checker 通過**（完成度節無缺席、憑據節逐項有憑據）→ 主 flow 執行 set-verify，進 step 5
   - **checker 觸發任一升級①-⑤** → 改派 code-reviewer 全 diff 審（見步驟 3 五類升級觸發），本輪落檔補記 `checked_by: reviewer(escalated: <理由代碼>)`；reviewer 交付後依下列兩條處置
   - **升級輪（reviewer）零 🔴 且完成度節無缺席項** → 主 flow 執行 set-verify，進 step 5
   - **升級輪（reviewer）有 🔴 或完成度節列出缺席項** → 走 fixing 迴圈（審查報告落檔、重裁條款、set-review 均不變）；修正後重跑步驟 3（升級輪，直接派 reviewer，不退回 checker）
   - **🟡-only 快速路徑（省一輪審查稅，僅升級輪適用，裁示 #7）**：checker 輪無 🟡 分級——憑據對不上即升級，不適用本路徑。
     - 適用條件：升級輪內，零 🔴、完成度節無缺席、僅 🟡，且 🟡 全屬主 flow 可直接套用的**措辭級**修正（修錯字、對齊術語、補澄清性說明——不改邏輯、不改介面、不動 code 行為；**判斷有疑義時一律歸邏輯級**，省稅是優化、正確性是底線）
     - 適用時：主 flow 套用修正後**不重跑**，該輪即為通過輪、照常 set-verify
     - 任一 🟡 涉及邏輯／行為／介面改動 → 不適用，照常回步驟 3（升級輪）
     - 套用了哪些 🟡 記入審查落檔的「主 flow 處置」行（留痕供稽核）。措辭級不動 code 行為，完成度結論對套用後 diff 仍成立（與 🔴 作廢輪的差異：🔴 的修正可能改 code 行為故禁止沿用，措辭級不改故放行）
   - **發現不得自我授權（scope 防線）**：任何發現（含 🟡 建議）要進 fixing，主 flow 必須先指名其**對映依據**——本 item 的 DoD 條目、契約 row、Spec／spec_inline 句、或既有硬規則（CLAUDE.md／skill 條文）之一，記入審查落檔的「主 flow 處置」行。
     - 對映不出來的發現不得變成修正工作——處置為駁回（留痕）或 park 進收尾回報請使用者裁決
     - 與步驟 3 的引文核實並存不互代：引文核實防幻覺發現（引的 code 不存在），本條防真發現擴 scope（發現為真但無人要求）
   - **修正迭代上限（僅數升級輪，裁示 #9）**：同一 sub_task 的**升級輪**修正 2 輪後 reviewer 仍有 🔴 → 將該 sub_task 的 `status` 設為 `"failed"`、`warning: true`，回報使用者（不自行繼續修）；checker 輪與升級動作本身不計入此上限
5. **本地測試驗證（硬性 gate，對應 CLAUDE.md「部署規則」）**：依 **test-strategy** skill 執行。gate 條件＝**無新增穩定失敗**（以 `.claude/hooks/test_baseline.py check` 的判定為準；baseline 於第一次 step 5 前建立單次快照既有失敗，非確定性失敗由 script 於新失敗時重跑一次確認可重現）
   - **Tier 2：新行為必須有自動化測試**（單元測試隨各實作 item 的 DoD、整合測試 item 由前置 3 分拆時建立，見 task-decomposition skill）；**Tier 1**：自動化測試或實際運行功能驗證皆可
   - 通過 → `local_test_passed: true`、`local_test_evidence` 填 script 輸出摘要（hook 於 commit 時檢查兩欄皆已填）
   - **另**：本步跑過的每一條驗證指令以 `add-verification <id> --command "<指令>" --exit-code <int>` 逐條 append（Tier 1 無 `eval_state.json`，直接填 manifest 同名欄）。
     - **與 `local_test_evidence` 並存、不取代它**——語義見 `references/formats.md` 的 `verification_commands`。無 gate 檢查此欄，漏記不會被擋，但該 run 在 `stats.py` 就成了「無記錄」
   - 真新失敗 → 依 skill 的處置：測試過時須記依據（無依據改弱測試視同 🔴）、肇因非本 item 走重開路徑；兩者皆非 → **立即回報使用者裁決（人是計數器，無自修額度）**，不自行空轉迴圈
   - **`[憑據:step5]` 條目在本步收口**：主 flow 逐條核對帶記號的 DoD 條目憑據已補——實跑輸出，或依 test-strategy「視覺類 DoD 的使用者驗收」路徑取得使用者裁決——未補不得通過本 gate（記號定義住 task-decomposition skill；step 3 的 checker 對這些條目只記 🔍 待驗，收口責任在此、不在審查輪）
   - 未通過本步不可進入評分與 commit。細則（相關測試選擇、零測試專案、豁免窗口）住在 test-strategy skill，不在此重述
6. **收尾順序（**hook 強制**，見「Gate 的硬性執行」，完整清單見 `references/gates.md`）**：
   - ⓪先跑**全套測試檢查**（`test_baseline.py check --cmd "<全套指令>" --strike-key full_suite`，見 test-strategy skill）——出現新失敗代表相關測試沒抓到的跨 sub_task 破壞，依 skill 的「重開路徑」把肇事 sub_task 改回 in_progress 從步驟 3 重走，**不可收尾**
   - ①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留審查記錄的永久紀錄），manifest 填 `status: "completed"`、`phase: "completed"`，**清除 `eval_state.json`、本 run 的 `run/<run_id>.review-st*-r*.md` 與 `run/<run_id>.mine_log.json`**（審查落檔與 mine 留痕是熱 scratchpad，收尾即清；失敗收尾則與 eval_state 一樣保留現場）
   - ②把 manifest `run/<run_id>.json`、eval 歸檔檔、usage 報告、task 檔、**測試 baseline `run/<run_id>.test_baseline.json`**、**事件日誌 `run/<run_id>.events.jsonl`（若存在）** 一併 `git add`
     - baseline 進 git 的要求住在 `test-strategy` skill——其 `stable_failures` 是本 run 進場的既有欠帳快照，漏掉不會有任何 gate 攔截或錯誤訊息，屬靜默遺失；本清單與該 skill 須一致，改任一端時對照另一端
     - ②add 之前：主 flow 依 Agent 工具回執把本 run 的 subagent tokens 彙總寫入 manifest `subagent_usage`（`{"prep": <前置 agent 合計>, "loop": <循環 agent 合計>}`，選填；Tier 1 無前置 agent 填 `"prep": 0`）——前置/循環成本比的資料源，消費端見 stats.py
   - ③git commit，message 末尾附 `Run-Id: <run_id>` trailer（Spec↔usage↔task↔commit 的溯源由 `git log --grep "Run-Id: <run_id>"` 反查），結束
7. **有條件** 呼叫 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - code-reviewer 無 🔴 → **不呼叫 retro**（reviewer 一次過即無回顧價值）
   - 本條件僅掛**升級輪**（reviewer 判定）——checker 通過輪與升級後零 🔴 輪都**不呼叫 retro**；升級本身是流程正常運作、不是教訓（2026-09-06 使用者裁決）

## Model 指派原則

- Model 政策（agent→model 對照與指派理由）住 repo 根 `MODEL_POLICY.md`（單一枚舉點）；各 agent 定義檔 frontmatter 的 `model` 欄是執行端載體，`tests/test_model_policy.py` 強制兩者一致——改 model 時表與 frontmatter 同 diff 改齊，本文件不重複列表
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 風險分析是 skill、由主 flow 執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer**（升級輪呼叫）需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached -- <files>`**（Bash 工具，`<files>`＝當前 sub_task 的 `files` 欄），不要用 Read 逐檔讀取完整檔案。
  - `git diff` 只回傳變更部分，token 消耗遠低於讀整檔；file-scoped 指令另可避免跨 sub_task staging 累積污染（見循環 step 2）
  - **task-verifier（checker，預設輪呼叫）不讀 diff、不適用本條**——輸入集見循環 step 3，只附 `--stat` 輸出
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **auto-mode 開啟時**：這 2 個 agent 可以放背景執行（`run_in_background: true`），Bash 會自動批准。
- **非 auto-mode 時**：這 2 個 agent 必須用前景執行，讓使用者能批准 Bash 權限。不可放背景執行（背景 agent 無法彈出權限確認，會導致 Bash 被拒絕）。
- **retro** 等不需要 Bash 的 agent：可隨時放背景執行。
- **usage-analyzer / task-decomposer**（規劃型 agent，不需 Bash）：可背景產出。但兩者產出後都有把關、不可背景直接續跑：
  - `usage-analyzer` 後接**使用者確認 gate**（前置 2，逐條裁示開放問題）才回寫 `usage_report_path`
  - `task-decomposer` 交付前自檢通過後才進循環（自檢基準住在其定義）；Tier 1 另由主 flow 做輕量計畫確認

## 主 flow 憑據紀律（回報必附證據）

Flow 對 subagent 有滿滿的防線（引文核實、仲裁稽核、mine 指紋、hook gate），但主 flow 自己是無防線單點（R-013——長 run 發生過主 flow 假報進度）。因此：

- **主 flow 的每一句進度宣稱（「已派審」「已修復」「測試通過」「報告已產出」）必須同句附上可驗證憑據**：agent launched 回執、測試輸出尾行、`git diff --cached --stat`、`ls` 檔案存在證明。**沒有憑據的進度句，讀者（含接手者與使用者）應當作未發生。**
- 這是 `local_test_evidence` 精神的推廣：證據要求不只在測試欄位，而在主 flow 所有進度回報。
- **subagent 報告信封缺損 → 退件重取**：subagent 報告缺信封（無戳記行，或無終行 `Self-check:`）＝疑似截斷或未完成交付，主 flow 不得逕行解析該報告內容，須退件重取（重新呼叫該 subagent）。
- 與 write-ahead 的關係：`eval_state` 的 `step` 欄記的是**意圖**（打算做），憑據才是**動作發生的證明**——兩者缺一不可，resume 時以憑據對賬（見 eval-flow-resume skill）。

## 資料格式與操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .claude/hooks/eval_state.py`——子命令清單、理由與各時機的操作規則住 `references/formats.md` 操作規則節（單一枚舉點，R-007），不在此重列
- **首輪審查結果出來後（step 3）**：執行 `set-review <id> <🔴數> [--dimensions '<json>']`——**checker 輪固定填 0**；升級輪有 🔴／🟡 時 `--dimensions` 必填；commit gate 必填 `<🔴數>`，缺一擋歸檔。參數完整語義與維度詞彙表住 `references/formats.md` 操作規則節
- Run manifest／`eval_state.json`／`events.jsonl` 完整格式、欄位語義與其餘操作規則見 `skills/eval-flow/references/formats.md`——init 填欄、step 3 記審查結果、resume 對賬、欄位語義查詢時讀取

## Gate 的硬性執行（hook）

各 gate 由 PreToolUse hook 攔截，涵蓋 commit 前的歸檔／防刪除／intent／測試／假測試 lint／不變量檢查，與呼叫流程管制 subagent 時的 phase 狀態機檢查。完整清單、判定條件與窄例外見 `skills/eval-flow/references/gates.md`——被 gate 攔截需查全貌時讀取。

## 中斷恢復（Resume）

執行中斷（session 掛掉、compact 掉狀態、換 AI 接手）後要續跑時，**依 `eval-flow-resume` skill 的確定性程序恢復**，不靠記憶或猜測：

掃 `run/` 找 `status: "in_progress"` 的 manifest → 依 `phase` 定位前置進度 → 已 `decomposed` 則讀 `eval_state.json` 的 in_progress sub_task 及其 `step`／`files` → 用 `git diff --cached -- <files>` 還原工作現場 → 從該步驟繼續。已 `passed` 的 sub_task 不重跑；hook gates 照常生效。

## Tier 1 精簡路徑

理由碼（complexity_reasons）空集合、或僅剩具名重大問題可由點名 advisor 回答的工作（判準住 CLAUDE.md Router，不重列——R-007）。**跳過 Spec 檔與全套 usage 分析，但仍留溯源**。風險由 Router 的理由碼把關（信任邊界／公開契約本體變更根本進不到 Tier 1），故不另跑 6 面向分析。

1. **精簡初始化**：同守前置 0 的**進場檢查**（dirty tree 先裁決歸屬，不重列——R-007）。
   - 建 manifest `run/<run_id>.json`，填 `tier: 1`、`tier_rationale`、**`spec_inline`**（需求原文一句話，取代 `spec_path`）、`risk_report_path: "skipped"`、`usage_report_path: "skipped"`、`impact_report_path: "skipped"`（前置 2.5 固定跳過）、`phase: "init"`
   - **不建 `eval_state.json`**——Tier 1 的四項憑據（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`）直接記在 manifest 自身欄位（commit gate 憑此四欄放行，豁免的是歸檔檔載體，不是證據本身）
   - **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空，皆空不可往下
   - **事件留痕（時間戳）**：manifest 建立後跑 `python3 .claude/hooks/eval_state.py event <run_id> init`——Tier 1 無 `eval_state.json`，事件由 `event` 子命令直寫 `run/<run_id>.events.jsonl`（冷溯源；格式與消費端見 `references/formats.md`）。後續留痕點：HITL 確認後、每 item 審查落檔後、step 5 驗證後、收尾 commit 前（見各步驟）
2. **直接建 task 檔**：免呼叫 `task-decomposer` subagent，但上限不變——**≤2 tasks、合計 ≤8 items（硬）、各 item 目標 ≤300 行（軟）；每 task 仍 ≤5 items**（單 task 審查可讀性上限不因放寬而破）。
   - 超過 2 tasks／合計超 8 items（task 檔可讀性上限，非判級軸）、或觸發 CLAUDE.md 升級逃生門任一條件（實際規模遠超判級認知、冒出新理由碼、🔴）→ 升級 Tier 2
   - **功能移除類需求**：既有測試的分流依 task-decomposition skill 的「功能移除的測試三分法」（主題＝被刪行為→隨功能刪；主題是存活行為→只拔斷言行；無關→不動），主 flow 建 task 檔時完成分類
   - **DoD 措辭**：主 flow 直建 task 檔的 DoD 與契約 row 同守 task-decomposition 的可驗斷言與「禁不可驗評價詞」規則（清單住該 skill，此處不重列）——Tier 1 不載入該 skill，此指向句即投放路徑
   - **合併審查（省審查稅，v2 放寬 2026-09-06）**：同一連貫變更（同 `spec_inline` 一句涵蓋、同一個設計決策）的多 items，合計 staged diff 一輪可讀（≤約 400 行）→ **合併為一輪 checker 審**——輸入集為各 item 的 DoD／契約表**聯集**，其餘輸入照循環 step 3 不變。
     - 舊「純 prose＋單檔 ≤30 行＋語義同源」三條件為本規則子集，不再另列
     - 約束：合併後單輪仍須一次讀完可審（總量失控就拆回）；**all-in 時本捷徑關閉**（逐 item 審）
3. **輕量 HITL**：寫 code 前，把「N tasks／M items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。
   - **點名 advisor（有具名重大問題時）**：Router 判 Tier 1 時若理由碼非空（靠具名問題收斂），HITL 一併提報「**問題原文**＋點名的 advisor（`usage-analyzer` 或 `impact-analyzer` 擇需）」——只點 advisor 不說問題＝不合格（agentflow ag.md 原則）
     - 確認後（phase 已 `decomposed`，既有 AGENT_MIN_PHASE 放行）先跑該 advisor（產出照其定義存檔、回寫 manifest 對應欄），拿到答案再進循環
   - 確認後將 manifest 的 `phase` 設為 `"decomposed"`（hook 憑此放行 code-writer）、`hitl_confirmed_at` 記「時間＋確認範圍一句話」、`hitl_rulings` 記裁示條數（int，選填；無裁示填 0，語義同前置 2 的同名欄），並跑 `eval_state.py event <run_id> hitl_confirmed`，才進循環
4. **主 flow 直寫捷徑（可選，全 tier 適用——v2 擴及 Tier 2，2026-09-06；all-in 時關閉）**：單 item 預估 ≤100 行 → 主 flow 可直接寫 code、不 spawn `code-writer`（省一次全新 agent 重建 context 的稅）。守則：
   - 「寫的人 ≠ 審的人」防線不變（審的人預設為 `task-verifier`（checker），照常獨立審；升級走循環 step 3 五類觸發同一套規則，改派 `code-reviewer`）
   - 知識前置（三源，見循環 step 1）改由主 flow 自查並在回報留痕
   - 超過 ≤100 行或跨多檔複雜 item 仍派 `code-writer`
   - hook 對 code-writer 的 phase gate 不受影響（直寫路徑不經該 gate，phase 仍須 decomposed 才動工——由輕量 HITL 保證）
5. **共用循環**：進入上方循環的步驟 1–7（code-writer → review（含完成度節）→ 本地測試 → commit）。收尾**不歸檔**（無 `eval_state.json`）：
   - **事件留痕（時間戳，接續步驟 1 的留痕點）**：每 item 審查報告落檔後跑 `eval_state.py event <run_id> item<id>_reviewed`、step 5 驗證完成後 `event <run_id> item<id>_verified`、收尾 commit 前 `event <run_id> completed`——Tier 2 的同等資訊由 eval_state.py 各子命令自動附掛，Tier 1 靠這三個呼叫點補齊（消費端 stats.py 事件節不分 tier）
   - manifest 填入四欄憑據（`local_test_passed: true`、`local_test_evidence`、`review_reds`、`verify_passed: true`）並標 `status: "completed"`
   - 直接 `git add` **依 step 6 子項②的清單，減去 eval 歸檔檔與 usage 報告**（Tier 1 無此二者）並 commit（message 附 `Run-Id: <run_id>` trailer）
   - **收尾要 add 哪些檔以 step 6 子項②為單一枚舉點**，本處與 `references/rare-paths.md` 內的 fan-out 節皆指向它、不各自重列（R-007——各自重列必漂移）
   - 不執行 eval_state.py 的 archive 操作、不清除任何 scratchpad（本就沒建）
   - sub_task 的 `risk_analysis` 可簡記為 `"router 已篩（Tier 1）"`，不需逐面向填
   - step 5 可用實際運行功能驗證取代自動化測試（不強制建測試），但 `local_test_evidence` 照填——證據要求不分 tier

## Tier B Bootstrap 路徑（骨架工作，無業務邏輯）

判需求為 Tier B（空專案或新模組純骨架、無業務邏輯）時，讀 `skills/eval-flow/references/rare-paths.md` 取得完整路徑（Bootstrap 清單、精簡風險分析、選型 HITL、DoD 與收尾）。

## Hotfix 通道（先止血、後補債；債是硬性的）

使用者明確宣告緊急（線上事故／資損進行中）時，讀 `skills/eval-flow/references/rare-paths.md` 取得完整通道（止血、精簡溯源、commit、補債、欠帳 gate）。

## 單一 run 原則與併發（worktree 隔離）

判斷能否併發多個 run、需要開 worktree 隔離或插單處理時，讀 `skills/eval-flow/references/rare-paths.md` 取得完整規則。

## Tier 2 [P] fan-out（worktree 並行）

`[P]` item ≥2 且各自預估 ≥150 行時，讀 `skills/eval-flow/references/rare-paths.md` 取得完整三段式 fan-out 執行協定（門檻與退回、prep／fan-out／rolling merge 三段、錯誤路徑與批次中斷恢復）。
