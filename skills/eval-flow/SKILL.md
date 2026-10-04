---
name: eval-flow
description: Tier 1／2 需求的實作流程：Tier 2 前置（初始化、具名問題觸發、分拆 task、HITL gate）、共用循環步驟 1–7（code-writer → checker／reviewer → 本地測試 → commit）、Tier 1 精簡路徑、headless 派工機制。觸發語：Router 判定需求為 Tier 1 或 Tier 2 時（執行前必須載入本 skill）、「跑 Eval Flow」、「照流程實作這個需求」。不適用於：Tier 0 微調（直接改，收尾 append 一行 tier0 留痕）、非實作類的問答。
---

# Eval Flow（Tier 1／2 執行細節）

> 本 skill 由主 flow 在 Router 判定 **Tier 1 或 Tier 2** 後載入執行。Router 分級表與防濫用規則住在 .agent-flow/ROUTER.md，不在此重述。先依下方「路徑選擇」認路。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。流程術語一詞一義，正式詞與禁用變體見 `references/glossary.md`（寫流程文件時查，執行 run 不需載入）。

## 路徑選擇

| Router 判定 | 前置 | 循環 |
|---|---|---|
| **Tier 1** | 本檔「Tier 1 精簡路徑」節 | 本檔「循環」節步驟 1–7 |
| **Tier 2** | `references/tier2-prep.md`（前置 0 → 具名問題觸發（選配）→ 前置 1 → HITL gate） | 同上，步驟 1–7 共用 |
| **Tier B／Hotfix／併發／[P] fan-out** | 各自入口見本檔同名節，完整路徑住 `references/rare-paths.md` | 依該路徑規定 |

先讀 `.agent-flow/HARNESS.md` 與 `.agent-flow/PRACTICES.md`。新 Tier 1／2 manifest 一律記目前 `harness` 與 `evidence_schema: 2`。派工輸入含目標、背景、限制與完成條件。

全 tier 的第一個動作都是下方「共用：進場檢查」。

## 共用：進場檢查（全 tier，執行任何步驟之前）

- **進場檢查（建 manifest 之前）**：跑 `git status --porcelain`。非空 → 列出檔案清單問使用者歸屬（納入本 run／擱置不動），裁決一句寫入 manifest `dirty_tree_ruling`（選填欄；乾淨樹免記）。孤兒變更不先裁決，staging 與 commit 範圍會在收尾才爆

## Tier 1 精簡路徑

理由碼（complexity_reasons）空集合、或僅剩具名重大問題可由點名 advisor 回答的工作（判準住 .agent-flow/ROUTER.md Router，不重列——R-007）。**跳過 Spec 檔與全套 usage 分析，但仍留溯源**。風險由 Router 的理由碼把關（信任邊界／公開契約本體變更根本進不到 Tier 1），故不另跑風險分析。

