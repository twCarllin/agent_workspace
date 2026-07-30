---
name: eval-flow
description: Eval Flow 的完整執行細節：Tier 2 前置 0–3（初始化、風險分析、使用情境、分拆 task）、循環步驟 1–7（code-writer → review（含完成度節）→ 本地測試 → commit）、Tier 1 精簡路徑、run manifest 與 eval_state.json 格式與操作規則、hook gate 清單。觸發語：Router 判定需求為 Tier 1 或 Tier 2 時（執行前必須載入本 skill）、「跑 Eval Flow」、「照流程實作這個需求」。不適用於：Tier 0 微調（直接改，不建任何檔）、非實作類的問答。
---

# Eval Flow（Tier 1／2 執行細節）

> 本 skill 由主 flow 在 Router 判定 **Tier 1 或 Tier 2** 後載入執行。Router 分級表與防濫用規則住在 CLAUDE.md，不在此重述。Tier 2 走完整路徑（前置 0–3 ＋循環）；Tier 1 走文末「Tier 1 精簡路徑」（跳過部分前置，共用循環）。

## Tier 2 完整路徑

當一個需求被 Router 判為 **Tier 2**（需實作的完整 Spec）時，執行以下流程。**Model 不在 flow 層級統一指定**，由每個 agent 依任務性質自行決定（見下「Model 指派原則」）。

### 前置 0：初始化（進入點，必須是第一個動作）

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
- **只寫觸及的面向**：有風險者標註等級（🔴 重大 / 🟡 中等 / 🟢 輕微）並寫風險描述與對策；與本任務無關者不逐節填寫，改在報告開頭以一行 `不適用：<面向清單>` 帶過。**面向未寫不等於已評估為無風險——判為不適用者仍須列名，漏列即視同未做**（六面向須全部出現在「有風險節」或「不適用」行之一）
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
- **flow 層級 gate**：報告需經**使用者確認**；未確認前不進入前置 3（usage-analyzer 在確認後才回寫 `manifest.usage_report_path`，並將 `phase` 更新為 `"usage_confirmed"`）。確認當下主 flow 把「時間＋確認範圍一句話」寫入 manifest 的 `hitl_confirmed_at`（留痕，接手者可驗證）。

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
   - **知識前置（硬性步驟）**：呼叫前，主 flow 把三個來源的相關內容**原文貼進 writer prompt 的硬性約束區**——不是叫 writer「自己去讀」。實測：writer 讀了 retro、檔頭還引用教訓，仍寫出一模一樣的問題模式；知識只有以明文約束前置進 prompt 才有效。三源：
     - **retro 條目**：先以本 item `files` 的模組路徑 grep `retro/RETRO.md` 的標籤篩選（標籤第一段＝模組路徑，見 retro agent 規範），主 flow 再補判同類操作／同類風險面的條目
     - **模組 conventions**：本 item 觸及模組的子目錄 `CLAUDE.md`（存在則摘錄相關段）
     - **impact report 慣例段**：前置 2.5 有跑時，摘錄該模組的「各模組既有慣例」與「可重用既有元件」節（節名見 impact-analyzer 定義）
     - grep 篩選的對象是**模組名片段**（取自 files 路徑的目錄／檔名，如 `eval_gates`、`hooks`），不是整段路徑——retro 標籤慣用全形 `／`，整段半形路徑會靜默零命中
     - 三源皆無相關內容時在 prompt 註明「知識前置：三源均無相關內容」（留痕，防跳步）
   - **測試管轄註記**：派工 prompt 附一句「測試自驗只准跑 `python3 .claude/hooks/test_baseline.py mine --strike-key sub_task_<id>`，依你定義中的測試管轄規則」（writer 層 mine 模式細節住 test-strategy skill，不重述；`[P]` item 在 fan-out（各開 worktree）或循序退回下 mine 模式均適用——隔離樹或逐個執行時未提交變更範圍可正確推導，不再需要「指定測試檔清單」舊 workaround）
   - **契約前置與仲裁句（硬性）**：派工 prompt 必須把本 item 的**行為契約表原文**（task 檔的 `契約:` 行，含邊界 row）貼進硬約束區作為仲裁基準——不是叫 writer 自己翻 task 檔（與知識前置同一教訓），並附一句：「測試紅時先仲裁再動手，對到契約表 row 判哪邊錯；**契約表沒答案 → 帶失敗交付是正確行為，硬湊綠燈才是違規**」。無契約表的 item（Tier 1 無表 fallback）此句改指 DoD。writer 以「表沒答案」帶失敗交付時，**主 flow 裁決**：讀 Spec／usage 報告判該行為的預期，把裁決結果補進契約表（表可增補、single source 不變）再回派；Spec 本身有洞才走升級逃生門問使用者
   - **交付稽核（writer 交付時，兩個對照）**：①工作報告的「仲裁記錄」——紅過的測試每條都要有仲裁行，判「測試超出契約」者核對 row 引文與 task 檔原文一致（對不上＝假仲裁，退件）；②`run/<run_id>.mine_log.json`——mine 執行次數異常多、測試檔 hash 在失敗未清的情況下反覆變動、失敗集合遊走＝「改測試湊綠」的機器指紋，退件重派並要求逐條補仲裁依據。正常交付（次數合理、記錄對得上）瞄一眼即過，不展開
