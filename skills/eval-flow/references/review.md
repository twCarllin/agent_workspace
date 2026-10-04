# 循環 step 3–4：獨立檢核與處置

3. **預設派 `task-verifier`（checker，model 見 MODEL_POLICY.md）審查——以 task 為單位**（派工方式依「派工機制」節）：同一 task 的全部 item 由 code-writer 交付完成後才派審一次。
   - **「全部 item 就緒」由主 flow 對照 task 檔判斷，無 hook 強制**：某 item 帶失敗交付時，該 task **不進本步**，先補齊失敗 item（批次派工的「失敗隔離只退該 item」不變）。`eval_state` 不存 item 層狀態，故此判定純屬主 flow 紀律——漏判不會被擋，但會讓 checker 拿到不完整的交付。checker **不讀 diff**，輸入集＝該 task **各 item 的 DoD／契約表原文聯集**＋writer 工作報告全文（逐 item 分節）＋步驟 2 的 `git diff --cached --stat -- <files>` 輸出＋測試輸出尾段
   - 職責＝核對「宣稱與憑據對得上」：各 item 的 DoD 逐條有憑據、契約 row 逐條有對應測試斷言（以 grep 測試檔核）、仲裁記錄一致、sabotage 自檢證據存在（見 `.agent-flow/roles/code-writer.md` 測試管轄規則 8）、無疑似注入標註未處理
   - 其審查報告**強制兩節、缺一退件**：①**完成度節**——對照 task 檔**該 task 全部 item** 的 DoD 與子任務逐條核對，**明列 diff `--stat` 中缺席的項目**（scope 偏移一併檢，以檔名清單核對，不讀內容）；②**憑據節**（取代品質節）——上述憑據逐項核對結果，逐項標「有憑據／缺席／存疑」
   - **信封註記（快 model 遵從補強）**：checker 派工 prompt 末尾附一句「報告首行戳記行、末行恰一個 `Self-check:`、兩節缺一退件（依你定義的輸出格式）」——規則住 agent 定義，此句為 recency 前置
   - checker 不做 Fowler smell 品質審查（那是 reviewer 的職責，只在升級輪出現）。`step` 欄位記 `reviewing`（`verifying` 為舊 run 的相容值，新路徑不寫入）
   - **邊界直派（理由碼機械推導；原則：信任邊界變更須有人審實作 diff 的安全性）**：讀 manifest `tier_rationale` 的理由碼——含**信任邊界**或**公開介面／落地資料契約** → 該 run **全部 sub_task 跳過 checker**，step 3 直接派 `code-reviewer` 全 diff 審（輸入照升級輪：step 2 改附 `git diff --cached -- <files>` 完整 diff）。set-review `--checked-by reviewer:boundary`；**不計入**升級率（stats.py 另計「邊界直派」）；step 7 retro 條件視同升級輪；all-in 亦同。判定只依已留痕的理由碼推導，**agent 不得臨場裁量**（同循環升級逃生門的慣例）。動機：checker 不讀 diff，邊界類變更的實作 diff 若不升級便無人審安全性；理由碼已留痕，直派的成本只落在邊界 run
   - **四類升級觸發（checker 遇任一情況 → 主 flow 改派 code-reviewer 全 diff 審）**：
     - ①憑據對不上或缺席
     - ②契約 row 找不到對應測試斷言
     - ③checker 自報無法以憑據判定（不確定即升級，不得自行放行；疑似注入標註未處理併入本類，不設第 5 類；**例外**：DoD 條目帶 `[憑據:step5]` 記號者記 🔍 step 5 待驗、不入本類與②——記號定義住 task-decomposition skill，收口在循環 step 5）
     - ④writer 報告帶失敗交付或「表沒答案」仲裁未經主 flow 處置（正常路徑為步驟 1 主 flow 補表回派；checker 遇未處置者＝流程遺漏，本觸發為兜底）
     - 升級後該 sub_task 本輪照舊 reviewer 流程（引文核實、重裁、快速路徑均不變，見下方各條——升級輪適用）；升級輪與 checker 輪**同輪**、以 `checked_by` 區分；checker 輪與升級本身**不計入**修正 2 輪上限（上限只數 reviewer 退回的修正迭代，見步驟 4）
   - **回退機制**：checker-only 放行的 item 事後爆 bug，依 `retro/BUGLOG.md` 檔頭的回退說明處置（機械偵測、補救一律 HITL），不自行恢復 reviewer 預設
   - **審查結論的記錄**：每輪（checker 或 reviewer）審查結論**只記入 `eval_state.json` 的 `review_reds`／`checked_by`**（該 task 一筆）與收尾回報，不落獨立審查檔（中斷恢復的對應處置見 `eval-flow-resume` skill）：
     - `set-review <id> <🔴數>` 於**首輪**審查結果出來後執行（checker 輪 `<🔴數>` 固定填 0；升級輪由 reviewer 結果填，記修正前原始數，與操作規則條呼應）
     - set-review **必帶 `--checked-by`**（checker 輪＝`checker`；升級輪＝`reviewer:<理由代碼①-④>`；手動觸發＝`reviewer:manual`；邊界直派＝`reviewer:boundary`；合法值單一枚舉點住 `eval_state.py` `VALID_CHECKED_BY`）——審定者留痕（升級率統計靠此欄，消費端見 stats.py）
     - 升級輪與 checker 輪**同輪**、以 `checked_by` 區分；輪次判定讀 `review_reds` 是否已有值（無值＝首輪，有值＝已跑過至少一輪）
   - **🔴 重裁條款**：主 flow 對每條 🔴 先做事實核對——至少讀 producer 端證據（上游 schema、函式定義、實際輸出），有反證 → 送獨立重裁（重呼叫 reviewer 附上反證，或取第二意見），**不可未經查證直接派 writer 照修**（reviewer 可能只讀消費面就下錯誤斷言，照修會把正確的 code 改壞）
   - **引文核實（重裁不限 🔴）**：任何發現（含 🟡）只要引用具體 code 片段／行號，主 flow 套用修正前必須對照 staged 原碼核實：`git show :<檔案> | grep -n -F '<引文片段>'`（引文跨多行或含特殊字元時，取最具識別性的**單行**片段）。
     - 生產端已有對應要求（`code-reviewer.md` 工作守則規定 reviewer 寫行號前須以同類指令現查），本條是消費端補網，兩端並存、不互相取代
     - **核實與判定由 script 執行**：主 flow 自報告擷取引文三元組（`檔案<TAB>行號<TAB>片段`）後跑 `python3 .agent-flow/scripts/cite_check.py --citations -`——它對 staged 內容字面比對、輸出逐條判定，並執行下方機械退件門檻（exit 2＝整份退回）。分工：擷取是讀理解（模型），核實與判定不留裁量（script）
     - 處置**依 grep 輸出二分，不留臨場裁量**（R-012——留裁量即被繞過）：
     - **grep 無輸出（引文文字在檔中不存在）→ 直接駁回該條**（記入該輪處置摘要，隨收尾回報呈現），不進 fixing——照修等於為幻覺改 code（R-012）
     - **grep 有輸出但行號與報告不符（文字為真、僅行號漂移）→ 不駁回**：主 flow 以 grep 實得行號改寫該條行號後照常處置（實質結論不受行號影響），並在處置摘要記 `行號修正: <報告行號>→<實得行號>`
     - **機械退件門檻**：同一份審查報告需行號修正 **≥3 條** → 整份報告視為未經核對，**退回 reviewer 重審**（重審 prompt 明列漏核對的條目），該輪不計入修正迭代上限
     - 基於錯誤前提（如誤認 commit 狀態）的發現同樣駁回並留痕