1. **精簡初始化**：同守上方「共用：進場檢查」（dirty tree 先裁決歸屬，不重列——R-007）。
   - 建 manifest `run/<run_id>.json`，填 `tier: 1`、`tier_rationale`、**`spec_inline`**（需求原文一句話，取代 `spec_path`）、`phase: "init"`（`risk_report_path`／`usage_report_path`／`impact_report_path` 三欄維持初始 `null`，語義見 `references/formats.md`）
   - **不建 `eval_state.json`**——Tier 1 的四項憑據（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`）直接記在 manifest 自身欄位（commit gate 憑此四欄放行，豁免的是歸檔檔載體，不是證據本身）
   - **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空，皆空不可往下
   - **事件留痕（時間戳）**：manifest 建立後跑 `python3 .agent-flow/scripts/eval_state.py event <run_id> init`——Tier 1 無 `eval_state.json`，事件由 `event` 子命令直寫 `run/<run_id>.events.jsonl`（冷溯源；格式與消費端見 `references/formats.md`）。主 flow 手動呼叫收斂為 **5 個節點**：`init`（本步）、`hitl_confirmed`、`reviewed`、`verified`、`completed`（各節點呼叫點見下列步驟）
2. **直接建 task 檔**：免呼叫 `task-decomposer` subagent，但上限不變——**≤2 tasks、合計 ≤8 items（硬）、各 item 目標 ≤300 行（軟）；每 task 仍 ≤5 items**（單 task 審查可讀性上限不因放寬而破）。
   - 超過 2 tasks／合計超 8 items（task 檔可讀性上限，非判級軸）、或觸發 .agent-flow/ROUTER.md 升級逃生門任一條件（實際規模遠超判級認知、冒出新理由碼、🔴）→ 升級 Tier 2
   - **功能移除類需求**：既有測試的分流依 task-decomposition skill 的「功能移除的測試三分法」（主題＝被刪行為→隨功能刪；主題是存活行為→只拔斷言行；無關→不動），主 flow 建 task 檔時完成分類
   - **DoD 措辭**：主 flow 直建 task 檔的 DoD 與契約 row 同守 task-decomposition 的可驗斷言與「禁不可驗評價詞」規則（清單住該 skill，此處不重列）——Tier 1 不載入該 skill，此指向句即投放路徑
   - **合併審查（省審查稅）**：同一連貫變更（同 `spec_inline` 一句涵蓋、同一個設計決策）的多 items，合計 staged diff 一輪可讀（≤約 400 行）→ **合併為一輪 checker 審**——輸入集為各 item 的 DoD／契約表**聯集**，其餘輸入照循環 step 3 不變。
     - 約束：合併後單輪仍須一次讀完可審（總量失控就拆回）；**all-in 時本捷徑關閉**（逐 item 審）
3. **輕量 HITL**：寫 code 前，把「N tasks／M items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。
   - **點名 advisor（有具名重大問題時）**：Router 判 Tier 1 時若理由碼非空（靠具名問題收斂），HITL 一併提報「**問題原文**＋點名的 advisor（`usage-analyzer` 或 `impact-analyzer` 擇需）」——只點 advisor 不說問題＝不合格（agentflow ag.md 原則）
     - 確認後（phase 已 `decomposed`，既有 AGENT_MIN_PHASE 放行）先跑該 advisor（答案寫入 Spec 或 task 計畫備註，不產獨立報告檔、不回寫 report path 欄，同 Tier 2 具名問題觸發語義），拿到答案再進循環
   - 確認後將 manifest 的 `phase` 設為 `"decomposed"`（hook 憑此放行 code-writer）、`hitl_confirmed_at` 記「時間＋確認範圍一句話」、`hitl_rulings` 記裁示條數（int，選填；無裁示填 0，語義同 Tier 2 HITL gate 的同名欄），並跑 `eval_state.py event <run_id> hitl_confirmed`，才進循環
4. **主 flow 直寫捷徑（可選，全 tier 適用；all-in 時關閉）**：主 flow 判斷「交接是否划算」（行數與檔案類型不是委派依據）——考量 item 是否需要獨立乾淨 context、主 flow 目前 context 負載、item 邏輯是否簡單機械；划算則直接寫 code、不 spawn `code-writer`（省一次全新 agent 重建 context 的稅）。**留痕（硬性）**：每 item 在 manifest 選填欄 `executor_notes` 記一句 `item <id>: 直寫｜派工 — <理由>`（欄位語義見 `references/formats.md`），供事後審計選擇是否合理。守則：
   - 「寫的人 ≠ 審的人」防線不變（審的人預設為 `task-verifier`（checker），照常獨立審；升級走循環 step 3 四類觸發同一套規則，改派 `code-reviewer`）
   - 知識前置（三源，見循環 step 1）改由主 flow 自查並在回報留痕
   - 需要獨立 context 的 item（多檔複雜邏輯、主 flow context 已重）仍派 `code-writer`
   - **直寫路徑同受 hook 攔截**：PreToolUse 的 Write／Edit gate 在 manifest `phase` 未達 `decomposed` 時擋下對實作檔的寫入（溯源與規格檔例外：`run/`／`task/`／`spec/`／`retro/`／`eval_state.json`）。確認只認檔不認對話——以 `python3 .agent-flow/scripts/eval_state.py hitl-confirm <run_id> --note "<一句>" [--rulings N]` 留痕並推進 phase；**無人看管的 session（headless）不得自行確認**，該指令會拒絕，正確行為是停在此步、回報計畫與待裁示項後結束，由有人看管的 session 接手。**此 gate 只攔 harness 已接入的檔案寫入工具，不防以命令工具寫檔**（同其他 gate 的防護層級：防照規則推進的誤用，不防刻意繞道）
5. **共用循環**：進入下方循環的步驟 1–7（code-writer → review（per-task，含完成度節）→ 本地測試 → commit）。收尾**不歸檔**（無 `eval_state.json`）：
   - **收尾檢查只跑累積聯集**（step 6 ⓪ 的 Tier 1 範圍：`--strike-key wrapup_related`，不跑全套；指令與空集合處置住 test-strategy skill「Commit 前收尾檢查與重開路徑」節）
   - **事件留痕（時間戳，接續步驟 1 的留痕點）**：每 task 審查完成後跑 `eval_state.py event <run_id> reviewed`、step 5 驗證完成後 `event <run_id> verified`、收尾 commit 前 `event <run_id> completed`——Tier 2 的同等資訊由 eval_state.py 各子命令自動附掛，Tier 1 靠這三個呼叫點補齊（消費端 stats.py 事件節不分 tier）
   - manifest 填入四欄憑據（`local_test_passed: true`、`local_test_evidence`、`review_reds`、`verify_passed: true`）；提交前跑 `run_commit.py prepare <run_id>` 標 `ready_to_commit`，提交成功後跑 `run_commit.py finalize <run_id>` 標 `completed`
   - 直接 commit **依 step 6 子項② 的處置**（Tier 1 無 eval 歸檔檔與 usage 報告；溯源檔同樣留在工作目錄不 `git add`），message 附 `Run-Id: <run_id>` trailer——**trailer 是 commit gate 的定位依據，不可省**
   - **收尾對溯源檔怎麼處置，以 step 6 子項②為單一枚舉點**，本處與 `references/rare-paths.md` 內的 fan-out 節皆指向它、不各自重列（R-007——各自重列必漂移）
   - 不執行 eval_state.py 的 archive 操作、不清除任何 scratchpad（本就沒建）
   - step 5 可用實際運行功能驗證取代自動化測試（不強制建測試），但 `local_test_evidence` 照填——證據要求不分 tier；驗證指令以 `run_verify.py` 執行（一次完成跑＋記 manifest `verification_commands`＋寫 verify_cmd 事件，見循環 step 5）

## Tier 2 完整路徑

當一個需求被 Router 判為 **Tier 2**（需實作的完整 Spec）時，執行以下流程。**Model 不在 flow 層級統一指定**，由每個 agent 的定義承載（見「Model 指派原則」節）。

前置四步住 `references/tier2-prep.md`（步驟清單見「路徑選擇」表），依序完成、**HITL gate 未過不可進入循環**；前置完成後回本檔「循環」節，與 Tier 1 共用步驟 1–7。

## 循環（每輪結果寫入 `eval_state.json`）

> **循環中的升級逃生門（Tier 2 也適用）**：循環執行中若冒出 🔴 重大風險、或發現需求歧義（DoD 講不清、Spec 有洞）→ 中止循環，先修改 **Spec** 釐清範圍；若牽動使用情境或影響面，補派具名問題給 `usage-analyzer`／`impact-analyzer`；若影響拆分，重跑前置 1（分拆 task）。

開工前把這份 checklist 複製進回報，逐步打勾（步驟細則見下方各步）：

```
- [ ] step 1: 派工 code-writer（gate: 知識前置＋契約前置）
- [ ] step 2: git add 進 staging（gate: file-scoped）
- [ ] step 3: 派 checker 審查（gate: 兩節缺一退件）
- [ ] step 4: 審查結果處置（gate: 引文核實）
- [ ] step 5: 本地測試（gate: 無新增穩定失敗）
- [ ] step 6: 收尾順序（gate: hook 強制）
- [ ] step 7: 有條件派 retro（gate: 僅升級輪）
```

1. 依「派工機制」節派工 `code-writer` subagent 產出程式碼
   - **批次派工（省 spawn 稅）**：派工單位＝**task**，同 task 多 item 一次派給同一 code-writer（知識前置一次組裝、item 間共用 context）。條件：①批內合計預估 ≤400 行（與合併審查上限對齊，超過拆批）②`[P]` item 不混批（保留平行／worktree 路徑）③**失敗隔離**：單 item 帶失敗交付只退該 item，其餘 item 照常收④工作報告與憑據**逐 item 分節**（審查輪輸入不變、逐 item 核對，格式住 code-writer.md）。單 item 的 task 照舊
   - **知識前置（硬性步驟）**：呼叫前，主 flow 把三個來源的相關內容**原文貼進 writer prompt 的硬性約束區**——不是叫 writer「自己去讀」，知識只有以明文約束前置進 prompt 才有效（R-011）。三源：
     - **retro 條目**：先以本 item `files` 的模組路徑 grep `retro/RETRO.md` 的標籤篩選（標籤第一段＝模組路徑，見 retro agent 規範），主 flow 再補判同類操作／同類風險面的條目
       - **篩選由 script 執行**：`python3 .agent-flow/scripts/retro_select.py --files <該 item 的 files>`——它一次做完下兩條（排除 retired、錨點鮮度檢查），輸出可直接貼進硬約束區的條目原文與 retire 候選清單。機械步驟不留給模型逐次手做；主 flow 仍須就輸出補判同類操作／同類風險面的條目
       - **排除 retired 條目**：grep 命中標 `［retired ...］` 的條目一律不選（標記定義住 RETRO.md 檔頭，單一枚舉點——此處指向式引用、不重列格式）
       - **貼入前鮮度檢查**：選中的每條若帶前提錨點 `［錨點: X］`，貼進 prompt **前**先 grep 該錨點（檔案／helper／機制名）是否仍存在於 codebase——**不存在→不貼該條**，改列入「retire 候選」於收尾回報使用者（比照 memory 規則「recalled 條目須先驗證仍存在」）。錨點失效的舊約束是對已消失機制的錯誤指令，貼進去只會與新功能打架
     - **模組 conventions**：本 item 觸及模組的子目錄 `AGENTS.md` 與目前 harness 入口（存在則摘錄相關段）
     - **impact report 慣例段**：本 run 曾具名問題觸發 `impact-analyzer` 且答案含該模組時，摘錄「各模組既有慣例」與「可重用既有元件」節（節名見 impact-analyzer 定義；答案寫在 Spec）
     - grep 篩選的對象是**模組名片段**（取自 files 路徑的目錄／檔名，如 `eval_gates`、`hooks`），不是整段路徑——retro 標籤慣用全形 `／`，整段半形路徑會靜默零命中
     - 三源皆無相關內容時在 prompt 註明「知識前置：三源均無相關內容」（留痕，防跳步）
     - **retro 約束 vs Spec 衝突仲裁**：**衝突成立判準（先驗）**——僅題材重疊／同域**不算**衝突；成立須同時①指認兩邊對撞的**條文原句**（R-NNN 約束句 vs Spec／DoD／契約 row 原文）②寫出**具體後果**（照約束做會違反 Spec 哪一句、產生什麼可觀察的錯誤行為）——寫不出後果＝不是衝突，不記仲裁、兩者照常都守。判準成立時：前置的 retro 約束與本 item 的 Spec／DoD／契約表衝突（新功能有正當理由要做某條約束禁止的事）→ **Spec 優先**，但 writer 與主 flow **不可靜默選邊**：須在交付報告寫仲裁記錄（衝突的 R-NNN、衝突點一句、採用哪邊、理由一句，比照契約仲裁記錄格式）。主 flow 收到後判「該約束前提已變、列 retire 候選」或「Spec 該收緊」——沉默採一邊會讓過期約束無限存活或讓 Spec 悄悄違反硬規則
   - **測試管轄註記**：派工 prompt 附一句「測試自驗只准跑 `python3 .agent-flow/scripts/test_baseline.py mine`，依你定義中的測試管轄規則」（**不傳 `--strike-key`**——該旗標只有 `check` 消費）（writer 層 mine 模式細節住 test-strategy skill，不重述）
     - `[P]` item 在 fan-out（各開 worktree）或循序退回下 mine 模式均適用——隔離樹或逐個執行時未提交變更範圍可正確推導
   - **契約前置與仲裁句（硬性）**：派工 prompt 必須把本 item 的**行為契約表原文**（task 檔的 `契約:` 行，含邊界 row，及 `退場:` 行——writer 須在同一 run 刪除其列出的測試，格式住 task-decomposition skill）貼進硬約束區作為仲裁基準——不是叫 writer 自己翻 task 檔（與知識前置同一教訓，R-011）。
     - 並附一句：「測試紅時先仲裁再動手，對到契約表 row 判哪邊錯；**契約表沒答案 → 帶失敗交付是正確行為，硬湊綠燈才是違規**」
     - 無契約表的 item（Tier 1 無表 fallback）仲裁句改指 DoD
     - writer 以「表沒答案」帶失敗交付時，**主 flow 裁決**：讀 Spec／usage 報告判該行為的預期，把裁決結果補進契約表（表可增補、single source 不變）再回派；Spec 本身有洞才走升級逃生門問使用者
   - **交付稽核（writer 交付時）**——正常交付（記錄對得上）瞄一眼即過，不展開：核對工作報告的「仲裁記錄」——紅過的測試每條都要有仲裁行，判「測試超出契約」者核對 row 引文與 task 檔原文一致（對不上＝假仲裁，退件）。writer 的 mine 模式測試自驗不落檔、不跨對照；改測試湊綠由 checker 核對「契約 row 逐條有對應測試斷言」時現形
修正重審與驗證重用依 `references/efficiency.md`：首輪完整獨立審；僅已審版本到目前 index 的有效 delta 可縮小重審，契約與未解問題仍完整提供。

2. 將變更檔案 `git add` 進 staging area（確保 checker／code-reviewer 可透過 `git diff --cached` 讀取）。
   - **預設派 task-verifier（checker）時，prompt 附 `git diff --cached --stat -- <files>` 輸出**（僅檔名與行數統計，checker 不讀 diff 內容）
   - **升級為 code-reviewer 全 diff 審時，prompt 硬性指示改用 `git diff --cached -- <files>`**（file-scoped 完整 diff）
   - `<files>`＝**當前 sub_task（task）的 `files`**（主 flow 讀 `eval_state.json` 該 sub_task 的 `files` 欄帶入，即該 task 全部 item 的聯集；收斂到當前 task 涉及檔，避免跨 sub_task staging 累積污染）。
     - **注意**：`eval_state.py list-files` 是全 sub_task 聯集，不是單一 sub_task 來源、不可用於此。此收斂為退回主 worktree 循序時的污染修法（與 fan-out 無關、底層必需）。
   - 審查以 task 為界，staging 天然以 task 分批，不另做批前快照
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
   - **升級輪（reviewer）有 🔴 或完成度節列出缺席項** → 走 fixing 迴圈（重裁條款、set-review 均不變；審查結論記 `eval_state`，見步驟 3）；修正後依 `references/efficiency.md` 產生增量 diff，再重跑步驟 3（升級輪，直接派 reviewer，不退回 checker）
   - **🟡-only 快速路徑（省一輪審查稅，僅升級輪適用）**：checker 輪無 🟡 分級——憑據對不上即升級，不適用本路徑。
     - 適用條件：升級輪內，零 🔴、完成度節無缺席、僅 🟡，且 🟡 全屬主 flow 可直接套用的**措辭級**修正（修錯字、對齊術語、補澄清性說明——不改邏輯、不改介面、不動 code 行為；**判斷有疑義時一律歸邏輯級**，省稅是優化、正確性是底線）
     - 適用時：主 flow 套用修正後**不重跑**，該輪即為通過輪、照常 set-verify
     - 任一 🟡 涉及邏輯／行為／介面改動 → 不適用，照常回步驟 3（升級輪）
     - 套用了哪些 🟡 記入該輪處置摘要（隨收尾回報呈現，留痕供稽核）。措辭級不動 code 行為，完成度結論對套用後 diff 仍成立（與 🔴 作廢輪的差異：🔴 的修正可能改 code 行為故禁止沿用，措辭級不改故放行）
   - **發現不得自我授權（scope 防線）**：任何發現（含 🟡 建議）要進 fixing，主 flow 必須先指名其**對映依據**——本 item 的 DoD 條目、契約 row、Spec／spec_inline 句、或既有硬規則（.agent-flow/ROUTER.md／skill 條文）之一，記入該輪處置摘要（隨收尾回報呈現）。
     - 對映不出來的發現不得變成修正工作——處置為駁回（留痕）或 park 進收尾回報請使用者裁決
     - 與步驟 3 的引文核實並存不互代：引文核實防幻覺發現（引的 code 不存在），本條防真發現擴 scope（發現為真但無人要求）
   - **修正迭代上限（僅數升級輪）**：同一 sub_task 的**升級輪**修正 2 輪後 reviewer 仍有 🔴 → 將該 sub_task 的 `status` 設為 `"failed"`、`warning: true`，回報使用者（不自行繼續修）；checker 輪與升級動作本身不計入此上限
5. **本地測試驗證（硬性 gate，對應 .agent-flow/ROUTER.md「部署規則」）**：依 **test-strategy** skill 執行。gate 條件＝**無新增穩定失敗**（以 `.agent-flow/scripts/test_baseline.py check` 的判定為準；baseline 於第一次 step 5 前建立單次快照既有失敗，非確定性失敗由 script 於新失敗時重跑一次確認可重現）
   - **Tier 2：新行為必須有自動化測試**（單元測試隨各實作 item 的 DoD、整合測試 item 由前置 1 分拆時建立，見 task-decomposition skill）；**Tier 1**：自動化測試或實際運行功能驗證皆可
   - 通過 → `local_test_passed: true`、`local_test_evidence` 填 script 輸出摘要（hook 於 commit 時檢查兩欄皆已填）
   - **另**：本步的每一條驗證指令以 wrapper 一次完成「跑＋留痕」：`python3 .agent-flow/scripts/run_verify.py --run-id <run_id> [--sub-task <id>] --cmd "<指令>"`——Tier 2 給 `--sub-task` 記入該 sub_task；Tier 1 免給，自動記 manifest 同名欄並寫 verify_cmd 事件。底層 `add-verification` 保留，直接呼叫仍合法。
     - **與 `local_test_evidence` 並存、不取代它**——語義見 `references/formats.md` 的 `verification_commands`。無 gate 檢查此欄，漏記不會被擋，但該 run 在 `stats.py` 就成了「無記錄」
   - 真新失敗 → 依 skill 的處置：測試過時須記依據（無依據改弱測試視同 🔴）、肇因非本 item 走重開路徑；兩者皆非 → **立即回報使用者裁決（人是計數器，無自修額度）**，不自行空轉迴圈
   - **`[憑據:step5]` 條目在本步收口**：主 flow 逐條核對帶記號的 DoD 條目憑據已補——實跑輸出，或依 test-strategy「視覺類 DoD 的使用者驗收」路徑取得使用者裁決——未補不得通過本 gate（記號定義住 task-decomposition skill；step 3 的 checker 對這些條目只記 🔍 待驗，收口責任在此、不在審查輪）
   - 未通過本步不可進入收尾與 commit。細則（相關測試選擇、零測試專案、豁免窗口）住在 test-strategy skill，不在此重述
6. **收尾順序（**hook 強制**，見「Gate 的硬性執行」，完整清單見 `references/gates.md`）**：
   - ⓪先跑**收尾測試檢查**——範圍**分 tier**（Tier 2：全套 `--strike-key full_suite`；Tier 1：累積聯集 `--strike-key wrapup_related`，不跑全套；指令與空集合處置住 test-strategy skill「Commit 前收尾檢查與重開路徑」節，單一枚舉點、此處不重列）；本 run 的最後一條收尾驗證須由 `run_verify.py --run-id <run_id> --cmd "<收尾檢查指令>"` 執行並記錄程式樹快照。出現新失敗代表相關測試沒抓到的跨 sub_task 破壞，依 skill 的「重開路徑」把肇事 sub_task 改回 in_progress 從步驟 3 重走，**不可收尾**
   - ①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留審查記錄的永久紀錄），**清除 `eval_state.json`**（熱 scratchpad，收尾即清；失敗收尾則保留現場）。manifest 此時仍為 `in_progress`；提交前跑 `python3 .agent-flow/scripts/run_commit.py prepare <run_id>`，憑據過關後改為 `ready_to_commit` 並記下原 HEAD
   - ②**冷溯源檔的進版控範圍**（單一枚舉點，分三類）：
     - **不進版控**（只留在工作目錄、永不清除，不 `git add`）：manifest `run/<run_id>.json`、eval 歸檔檔 `run/<run_id>.eval.json`、測試 baseline `run/<run_id>.test_baseline.json`、事件日誌 `run/<run_id>.events.jsonl`、task 檔 `task/YYYY-MM-DD.md`。本次 commit 的 staged 內容＝循環 step 2 已陸續加入的**程式碼與測試檔**，此處不追加上述任何檔案
     - **進版控**：`spec/<run_id>.md`。它是 intent gate 的依據（manifest `spec_path` 指向它），且具名問題觸發 usage-analyzer／impact-analyzer 後答案寫進 Spec（見 `references/tier2-prep.md`「具名問題觸發」節）——Spec 是本 run 需求的唯一來源，換手者必須讀得到，故隨程式碼一併 `git add`、正常 commit
     - **歷史產物**（`usage/`、`risk/`、`impact/` 三目錄）：既有歷史報告（冷溯源）保留在版控中，**不刪**；這三個目錄無新檔產生，無需 `git add`
     - **依據**：所有消費端（`eval_gates.py`／`stats.py`／`test_baseline.py`／`session_start.py`）都以 `glob("run/*.json")` 從工作目錄讀檔，無一從 git 歷史讀，故「不進版控」那組檔案進不進版控不影響任何既有功能
     - **`Run-Id: <run_id>` trailer 是硬要求**（見子項③）：`run/`／`task/` 系列溯源檔不進版控，它是 commit↔run 之間唯一的機械連結，也是 commit gate 的定位依據。漏寫 → gate 退回「工作目錄 in_progress」安全網，該次 commit 的四欄憑據不被核對（判定全貌見 `references/gates.md`）
     - baseline 的處置要求同住 `test-strategy` skill——其 `stable_failures` 是本 run 進場的既有欠帳快照；**本節與該 skill 須一致，改任一端時對照另一端**
     - **部署建議**：目標專案的 `.gitignore` 可加 `run/`、`task/`，免得 `git status` 長期掛著未追蹤檔。`retro/RETRO.md` **不在此列**——它是派工時貼進 writer prompt 的硬性約束、隨框架部署，照常進版控
     - ②之前：Claude 主 flow 跑 `python3 .agent-flow/scripts/token_usage.py <run_id> --write`，由 transcript **實測**回寫 manifest `subagent_usage`（prep／loop／main）與 `token_usage` 明細（subagents＝transcript ∪ `run/<run_id>.dispatch.jsonl` 派工留痕）；Codex run 設 `harness: "codex"`，同指令記 `token_usage_status: "unknown_codex"`，不將未知用量寫成零（欄位語義住 `references/formats.md`）
   - ③git commit，message 末尾附 `Run-Id: <run_id>` trailer；成功後跑 `python3 .agent-flow/scripts/run_commit.py finalize <run_id>`，核對 Git 實際提交訊息並回填 SHA、`completed`。中斷在兩者之間時，manifest 保持 `ready_to_commit`，照 resume 程序核對 HEAD 後續跑
7. **有條件** 依「派工機制」節派工 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - code-reviewer 無 🔴 → **不呼叫 retro**（reviewer 一次過即無回顧價值）
   - 本條件僅掛**升級輪**（reviewer 判定；邊界直派輪視同升級輪）——checker 通過輪與升級後零 🔴 輪都**不呼叫 retro**；升級本身是流程正常運作、不是教訓

## 派工機制（headless CLI；本節為單一枚舉點）

流程角色（`code-writer`／`task-verifier`／`code-reviewer`／`retro`／`task-decomposer`／`usage-analyzer`／`impact-analyzer`）可由目前 harness 的角色工具或 headless CLI 派工。兩路都遵守共用角色契約、獨立審查與 gate；工具與權限差異住 `.agent-flow/HARNESS.md` 及適配層：

- **指令**：`python3 .agent-flow/scripts/dispatch.py <role> --prompt-file <path> [--backend claude|codex] [--resume <session>] [--files <逗號清單>] [--timeout <秒>] [--max-output-chars <n>]`。後端依 manifest `harness` 選取；明示 `--backend` 可覆寫，舊 manifest 缺 harness 時使用 Claude 相容路徑。角色職責讀共用 `.agent-flow/roles/`，模型與工具設定由各 harness 載體提供
- **prompt 檔**：主 flow 把派工 prompt 全文（含硬性約束區、契約表原文——知識前置規則不變，R-011）寫到 `run/<run_id>.prompt-<role>-<n>.md`（冷溯源檔，不進版控）再派工，不走命令列參數
- **輸出**：stdout＝子 agent 報告全文（主 flow 直接讀）；stderr 摘要行 `[dispatch] role=… backend=… session=<sid> turns=… tokens=… cost_usd=…`；exit 2＝信封 blocking（退件重取，見「主 flow 憑據紀律」）、exit 3＝子程序失敗／超時（預設 1200 秒）／報告超量（預設 60000 字元，截斷）、exit 4＝越界變更（退件；範圍外檔案列在 stderr，優先於 exit 2）
- **越界檢查（主 flow 派 code-writer 時必帶 `--files`，值＝該 item 的 files 欄）**：script 以派工前後的 `git status` 對照，「派工後新出現且不在清單內」的路徑即越界。越界退件時主 flow 先看 stderr 清單裁決（真越界→`--resume` 要求還原；清單漏列→補 files 後照常收），不自行放行
- **修正輪**：同一角色的修正／重取以 `--resume <sid>` 沿用原 session（context 仍熱，省重建稅），`<sid>` 取自上一輪 stderr 摘要行
- **信封驗收內建**：script 以 `report_envelope_check.check_envelope` 判定（單一出處），blocking／advisory 處置同 PostToolUse hook（該 hook 仍掛在 `Agent` 工具路徑上）
- **權限**：CLI 相容模式與原生工具的執行前提見目前 harness 適配層；目前 session 必須已授權該模式。CLI 派工為前景子程序
- **留痕**：每次派工 append `run/<run_id>.dispatch.jsonl`（格式見 `references/formats.md`），`token_usage.py` 收尾時併入用量；gate 7 對命令工具派工指令同樣生效（見 `references/gates.md`）
- **範圍外**：parallel-run／[P] fan-out 使用獨立 Git worktree 與各 harness 的隔離執行方式；不能用背景旗標代替隔離

## Model 指派原則

- agent→model 的可執行設定來源住 `.agent-flow/harnesses/models.json`；指派理由住 repo 根 `MODEL_POLICY.md`：Claude 端由 `.claude/agents/*.md` frontmatter 承載；Codex 端由 `.codex/agents/*.toml`（共用安裝器 `install_harness.py` 產生）承載，`tests/test_model_policy.py` 強制兩端與政策表一致。不同平台各自驗證，不共用模型 ID
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 分拆 task 在主 flow 直建門檻內（≤2 tasks 且 ≤8 items）時由主 flow 直接執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer**（升級輪呼叫）需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached -- <files>`**（命令工具，`<files>`＝當前 sub_task 的 `files` 欄），不要逐檔讀取完整檔案。
  - `git diff` 只回傳變更部分，token 消耗遠低於讀整檔；file-scoped 指令另可避免跨 sub_task staging 累積污染（見循環 step 2）
  - **task-verifier（checker，預設輪呼叫）不讀 diff、不適用本條**——輸入集見循環 step 3，只附 `--stat` 輸出
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **背景執行與權限**：依 `.agent-flow/HARNESS.md` 與目前 harness 適配層執行。主 flow 等待交付與必要的 HITL gate 後才可續跑；流程不授予額外權限。
- **usage-analyzer / task-decomposer**：可依 harness 能力背景產出。usage 答案併入 Spec；task-decomposer 自檢完成後才進計畫確認 gate。Tier 1 仍由主 flow 做輕量計畫確認。

## 主 flow 憑據紀律（回報必附證據）

Flow 對 subagent 有滿滿的防線（引文核實、仲裁稽核、hook gate），但主 flow 自己是無防線單點（R-013——長 run 發生過主 flow 假報進度）。因此：

- **主 flow 的每一句進度宣稱（「已派審」「已修復」「測試通過」「報告已產出」）必須同句附上可驗證憑據**：agent launched 回執、測試輸出尾行、`git diff --cached --stat`、`ls` 檔案存在證明。**沒有憑據的進度句，讀者（含接手者與使用者）應當作未發生。**
- 這是 `local_test_evidence` 精神的推廣：證據要求不只在測試欄位，而在主 flow 所有進度回報。
- **subagent 報告信封缺損 → 二分處置（原則：表現層問題只警告、不觸發付費重試）**：
  - **blocking**（缺終行 `Self-check:`，或 task-verifier 缺兩節關鍵詞）＝疑似截斷或未完成交付，主 flow 不得逕行解析該報告內容，須退件重取（重新呼叫該 subagent）——**重取最多 1 次**；第 2 次仍缺 → 不再重取，主 flow 人工檢視該報告內容（判斷是否完整可用）並在回報留痕一句「信封第 2 次缺損，人工檢視採用／退件」
  - **advisory**（只缺首行戳記行）＝表現層缺項，**不退件**：hook 以 PostToolUse `additionalContext` 回傳警告，主 flow 照常解析報告、在回報留痕一句
  - 由 PostToolUse hook（`.agent-flow/scripts/report_envelope_check.py`）機械偵測——blocking 時 exit 2 的 stderr 即標準化退件訊息；hook 屬品質 lint、fail-open（解析異常放行），人工檢查為兜底、不因 hook 存在而豁免（兩類項目與載荷的單一枚舉點住 `references/gates.md` 信封 lint 節）
- 與 write-ahead 的關係：`eval_state` 的 `step` 欄記的是**意圖**（打算做），憑據才是**動作發生的證明**——兩者缺一不可，resume 時以憑據對賬（見 eval-flow-resume skill）。

## 資料格式與操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .agent-flow/scripts/eval_state.py`——子命令清單、理由與各時機的操作規則住 `references/formats.md` 操作規則節（單一枚舉點，R-007），不在此重列
- **首輪審查結果出來後（step 3）**：執行 `set-review <id> <🔴數> [--dimensions '<json>']`——**checker 輪固定填 0**；升級輪有 🔴／🟡 時 `--dimensions` 必填；commit gate 必填 `<🔴數>`，缺一擋歸檔。參數完整語義與維度詞彙表住 `references/formats.md` 操作規則節
- Run manifest／`eval_state.json`／`events.jsonl` 完整格式、欄位語義與其餘操作規則見 `.agents/skills/eval-flow/references/formats.md`——init 填欄、step 3 記審查結果、resume 對賬、欄位語義查詢時讀取

## Gate 的硬性執行（hook）

各 gate 由 PreToolUse hook 攔截，涵蓋 commit 前的歸檔／防刪除／intent／測試／假測試 lint／不變量檢查，與呼叫流程管制 subagent 時的 phase 狀態機檢查。完整清單、判定條件與窄例外見 `.agents/skills/eval-flow/references/gates.md`——被 gate 攔截需查全貌時讀取。

## 中斷恢復（Resume）

執行中斷（session 掛掉、compact 掉狀態、換 AI 接手）後要續跑時，**依 `eval-flow-resume` skill 的確定性程序恢復**，不靠記憶或猜測：

掃 `run/` 找 `status: "in_progress"` 的 manifest → 依 `phase` 定位前置進度 → 已 `decomposed` 則讀 `eval_state.json` 的 in_progress sub_task 及其 `step`／`files` → 用 `git diff --cached -- <files>` 還原工作現場 → 從該步驟繼續。已 `passed` 的 sub_task 不重跑；hook gates 照常生效。

## Tier B Bootstrap 路徑（骨架工作，無業務邏輯）

判需求為 Tier B（空專案或新模組純骨架、無業務邏輯）時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整路徑（Bootstrap 清單、精簡風險分析、選型 HITL、DoD 與收尾）。

## Hotfix 通道（先止血、後補債；債是硬性的）

使用者明確宣告緊急（線上事故／資損進行中）時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整通道（止血、精簡溯源、commit、補債、欠帳 gate）。

## 單一 run 原則與併發（worktree 隔離）

判斷能否併發多個 run、需要開 worktree 隔離或插單處理時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整規則。

## Tier 2 [P] fan-out（worktree 並行）

`[P]` item ≥2 且各自預估 ≥150 行時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整三段式 fan-out 執行協定（門檻與退回、prep／fan-out／rolling merge 三段、錯誤路徑與批次中斷恢復）。