2. 將變更檔案 `git add` 進 staging area（確保 code-reviewer 可透過 `git diff --cached` 讀取）。**派 code-reviewer 時，prompt 硬性指示改用 `git diff --cached -- <files>`**，`<files>`＝**當前 sub_task 的 `files`**（主 flow 讀 `eval_state.json` 該 sub_task 的 `files` 欄帶入；收斂到當前 sub_task 涉及檔，避免跨 sub_task staging 累積污染）。**注意**：`eval_state.py list-files` 是全 sub_task 聯集，不是單一 sub_task 來源、不可用於此。此收斂為退回主 worktree 循序時的污染修法（與 fan-out 無關、底層必需）。
3. 呼叫 `code-reviewer`（唯讀、讀 staged diff），其審查報告**強制兩節、缺一退件**：①**完成度節**——對照 task 檔該 item 的 DoD 與子任務逐條核對，**明列 diff 中缺席的項目**（scope 偏移一併檢）；②**品質節**——既有五大範疇審查（做的東西會怎麼壞）。機械可驗的 DoD（grep／指令斷言）由主 flow 直驗留痕、不佔 agent。`step` 欄位記 `reviewing`（`verifying` 保留供舊 run resume 相容，新路徑不再使用）
   - **task-verifier 已自動迴圈退役（2026-07-25）**：兩個長 run 實測 0 個獨有發現、1 次誤報、佔 1/3 token，完成度檢查併入 reviewer 完成度節。agent 定義保留供手動觸發。**回退條件**：「漏做的 DoD 逃過完成度節、進了 commit」寫入 BUGLOG 且命中第 2 次 → 恢復獨立 verifier 每輪派遣
   - **審查報告 write-ahead（硬性步驟）**：**每一輪** code-reviewer 交付後，主 flow 立即把審查報告全文落檔 `run/<run_id>.review-st<id>-r<N>.md`（st＝sub_task id、r＝該 sub_task 的審查輪次，逐輪遞增），再進入解析／修正——比照 `step` 欄位的 write-ahead 原則（中斷在 fixing 時整輪 reviewer 只活在對話裡會作廢，落檔後接手者讀報告續修，不重跑 reviewer）。`set-review <id> <🔴數>` 僅於**首輪**落檔後執行（記修正前原始數，與操作規則條呼應）。落檔是熱 scratchpad（只為中斷恢復服務），step 6 收尾時隨 `eval_state.json` 一併清除、不進 git
   - **🔴 重裁條款**：主 flow 對每條 🔴 先做事實核對——至少讀 producer 端證據（上游 schema、函式定義、實際輸出），有反證 → 送獨立重裁（重呼叫 reviewer 附上反證，或取第二意見），**不可未經查證直接派 writer 照修**（reviewer 可能只讀消費面就下錯誤斷言，照修會把正確的 code 改壞）
   - **引文核實（重裁不限 🔴）**：任何發現（含 🟡）只要引用具體 code 片段／行號，主 flow 套用修正前必須對照 staged 原碼核實——**引文或行號與檔案不符 → 直接駁回該條**（記入審查落檔的「主 flow 處置」行），不進 fixing（實測：reviewer 讀大 diff 會混淆記憶，引用不存在的寫法判 🟡；照修等於為幻覺改 code）。基於錯誤前提（如誤認 commit 狀態）的發現同樣駁回並留痕
4. 審查結果的處置：
   - **零 🔴 且完成度節無缺席項** → 主 flow 執行 set-verify，進 step 5
   - **有 🔴 或完成度節列出缺席項** → 走 fixing 迴圈（審查報告落檔、重裁條款、set-review 均不變）；修正後重跑步驟 3
   - **🟡-only 快速路徑（省一輪審查稅）**：零 🔴、完成度節無缺席、僅 🟡，且 🟡 全屬主 flow 可直接套用的**措辭級**修正（修錯字、對齊術語、補澄清性說明——不改邏輯、不改介面、不動 code 行為；**判斷有疑義時一律歸邏輯級**，省稅是優化、正確性是底線）→ 主 flow 套用修正後**不重跑**，該輪即為通過輪、照常 set-verify。任一 🟡 涉及邏輯／行為／介面改動 → 不適用，照常回步驟 3。套用了哪些 🟡 記入審查落檔的「主 flow 處置」行（留痕供稽核）。措辭級不動 code 行為，完成度結論對套用後 diff 仍成立（與 🔴 作廢輪的差異：🔴 的修正可能改 code 行為故禁止沿用，措辭級不改故放行）
   - **修正迭代上限**：同一 sub_task 修正 2 輪後 reviewer 仍有 🔴 → 將該 sub_task 的 `status` 設為 `"failed"`、`warning: true`，回報使用者（不自行繼續修）
5. **本地測試驗證（硬性 gate，對應 CLAUDE.md「部署規則」）**：依 **test-strategy** skill 執行。gate 條件＝**無新增穩定失敗**（以 `.claude/hooks/test_baseline.py check` 的判定為準；baseline 於第一次 step 5 前建立單次快照既有失敗，非確定性失敗由 script 於新失敗時重跑一次確認可重現）
   - **Tier 2：新行為必須有自動化測試**（單元測試隨各實作 item 的 DoD、整合測試 item 由前置 3 分拆時建立，見 task-decomposition skill）；**Tier 1**：自動化測試或實際運行功能驗證皆可
   - 通過 → `local_test_passed: true`、`local_test_evidence` 填 script 輸出摘要（hook 於 commit 時檢查兩欄皆已填）
   - 真新失敗 → 依 skill 的處置：測試過時須記依據（無依據改弱測試視同 🔴）、肇因非本 item 走重開路徑；兩者皆非 → **立即回報使用者裁決（人是計數器，無自修額度）**，不自行空轉迴圈
   - 未通過本步不可進入評分與 commit。細則（相關測試選擇、零測試專案、豁免窗口）住在 test-strategy skill，不在此重述
6. **收尾順序（**hook 強制**，見「Gate 的硬性執行」）**：⓪先跑**全套測試檢查**（`test_baseline.py check --cmd "<全套指令>" --strike-key full_suite`，見 test-strategy skill）——出現新失敗代表相關測試沒抓到的跨 sub_task 破壞，依 skill 的「重開路徑」把肇事 sub_task 改回 in_progress 從步驟 3 重走，**不可收尾** ①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留審查記錄的永久紀錄），manifest 填 `status: "completed"`、`phase: "completed"`，**清除 `eval_state.json`、本 run 的 `run/<run_id>.review-st*-r*.md` 與 `run/<run_id>.mine_log.json`**（審查落檔與 mine 留痕是熱 scratchpad，收尾即清；失敗收尾則與 eval_state 一樣保留現場） ②把 manifest `run/<run_id>.json`、eval 歸檔檔、usage 報告、task 檔一併 `git add` ③git commit，message 末尾附 `Run-Id: <run_id>` trailer（Spec↔usage↔task↔commit 的溯源由 `git log --grep "Run-Id: <run_id>"` 反查），結束
7. **有條件** 呼叫 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - code-reviewer 無 🔴 → **不呼叫 retro**（reviewer 一次過即無回顧價值）

