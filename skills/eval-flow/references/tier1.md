# Tier 1 初始化與計畫確認

## Tier 1 精簡路徑

理由碼（complexity_reasons）空集合、或僅剩具名重大問題可由點名 advisor 回答的工作（判準住 .agent-flow/ROUTER.md Router，不重列——R-007）。**跳過 Spec 檔與全套 usage 分析，但仍留溯源**。風險由 Router 的理由碼把關（信任邊界／公開契約本體變更根本進不到 Tier 1），故不另跑風險分析。

1. **精簡初始化**：同守上方「共用：進場檢查」（dirty tree 先裁決歸屬，不重列——R-007）。
   - 用 `eval_state.py init-run` 建立 manifest `run/<run_id>.json`；參數與操作範例見 `.agent-flow/FLOW_CLI.md`「Tier 1 初始化與審查」。**`spec_inline`** 記需求原文一句話，取代 `spec_path`。工具設定 `tier: 1`、`phase: "init"` 與憑據初值，不自動判級或確認 HITL。
   - **不建 `eval_state.json`**——Tier 1 的四項憑據（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`）直接記在 manifest 自身欄位（commit gate 憑此四欄放行，豁免的是歸檔檔載體，不是證據本身）
   - **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空，皆空不可往下
   - **事件留痕**：生命週期事件由對應操作自動記錄，不另呼叫 `event` 補記；時機與語義見 `SKILL.md「資料格式與操作規則」`。
2. **直接建 task 檔**：免呼叫 `task-decomposer` subagent，但上限不變——**≤2 tasks、合計 ≤8 items（硬）、各 item 目標 ≤300 行（軟）；每 task 仍 ≤5 items**（單 task 審查可讀性上限不因放寬而破）。
   - 超過 2 tasks／合計超 8 items（task 檔可讀性上限，非判級軸）、或觸發 .agent-flow/ROUTER.md 升級逃生門任一條件（實際規模遠超判級認知、冒出新理由碼、🔴）→ 升級 Tier 2
   - **功能移除類需求**：既有測試的分流依 task-decomposition skill 的「功能移除的測試三分法」（主題＝被刪行為→隨功能刪；主題是存活行為→只拔斷言行；無關→不動），主 flow 建 task 檔時完成分類
   - **DoD 措辭**：主 flow 直建 task 檔的 DoD 與契約 row 同守 task-decomposition 的可驗斷言與「禁不可驗評價詞」規則（清單住該 skill，此處不重列）——Tier 1 不載入該 skill，此指向句即投放路徑
   - **合併審查（省審查稅）**：同一連貫變更（同 `spec_inline` 一句涵蓋、同一個設計決策）的多 items，合計 staged diff 一輪可讀（≤約 400 行）→ **合併為一輪 checker 審**——輸入集為各 item 的 DoD／契約表**聯集**，其餘輸入照循環 step 3 不變。
     - 約束：合併後單輪仍須一次讀完可審（總量失控就拆回）；**all-in 時本捷徑關閉**（逐 item 審）
3. **輕量 HITL**：寫 code 前，把「N tasks／M items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。
   - **事實句**：計畫與 `spec_inline` 中描述既有程式或資料的句子，同守 `tier2-prep.md` 前置 0「事實句附來源」規則（不重列——R-007）；`［假設］` 句一律列入本次提報，由使用者逐條裁示
   - **點名 advisor（有具名重大問題時）**：Router 判 Tier 1 時若理由碼非空（靠具名問題收斂），HITL 一併提報「**問題原文**＋點名的 advisor（`usage-analyzer` 或 `impact-analyzer` 擇需）」——只點 advisor 不說問題＝不合格（agentflow ag.md 原則）
     - 確認後（phase 已 `decomposed`，既有 AGENT_MIN_PHASE 放行）先跑該 advisor（答案寫入 Spec 或 task 計畫備註，不產獨立報告檔、不回寫 report path 欄，同 Tier 2 具名問題觸發語義），拿到答案再進循環
   - 確認後執行下列 `hitl-confirm` 指令，由工具寫入確認範圍、裁示條數、`phase: "decomposed"` 及事件，才進循環。
4. **主 flow 直寫捷徑（可選，全 tier 適用；all-in 時關閉）**：主 flow 判斷「交接是否划算」（行數與檔案類型不是委派依據）——考量 item 是否需要獨立乾淨 context、主 flow 目前 context 負載、item 邏輯是否簡單機械；划算則直接寫 code、不 spawn `code-writer`（省一次全新 agent 重建 context 的稅）。**留痕（硬性）**：每 item 在 manifest 選填欄 `executor_notes` 記一句 `item <id>: 直寫｜派工 — <理由>`（欄位語義見 `SKILL.md「資料格式與操作規則」`），供事後審計選擇是否合理。守則：
   - 「寫的人 ≠ 審的人」防線不變（審的人預設為 `task-verifier`（checker），照常獨立審；升級走循環 step 3 四類觸發同一套規則，改派 `code-reviewer`）
   - 知識前置（三源，見循環 step 1）改由主 flow 自查並在回報留痕
   - 需要獨立 context 的 item（多檔複雜邏輯、主 flow context 已重）仍派 `code-writer`
   - **直寫路徑同受 hook 攔截**：PreToolUse 的 Write／Edit gate 在 manifest `phase` 未達 `decomposed` 時擋下對實作檔的寫入（溯源與規格檔例外：`run/`／`task/`／`spec/`／`retro/`／`eval_state.json`）。確認只認檔不認對話——以 `python3 .agent-flow/scripts/eval_state.py hitl-confirm <run_id> --note "<一句>" [--rulings N]` 留痕並推進 phase；**無人看管的 session（headless）不得自行確認**，該指令會拒絕，正確行為是停在此步、回報計畫與待裁示項後結束，由有人看管的 session 接手。**此 gate 只攔 harness 已接入的檔案寫入工具，不防以命令工具寫檔**（同其他 gate 的防護層級：防照規則推進的誤用，不防刻意繞道）
5. **共用循環**：進入下方循環的步驟 1–7（code-writer → review（per-task，含完成度節）→ 本地測試 → commit）。收尾**不歸檔**（無 `eval_state.json`）：
   - **收尾檢查只跑累積聯集**（step 6 ⓪ 的 Tier 1 範圍：`--strike-key wrapup_related`，不跑全套；指令與空集合處置住 test-strategy skill「Commit 前收尾檢查與重開路徑」節）
   - 獨立審查結論用 `eval_state.py review-run` 記錄；只有本 run 全部 task 已通過獨立審查時才加 `--passed`。測試欄位由 `run_verify.py` 依實際結果寫入。收尾依 step 6 執行 prepare、commit、finalize。
   - 直接 commit **依 step 6 子項② 的處置**（Tier 1 無 eval 歸檔檔與 usage 報告；溯源檔同樣留在工作目錄不 `git add`），message 附 `Run-Id: <run_id>` trailer——**trailer 是 commit gate 的定位依據，不可省**
   - **收尾對溯源檔怎麼處置，以 step 6 子項②為單一枚舉點**，本處與 `SKILL.md「其他路徑」` 內的 fan-out 節皆指向它、不各自重列（R-007——各自重列必漂移）
   - 不執行 eval_state.py 的 archive 操作、不清除任何 scratchpad（本就沒建）
   - step 5 可用實際運行功能驗證取代自動化測試（不強制建測試）；驗證指令以 `run_verify.py` 執行，補充仲裁或豁免說明仍記在 `local_test_evidence`（見循環 step 5）。