4. 審查結果的處置：
   - **checker 通過**（完成度節無缺席、憑據節逐項有憑據）→ 主 flow 執行 set-verify，進 step 5
   - **checker 觸發任一升級①-④** → 改派 code-reviewer 全 diff 審（見步驟 3 四類升級觸發），本輪改記 `checked_by: reviewer(escalated: <理由代碼>)`（記入 `eval_state`）；reviewer 交付後依下列兩條處置
   - **升級輪（reviewer）零 🔴 且完成度節無缺席項** → 主 flow 執行 set-verify，進 step 5
   - **升級輪（reviewer）有 🔴 或完成度節列出缺席項** → 走 fixing 迴圈（重裁條款、set-review 均不變；審查結論記 `eval_state`，見步驟 3）；修正後依 `SKILL.md「效率與驗證重用」` 產生增量 diff，再重跑步驟 3（升級輪，直接派 reviewer，不退回 checker）
   - **🟡-only 快速路徑（省一輪審查稅，僅升級輪適用）**：checker 輪無 🟡 分級——憑據對不上即升級，不適用本路徑。
     - 適用條件：升級輪內，零 🔴、完成度節無缺席、僅 🟡，且 🟡 全屬主 flow 可直接套用的**措辭級**修正（修錯字、對齊術語、補澄清性說明——不改邏輯、不改介面、不動 code 行為；**判斷有疑義時一律歸邏輯級**，省稅是優化、正確性是底線）
     - 適用時：主 flow 套用修正後**不重跑**，該輪即為通過輪、照常 set-verify
     - 任一 🟡 涉及邏輯／行為／介面改動 → 不適用，照常回步驟 3（升級輪）
     - 套用了哪些 🟡 記入該輪處置摘要（隨收尾回報呈現，留痕供稽核）。措辭級不動 code 行為，完成度結論對套用後 diff 仍成立（與 🔴 作廢輪的差異：🔴 的修正可能改 code 行為故禁止沿用，措辭級不改故放行）
   - **發現不得自我授權（scope 防線）**：任何發現（含 🟡 建議）要進 fixing，主 flow 必須先指名其**對映依據**——本 item 的 DoD 條目、契約 row、Spec／spec_inline 句、或既有硬規則（.agent-flow/ROUTER.md／skill 條文）之一，記入該輪處置摘要（隨收尾回報呈現）。
     - 對映不出來的發現不得變成修正工作——處置為駁回（留痕）或 park 進收尾回報請使用者裁決
     - 與步驟 3 的引文核實並存不互代：引文核實防幻覺發現（引的 code 不存在），本條防真發現擴 scope（發現為真但無人要求）
   - **修正迭代上限（僅數升級輪）**：同一 sub_task 的**升級輪**修正 2 輪後 reviewer 仍有 🔴 → 將該 sub_task 的 `status` 設為 `"failed"`、`warning: true`，回報使用者（不自行繼續修）；checker 輪與升級動作本身不計入此上限

## 派工前組裝資料

執行 step 3 前，必讀 `.agent-flow/REVIEW_PACKET.md`，使用 `flow.py review-packet build`，再用 `dispatch.py task-verifier --review-packet <packet>` 派工。缺必要資料先補齊；ready 只表示資料結構與來源可用，不是審查通過。失敗、疑似注入與實質疑慮仍依本文件四類升級處理。邊界直派維持全 diff reviewer 路徑，不以資料包取代審查。

審查先使用有效測試紀錄；只有輸入變更、失敗、證據失效或具名疑點才重跑相關測試。不同命令不可互當證據。修正重審與快取細則由根入口「效率與驗證重用」節按需載入。