## Model 指派原則

- Model 由各 agent 定義檔的 frontmatter `model` 欄指定（single source of truth），本文件不重複列表
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 風險分析是 skill、由主 flow 執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer**（含手動觸發的 task-verifier）需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached -- <files>`**（Bash 工具，`<files>`＝當前 sub_task 的 `files` 欄），不要用 Read 逐檔讀取完整檔案。`git diff` 只回傳變更部分，token 消耗遠低於讀整檔；file-scoped 指令另可避免跨 sub_task staging 累積污染（見循環 step 2）。
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **auto-mode 開啟時**：這 2 個 agent 可以放背景執行（`run_in_background: true`），Bash 會自動批准。
- **非 auto-mode 時**：這 2 個 agent 必須用前景執行，讓使用者能批准 Bash 權限。不可放背景執行（背景 agent 無法彈出權限確認，會導致 Bash 被拒絕）。
- **retro** 等不需要 Bash 的 agent：可隨時放背景執行。
- **usage-analyzer / task-decomposer**（規劃型 agent，不需 Bash）：可背景產出。但兩者產出後都有把關、不可背景直接續跑：
  - `usage-analyzer` 後接**使用者確認 gate**（前置 2，逐條裁示開放問題）才回寫 `usage_report_path`
  - `task-decomposer` 交付前自檢通過後才進循環（自檢基準住在其定義）；Tier 1 另由主 flow 做輕量計畫確認

## 主 flow 憑據紀律（回報必附證據）

Flow 對 subagent 有滿滿的防線（引文核實、仲裁稽核、mine 指紋、hook gate），但主 flow 自己是無防線單點——長 run 實測發生過主 flow 假報進度（寫了 step=reviewing 卻沒真的派 agent）。因此：

- **主 flow 的每一句進度宣稱（「已派審」「已修復」「測試通過」「報告已產出」）必須同句附上可驗證憑據**：agent launched 回執、測試輸出尾行、`git diff --cached --stat`、`ls` 檔案存在證明。**沒有憑據的進度句，讀者（含接手者與使用者）應當作未發生。**
- 這是 `local_test_evidence` 精神的推廣：證據要求不只在測試欄位，而在主 flow 所有進度回報。
- 與 write-ahead 的關係：`eval_state` 的 `step` 欄記的是**意圖**（打算做），憑據才是**動作發生的證明**——兩者缺一不可，resume 時以憑據對賬（見 eval-flow-resume skill）。

## Run Manifest 格式（`run/<run_id>.json`）

冷溯源檔。前置 0 建立，各前置步驟回填路徑，commit 時隨 code 進 git、**永不清除**。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "created_at": "2026-07-06 14:30",
  "framework_version": "2026.07.15",
  "tier": 2,
  "tier_rationale": "多角色 + 觸及金流 → 強制 Tier 2",
  "phase": "init | risk_done | usage_confirmed | decomposed | completed",
  "spec_path": "spec/2026-07-06-partial-settlement.md",
  "spec_inline": null,
  "test_command": null,
  "hitl_confirmed_at": null,
  "risk_report_path": null,
  "usage_report_path": null,
  "impact_report_path": null,
  "task_file": null,
  "status": "in_progress | completed | failed",
  "failed_reason": null,
  "local_test_passed": null,
  "local_test_evidence": null,
  "review_reds": null,
  "verify_passed": null
}
```

- `framework_version`：前置 0 從 `.claude/hooks/VERSION` 讀入——事後鑑識「這個 run 是在哪一版流程規則下跑的」（部署健檢用 `python3 .claude/hooks/doctor.py`）
- `hitl_rejections`：HITL gate 被使用者**打回**的累計次數（usage 報告退回重寫、計畫被否決都算）。打回當下 +1。與 `hitl_confirmed_at` 一起餵 `stats.py` 的打回率——趨近 0% 的人閘門是蓋章，候選降級
- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 6）。轉移時機：前置 0 建立 `"init"` → 前置 1 無 🔴 `"risk_done"` → 前置 2 使用者確認 `"usage_confirmed"` → 前置 3 審查通過 `"decomposed"` → step 6 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`。舊 manifest 無此欄時 hook 以 `task_file` / `usage_report_path` 推導（向後相容）
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）
- `test_command`：本專案的**全套測試指令**（test-strategy script 省略 `--cmd` 時的預設來源，single source of truth——保證 baseline 與 check 範圍一致）。前置 0 可先 `null`，**第一次 step 5 前必須寫入**；同專案的後續 run 沿用前一個 manifest 的值；Tier B 於 DoD 驗證時寫入
- `hitl_confirmed_at`：HITL gate 的留痕——使用者確認當下寫入「時間 ＋ 確認範圍一句話」（例：`"2026-07-15 14:30 — 確認 usage 報告 v1（3 情境、2 開放問題已裁示）"`；Tier 1 記輕量計畫確認：`"… — 確認 1 task／3 items 計畫"`）。resume／換手時，接手者憑此驗證確認 gate 真的過過，不只信 `phase` 欄位。Tier B 記選型確認
- `scout_report_path`：**已廢止**（前置 1.5 scout 已移除，蒐證職責併回 usage-analyzer／impact-analyzer 自掃）。舊 manifest 仍有此欄者不需回填移除——hook 對此欄無任何依賴，留著不影響任何 gate
- `usage_report_path`：Tier 2 前置 2 使用者確認後寫入（`null` → 不可分拆 task）；Tier 1 固定為 `"skipped"`
- `impact_report_path`：Tier 2 前置 2.5 impact-analyzer 產出後寫入路徑（或 `"skipped: <理由>"`）；Tier 1 固定為 `"skipped"`
- `task_file`：分拆／建 task 後寫入
- `status`：step 6 收尾時（commit 前）填 `"completed"`。manifest↔commit 的對應不記 `commit_sha`，改由 commit message 的 `Run-Id: <run_id>` trailer 反查（`git log --grep`）
- `failed_reason`：`status` 設為 `"failed"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼），讓接手者不用翻對話記錄
- `local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`：**Tier 1 專用憑據欄（豁免歸檔檔）**——Tier 1 不建 `eval_state.json`，這四欄直接寫在 manifest、commit gate 憑此四欄驗放行（語義與 `eval_state.json` 各 sub_task 同欄一致）。Tier 2 仍走歸檔檔路徑，此四欄在 Tier 2 manifest 無意義（可不填）
- `debt`：僅 hotfix 通道使用（見「Hotfix 通道」），記錄欠下的流程債，如 `["risk", "test", "retro"]`；還清一項移除一項，清空後才可啟動新 run（hook 強制）

## eval_state.json 格式

熱評分 scratchpad。靠 `run_id` 關聯 manifest；commit 後歸檔為 `run/<run_id>.eval.json` 再清除。

> 下方範例是**欄位形狀骨架**，數值為佔位符、非通過所有不變量的自洽樣本（例如 `review_reds: null` 配非空 `rounds`、全 0 的 `dimensions` 在真實歸檔檔中都會被 hook 擋）；合法組合見「操作規則」與「Gate 的硬性執行」。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "sub_tasks": [
    {
      "id": 1,
      "name": "子 task 名稱",
      "status": "passed | failed | in_progress",
      "step": "writing | reviewing | fixing | verifying | testing | done",
      "files": ["src/foo.ts", "src/bar.ts"],
      "warning": false,
      "local_test_passed": false,
      "local_test_evidence": null,
      "review_reds": null,
      "review_dimensions": null,
      "verify_passed": false,
      "risk_analysis": {
        "technical": "🟢 無風險 | 🟡 ... | 🔴 ...",
        "security": "...",
        "data": "...",
        "performance": "...",
        "deployment": "...",
        "business_maintenance": "...",
        "blocking": false
      }
    }
  ]
}
```

- `review_dimensions`：維度→問題數的字典（例 `{"Non-functional": 2}`）；null 表示零 🔴 無問題可標。五維詞彙：`Clarity`／`Completeness`／`Testability`／`Non-functional`／`Technical_constraints`。由主 flow 於 set-review 時以 `--dimensions` 寫入，供 stats.py 維度分佈遙測

## eval_state.json 操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .claude/hooks/eval_state.py`（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`list-files`／`archive`）。實測單一 run 手動 Edit 30+ 次是高錯誤面；helper 在寫入前驗證不變量（archive 驗全數 passed），錯誤在落盤前就擋下
- **前置 0（初始化）**：建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id` ＋ 空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **使用情境分析完成後 / 分拆 task 完成後**：`usage_report_path` 與 `task_file` 分別由 `usage-analyzer`、`task-decomposer` 於各自步驟回寫（時機與條件見 agent 定義）。前者為 `null` 時不可進入分拆 task
- **風險分析完成後**：將 6 大面向結果填入對應 sub_task 的 `risk_analysis`，若有 🔴 設 `blocking: true`，必須修正 Spec 後重新分析
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`（`writing`→`reviewing`（並發 review＋verify 階段）→`fixing`（有 🔴 時）→`testing`→`done`；`verifying`／`scoring` 為舊版 run 的相容值，新路徑不寫入），步驟完成後再更新為下一步。code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **首輪 code-reviewer 審查結果出來後（step 3）**：執行 `python3 .claude/hooks/eval_state.py set-review <id> <🔴數> [--dimensions '<json>']`——`<🔴數>` 記首輪 code-reviewer 的 🔴 原始數（修正前，有無 🔴 皆須執行）；`--dimensions` 為 reviewer 報告末尾的維度統計（維度→問題數，五維詞彙：Clarity／Completeness／Testability／Non-functional／Technical_constraints），有 🔴／🟡 時必填，供 stats.py 維度分佈遙測——commit gate 必填 `<🔴數>`，缺一擋歸檔
- **reviewer 完成度節通過且該輪零 🔴（step 4 放行、真正進 step 5 的輪次）**：執行 `python3 .claude/hooks/eval_state.py set-verify <id>`，將 `verify_passed` 設為 `true`——commit gate 必填，缺一擋歸檔。**語義（2026-07-25 起）**：`verify_passed` 記的是「reviewer 審查報告的完成度節通過（DoD 無缺席、scope 無偏移）」，不再對應獨立 task-verifier agent；hook gate 判定不變。有 🔴 的輪次**不得** set-verify（該輪修正可能改 code 行為）；與 `set-review` 記首輪原始數不同，`set-verify` 記的是**最終通過輪**
- **本地測試通過後（step 5）**：將該 sub_task 的 `local_test_passed` 設為 `true`、`local_test_evidence` 填入驗證證據（指令＋結果摘要；Tier 2 若更新過既有測試，一併註明 Spec／task 依據）。預設 `false`／`null`；hook 於 commit 時檢查歸檔檔中所有 sub_task 兩欄皆已填
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **同一 sub_task 修正 2 輪後 reviewer 仍有 🔴**：`status` 設為 `"failed"`，`warning` 設為 `true`，回報使用者（詳見循環 step 4 修正迭代上限）
- **全部完成且通過**：**先歸檔為 `run/<run_id>.eval.json`**（保留評分歷史與扣分原因）、清除 `eval_state.json`、manifest `status` 設為 `"completed"`，**再** commit（歸檔檔與 manifest 同批進 git；順序由 hook 強制——`eval_state.json` 尚存在時 commit 會被擋）
- **有任一 failed**：manifest 的 `status` 設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）。此時 hook 會擋下 Claude 端的任何 `git commit`（`eval_state.json` 尚存在），屬預期行為；使用者要部分 commit 可在自己的終端執行（hook 只攔 Claude 的 Bash 工具）

## Gate 的硬性執行（hook）

以下 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，設定於 `.claude/settings.json`，matcher `Bash|Task|Agent`）強制攔截，不再只靠文字約束。攔截點有二：Claude 執行 `git commit` 時（gate 1–5），與呼叫流程管制的 subagent 時（gate 6）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔；失敗收尾時也會擋，屬預期）
2. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `"completed"` → 擋
3. **測試 gate**：staged manifest 對應的 `run/<run_id>.eval.json` 未同批 staged、或其中任一 sub_task 非 `passed`／`local_test_passed` 非 `true`、或 `review_reds` 未留痕（非 int 或負數）／`verify_passed` 非 `true` → 擋（`verify_passed` 語義＝reviewer 完成度節通過，見操作規則）。**Tier 1 分支**：若 `run/<run_id>.eval.json` 未 staged，改驗 manifest 自身四欄（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`），全過放行、豁免歸檔檔；已 staged 時走原路徑（向後相容）
4. **假測試 lint gate**：staged 有 manifest（flow 收尾 commit）時，staged 的 Python 測試檔跑 `test_lint.py`，檢出 if-guard 藏斷言／無斷言／恆真斷言 → 擋（誤報以行尾 `# testlint: allow` 豁免並留痕，見 test-strategy skill）
5. **不變量驗證**：歸檔檔 `run_id` 與 manifest 不一致 → 擋
6. **phase 狀態機（subagent 呼叫攔截）**：依 `eval_state.json.run_id` 定位 manifest，檢查 `phase` 是否達到該 agent 的最低要求，未達 → 擋呼叫：
   - `usage-analyzer` 需 `phase >= risk_done`（前置 1 未完不可跑前置 2）
   - `task-decomposer` 需 `phase >= usage_confirmed` 且 `usage_report_path` 非空；為 `"skipped"`（Tier 1）也擋
   - `code-writer` 需 `phase >= decomposed` 且 `task_file` 非空；任一 sub_task `risk_analysis.blocking: true` 也擋
   - **共通前提**：intent gate 通過且 manifest 存在。`eval_state.json` 存在時依其 `run_id` 定位 manifest；**Tier 1 分支**：`eval_state.json` 不存在時，掃 `run/` 找唯一一個 `tier: 1` 且 `status: "in_progress"` 的 manifest 作為當前 run 依據（找到唯一一個 → 繼續後續 gate；找不到或多個 → 擋，原訊息語義）。`check_other_runs` 在兩條路徑下都執行（Tier 1 單一 run 原則不因豁免而失效）

被擋時 hook 會以 stderr 回報原因，依訊息補齊狀態後重試。流程中亦可隨時自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。hook 只攔 Claude 的 Bash 工具，不影響使用者自己終端的 git 操作。本 skill 對應條文為流程說明，實際防線以 hook 為準。

## 中斷恢復（Resume）

執行中斷（session 掛掉、compact 掉狀態、換 AI 接手）後要續跑時，**依 `eval-flow-resume` skill 的確定性程序恢復**，不靠記憶或猜測：掃 `run/` 找 `status: "in_progress"` 的 manifest → 依 `phase` 定位前置進度 → 已 `decomposed` 則讀 `eval_state.json` 的 in_progress sub_task 及其 `step`／`files` → 用 `git diff --cached -- <files>` 還原工作現場 → 從該步驟繼續。已 `passed` 的 sub_task 不重跑；hook gates 照常生效。

## Tier 1 精簡路徑

明確、單一路徑、不觸及高風險面的小功能。**跳過 Spec 檔與 usage 分析，但仍留溯源、仍守大小上限**。風險由 Router 的排除條件把關（觸及高風險面者根本進不到 Tier 1），故不另跑 6 面向分析。

1. **精簡初始化**：建 manifest `run/<run_id>.json`，填 `tier: 1`、`tier_rationale`、**`spec_inline`**（需求原文一句話，取代 `spec_path`）、`risk_report_path: "skipped"`、`usage_report_path: "skipped"`、`impact_report_path: "skipped"`（前置 2.5 固定跳過）、`phase: "init"`。**不建 `eval_state.json`**——Tier 1 的四項憑據（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`）直接記在 manifest 自身欄位（commit gate 憑此四欄放行，豁免的是歸檔檔載體，不是證據本身）
   - **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空，皆空不可往下
2. **直接建 task 檔**：免呼叫 `task-decomposer` subagent，但上限不變——**≤2 tasks、合計 ≤8 items（硬）、各 item 目標 ≤300 行（軟）；每 task 仍 ≤5 items**（單 task 審查可讀性上限不因放寬而破）。超過 2 tasks／合計超 8 items、或出現遠超 300 行且拆不進去的工作 → 觸發升級逃生門（回 Tier 2）。**功能移除類需求**：既有測試的分流依 task-decomposition skill 的「功能移除的測試三分法」（主題＝被刪行為→隨功能刪；主題是存活行為→只拔斷言行；無關→不動），主 flow 建 task 檔時完成分類
   - **小 prose item 合併（省審查稅）**：純 prose（文件／agent 定義／skill，無 code）、單檔 ≤30 行、語義同源（同一個設計決策的多處投放）的 items，**合併為一個 sub_task 一輪審**——審查稅從 N 輪降 1 輪。約束：合併後單輪 diff 仍須 reviewer 一次讀完可審（總量失控就拆回）；含 code 的 item 不併入 prose 合併
3. **輕量 HITL**：寫 code 前，把「N tasks／M items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。確認後將 manifest 的 `phase` 設為 `"decomposed"`（hook 憑此放行 code-writer）、`hitl_confirmed_at` 記「時間＋確認範圍一句話」，才進循環
4. **主 flow 直寫捷徑（可選）**：Tier 1 且單 item 預估 ≤100 行 → 主 flow 可直接寫 code、不 spawn `code-writer`（省一次全新 agent 重建 context 的稅）。守則：「寫的人 ≠ 審的人」防線不變（`code-reviewer` 照常獨立審 staged diff）；知識前置（三源，見循環 step 1）改由主 flow 自查並在回報留痕；超過 ≤100 行或跨多檔複雜 item 仍派 `code-writer`；hook 對 code-writer 的 phase gate 不受影響（直寫路徑不經該 gate，phase 仍須 decomposed 才動工——由輕量 HITL 保證）
5. **共用循環**：進入上方循環的步驟 1–7（code-writer → review（含完成度節）→ 本地測試 → commit）。收尾**不歸檔**（無 `eval_state.json`）：manifest 填入四欄憑據（`local_test_passed: true`、`local_test_evidence`、`review_reds`、`verify_passed: true`）並標 `status: "completed"`，直接 `git add` manifest／task 檔並 commit（message 附 `Run-Id: <run_id>` trailer）。不執行 eval_state.py 的 archive 操作、不清除任何 scratchpad（本就沒建）
   - sub_task 的 `risk_analysis` 可簡記為 `"router 已篩（Tier 1）"`，不需逐面向填
   - step 5 可用實際運行功能驗證取代自動化測試（不強制建測試），但 `local_test_evidence` 照填——證據要求不分 tier

## Tier B Bootstrap 路徑（骨架工作，無業務邏輯）

空專案或新模組的純結構性工作：目錄結構、框架接線、CI、工具鏈。**沒有使用者情境可盤（usage 分析跳過）、行數天然爆表（不適用 5 items／300 行上限）**，但選型是使用者的決定，且這是引入測試框架成本最低的時點——路徑圍繞這兩點設計：

1. **Bootstrap 清單取代 Spec**：產出 `spec/<run_id>-bootstrap.md`，內容三段——要建什麼（逐項）、選型與理由（語言／框架／工具鏈，含捨棄的選項）、明確不做什麼（業務邏輯零容忍，出現即回 Router 重新判級）
2. **精簡風險分析**：只跑部署、資料兩面向（其餘四面向對空骨架無意義），結論併入清單檔，不另建 `risk/` 檔
3. **一次 HITL（硬性）**：清單交使用者確認**選型**後才動工——選型錯了整個骨架重來，這是 Tier B 唯一真正的風險
4. **建 manifest**：`tier: "B"`、`spec_path` 指向清單檔、`usage_report_path: "skipped"`、`risk_report_path: "inline"`、確認後 `phase: "decomposed"`。**不建 `eval_state.json`**（骨架多為 CLI 與樣板產出，不走循環評分——eval 維度對 scaffolding 不對口）
5. **DoD 固定兩條（hook 強制）**：①本地 build／run 指令跑得通 ②**測試框架已建立且有至少一個會跑的示範測試**——此後這個專案所有 run 的本地測試 gate 都沒有「無測試框架」的後門可走。兩條都過才把 manifest 標 `bootstrap_verified: true`，並把全套測試指令寫入 manifest 的 `test_command`（後續 run 的 test-strategy script 從此讀）
6. **收尾**：manifest 標 `status: "completed"` 隨骨架一併 commit（附 `Run-Id: <run_id>` trailer）。hook 對 `tier: "B"` 豁免 eval 歸檔檔要求，但 `bootstrap_verified` 非 `true` 擋 commit

## Hotfix 通道（先止血、後補債；債是硬性的）

僅限**使用者明確宣告**緊急（線上事故／資損進行中）時啟用，agent 不可自行認定。Bugfix 的診斷前判規則見 CLAUDE.md「工作型態前判」。

1. **止血**：診斷（重現 → 根因 → 修法）→ 直接修 ＋ 本地測試驗證（部署規則不豁免：未經本地驗證仍不可 commit／部署）
2. **精簡溯源**：建 manifest `run/<run_id>.json`，填 `tier: "hotfix"`、`tier_rationale`（含使用者宣告緊急的依據）、`spec_inline`（診斷結論）、`phase: "hotfix"`、`risk_report_path` / `usage_report_path: "deferred"`、**`debt: ["risk", "test", "retro"]`**。**不建 `eval_state.json`**（不走循環評分）
3. **commit**：manifest 標 `status: "completed"` 後隨修正一併 commit，message 附 `Run-Id: <run_id>` 與 `Hotfix: true` trailer（hook 對 `tier: "hotfix"` 的 manifest 豁免 eval 歸檔檔要求，但 intent gate 照常）
4. **補債（事後必須，不是可選）**：事故解除後依序還債，還清一項就從 manifest 的 `debt` 移除一項：
   - `risk`：補跑 task-risk-analysis，產出 `risk/<run_id>.md`、回填 `risk_report_path`（發現 🔴 → 立即回報使用者，可能需要 follow-up run 修正）
   - `test`：補上覆蓋該 bug 的回歸測試，本地跑過後隨 follow-up commit 進 git（同樣附 `Run-Id: <run_id>` trailer）
   - `retro`：強制呼叫 retro subagent，根因寫入 `retro/RETRO.md`
5. **欠帳 gate（hook 強制）**：任一 manifest 的 `debt` 非空時，**不可啟動新 run**（流程管制的 subagent 呼叫會被擋，還債所屬的原 run 不受影響）——防止「緊急」變成常態逃生門

## 單一 run 原則與併發（worktree 隔離）

- **一個 worktree 同一時間只允許一個 in_progress 的 run**。這不是任意規定：`eval_state.json` 是單例、git staging area 也是單例，同工作區並行兩個 run 必然互相污染（staged 變更分不開、commit 切不乾淨）
- **要並行 → 開 `git worktree`**：每個 run 在自己的 worktree／branch 裡跑，單例假設在 worktree 內自然成立，收尾各自 commit 後合回主線。**≥2 個互不相依的 Tier 1 需求同時進來時，依 `parallel-run` skill 執行**（批次 HITL、背景 agent、merge 收尾的細節住在該 skill）
- **插單（run 跑到一半來了急件）**：原 run 的 worktree **原地凍結**（狀態已全在 manifest／`eval_state.json`／staging area 裡，不需要任何「暫停」操作），急件在新 worktree 處理，完成後回原 worktree 依 `eval-flow-resume` skill 接續
- hook 強制：呼叫流程管制的 subagent 時，若本工作區存在**其他** in_progress 的 manifest（run_id 與 `eval_state.json` 不一致）→ 擋，並提示「先收尾／封存既有 run，或開 worktree 並行」
- **`[P]` item 的並行執行由 fan-out 達成，不再有共用同一棵樹的併發 writer**：門檻滿足（`[P]` item ≥2 且各自預估 ≥150 行）→ 走「## Tier 2 [P] fan-out（worktree 並行）」節，各開 worktree 隔離，mine 模式在各自樹內正常生效；門檻不足 → 退回主 worktree **循序**執行（一次一個 item），亦無共用樹併發。舊「shared-tree join barrier」概念隨共用樹模型一併移除；跨 item 的全套測試把關由 rolling merge 段的全套 baseline gate（見 `parallel-run` skill 步驟 8）負責

## Tier 2 [P] fan-out（worktree 並行）

Tier 2 run 內符合門檻的 `[P]` item 各開 git worktree 並行執行，取得真正的 worktree 隔離：每個 item 在自己的樹裡，`git diff --cached` 天生乾淨、mine 模式復活。本節描述三段式 fan-out 執行協定，由**主 flow**（前景，判門檻／開 worktree／rolling merge）編排、**背景 item agent**（在各自 worktree 跑迷你 run，具備 Bash／Write／Edit 工具）執行、收尾序列**直接引用 `skills/parallel-run/SKILL.md`**（避免兩處漂移）。改此 skill 的 run 自身序列跑、不 fan-out（新機制首次執行不用在改它自己的 run 上）。

### 門檻與退回

fan-out 僅在「**`[P]` item ≥2 且各自預估 ≥150 行**（以 task-decomposer 的 `~<行數>行` 欄位 ×2 校準估計為準）」時啟動。估計不準即不 fan-out（保守偏循序）。不滿足門檻 → 該批 `[P]` item 退回主 worktree **循序**執行（不開 worktree），派 code-reviewer 時改用循環 step 2 的 file-scoped diff 收斂（引用循環 step 2 的規則，不在此重述）。含「有意行為變更需更新既有測試」的 item 不可進 fan-out 批，改留循序段——理由與 `parallel-run` skill 相同：既有測試只增不改是 merge gate 的裁判前提，破掉它等於裁判換人、全套綠燈失去安全保證。

### 三段式執行協定

三段的跨段不變量：**prep 段的父 manifest 標 `completed` 是 fan-out 的必要前提，fan-out 不可提前**。這個跨段條件的機械依據有二：`eval_gates.py` 的 `check_other_runs`（約 :155）對同工作區另一個 in_progress manifest 直接 block subagent 呼叫——父 run 若保持 in_progress，item worktree 裡的 code-writer 就會被擋；歸檔 gate 對未歸檔的 `eval_state.json` 擋 commit——prep 段必須照現行 step 6 正常歸檔後才能 commit，commit 完父 manifest 才能標 `completed`。

**① 循序前置段（prep run）**

依賴型 item（task 中標 `depends`、不可標 `[P]`，典型如 DB schema 定義、共用型別）在主 worktree 循序做完，照現行 step 6 正常歸檔＋commit，父 manifest 標 `status: "completed"` 後才進入 fan-out。這批 item 是各 `[P]` item branch 出去時的共同基礎，必須先落地才能確保各子 worktree 起點一致。沒有 depends 型 item 時，此段為空、直接進入 fan-out。

**② Fan-out 段**

主 flow 為每個符合門檻的 `[P]` item spawn 一個背景 item agent，**worktree 交由 harness 建立**：以 `Agent` 工具的 `isolation: "worktree"` 啟動，harness 建 `.claude/worktrees/agent-<id>/` 並在啟動時釘定該 agent 的工作目錄。細節與禁止事項見 `parallel-run` skill 步驟 5（**禁止改用「主 flow 先 `git worktree add`，再叫 agent 自己進去」**——2026-07-29 實測證明 repo root 啟動的 subagent 無法切入，`EnterWorktree` 會拒絕；亦禁止用 `cd` 替代，那會使 gate 判到主工作區）。

branch 名稱由 harness 指派（非 `feat/<父run_id>-item-<id>`），item agent 須在回報中附上；全族溯源靠 commit trailer `Parent-Run-Id: <父run_id>`，不靠 branch 命名。**worktree 起點是 `origin/<預設分支>`、不是父 run 的 HEAD**，故 item agent 起手必須依 `parallel-run` 步驟 6 的「起手三步」`git merge main` 同步並驗證前提（本節的 prep 段成果若未 push，正是靠這一步才進得了 item worktree）。

然後同一訊息 spawn 全部背景 item agent（一 item 一 agent，並發啟動）。每個背景 agent 以**獨立 sibling 迷你 run**執行完整 Tier 2 循環：

- **子 manifest**：`run/<父run_id>-item-<id>.json`，填入 `parent_run_id: <父run_id>`、`spec_path` 指回父 Spec（`spec/<父run_id>.md`）、`tier: 2`、`status: "in_progress"`，以及自己的 `run_id`、`created_at`、`phase`。
- **自己的 `eval_state.json`**（在自己 worktree 初始化），自己的 eval_state 貫穿自己的 code-writer → review（含完成度節）→ step 5 本地測試 → 自己歸檔。
- **mine 模式在隔離樹下復活**：各 worktree diff 乾淨，未提交變更只屬於自己，`python3 .claude/hooks/test_baseline.py mine --strike-key <item_id>` 可正常推導範圍。
- **hook gate 在各 worktree 內獨立生效（有前提，非天然成立）**：每個 worktree 有自己的 staging area 與 `eval_state.json`，所有現行 gate 照常運作、零後門——**前提是 hook 以該次 tool call 的實際 cwd（payload 的 `cwd`）解析所屬 worktree 根後才 chdir**。`CLAUDE_PROJECT_DIR` 由 Claude Code 釘死在 session 啟動目錄、**不隨 worktree 移動**（`EnterWorktree` 與背景 subagent 皆然），若 gate 逕以它決定工作區，worktree 內的 run 會誤用主工作區狀態：subagent 呼叫 gate 誤判、commit gate 因讀主工作區空 index 而靜默失效。此解析住在 `.claude/hooks/eval_gates.py`，改動該處等同動搖本節前提。**限制**：`CLAUDE_PROJECT_DIR` 為 git 儲存庫子目錄的專案開 worktree 時會解析到 worktree 根（不拼接子路徑），該類專案目前不支援 fan-out。
- **自己 branch commit**：step 6 收尾 commit 附 trailer `Run-Id: <子run_id>` 與 `Parent-Run-Id: <父run_id>`（後者讓主 session 一次 grep `Parent-Run-Id: <父run_id>` 撈全族 commit）。禁止 push、禁止切 branch、禁止把自己的 branch 合進 main（同 `parallel-run` skill 的背景 agent 規則；起手的 `git merge main` 是反方向同步，允許且必要）。
- **BUGLOG 條目寫進回報內容、不 append 檔案**：沿 `parallel-run` skill 規則——各 worktree grep 自己的快照會漏看對方的條目，兩層制升級判定由主 session 於 merge 後統一做。
- **blocker 出在 main 既有 code 時禁止在 item worktree 修**：標明後依 `parallel-run` skill 的「卡住／HITL 協定」停下，由主 session 在 main 上走 bugfix 流程，修完後各 item worktree `git merge main` 同步（修一次、多支受惠）。
- 卡住（2 次真失敗、任何需使用者裁決的事）→ 依 `parallel-run` skill 的「卡住／HITL 協定」停止並回報主 session，manifest 標 `status: "blocked"`，落盤卡點報告 `run/<子run_id>-blocked.md`，**不自行猜測往下**。

角色確認（retro 約束）：主 flow 能開 worktree、讀寫 manifest（成立）；背景 agent 在隔離 worktree 內具 Bash／Write／Edit、hook gate 照常生效且能 commit 自己 branch（成立——gate 生效以上一項的 root 解析前提為條件）；引用 `parallel-run` skill 的收尾步驟確實存在於該 skill（收尾序列見 `parallel-run/SKILL.md` 步驟 7–10，機械檢查①②見步驟 8 的子項 8.1／8.2，已 Read 佐證）。

**③ Rolling merge 段**

直接引用 `skills/parallel-run/SKILL.md` 的收尾序列（步驟 7–10），不重寫——避免兩處機制描述漂移。重用其：① 測試只增不改機械檢查（`git diff main...<branch>` 過濾測試路徑，出現 M／D 不 merge；`<branch>` 取自該 item agent 回報的 harness 指派 branch）② 實際交集重驗（本支與其他未合支的實際 changed-file 清單取交集，非空停下回報）③ 後合者先 `git merge main` 同步再重跑相關測試 ④ 全套 baseline gate（`git merge <branch>` 後跑全套，判準為相對 merge 前 main baseline 無新增失敗；批次層 baseline 快照須手動帶 `--cmd`）⑤ BUGLOG 帶回統一 append＋兩層制升級判定＋清理 worktree 與 branch（append 前 grep 舊條目判是否升級 RETRO；清理**可能因 harness 的 worktree lock 而失敗，失敗時不可強拆**，依 `parallel-run` 步驟 8.5 處置——未上鎖者照常移除，仍上鎖者列入回報交由使用者或 harness 回收）。誰先完成先收，不等全批。**本①-⑤為重點提示，完整子步驟以 `parallel-run` 步驟 8 之子項 1–5 為準、不由本清單替代。**

一族 commit 完成後，可用 `git log --grep "Parent-Run-Id: <父run_id>"` 反查全族。

### 錯誤路徑與批次中斷恢復

**F-err1（rolling merge 後測試紅燈）**：全套測試在 merge 後出現新增失敗，根因跨兩支 branch 語意衝突。由 bugfix 走既有「診斷先行」流程、在**主 session（main）**做（單一 worktree 視野只有一半）——見 `parallel-run` skill 步驟 9。

**F-err2（機械檢查② 實際交集非空）**：fan-out 前置預估 disjoint、但合併前重驗時本支與其他未合支的實際 changed-file 清單有交集——disjoint 前提被實際變更打破。該支停下回報、退出並行改循序——見 `parallel-run` skill 步驟 8 子項 2（8.2）。

**G（批次中斷恢復）**：主 session 死掉後，以下痕跡機械重建批次狀態，不靠記憶——見 `parallel-run` skill 步驟 14：
- `git worktree list`：還有哪些 worktree 存活
- 各子 manifest `status`（in_progress／blocked／completed）：哪支還在跑、哪支卡住
- `git log --grep "Parent-Run-Id: <父run_id>"`：哪支已 merge 進 main
- `run/parallel-merge-*.test_baseline.json` 存在與否：全套 baseline 是否已快照

**特別檢查項——已 merge 但 BUGLOG 未 append 的遺失窗口**：子 manifest 標 `completed`、commit 已在 main 的 `git log` 內，但 `retro/BUGLOG.md` 沒有對應條目（收尾步驟 8.5 的 append 在 session 死掉前未完成）。重建後逐支確認：已 merge 的 run 有無帶 BUGLOG 條目（回報內容或卡點報告），有條目未 append → 補問使用者確認後補 append，並依兩層制做升級判定。
