# HISTORY — prose 規則的歷史註記（維護者溯源用）

> **用途**：收納從 `skills/*/SKILL.md`、`skills/*/references/*.md`、`.claude/agents/*.md`、CLAUDE.md 本體搬出的歷史註記——規則「何時改、為何改、改掉了什麼」。本檔**不在任何 skill／agent 的載入路徑內、不進 LLM context**；執行期規則只讀本體現行式陳述。完整證據鏈住 `run/<run_id>.json`（冷溯源，不進版控）與 `retro/RETRO.md`、`retro/BUGLOG.md`。
>
> **行格式**：`- 日期｜run_id 或裁決碼｜原出處檔:節｜摘要一句`。日期＝規則變更生效日；裁決碼＝原 Spec 的 D-／Q-／裁示 # 編號（無則省略）。append-only，依搬出批次分節。

## 2026-10-03 搬出（run 2026-10-03-evalflow-dehistorize：eval-flow 家族）

### skills/eval-flow/SKILL.md

- 2026-09-06｜實測教訓｜SKILL.md:前置 0 進場檢查｜dirty tree 先裁決歸屬的規則源自一次收尾時 staging 與 commit 範圍爆掉的實測
- 2026-09-22｜D2｜SKILL.md:具名問題觸發｜usage-analyzer／impact-analyzer 由 Tier 2 預設前置步驟改為具名問題觸發；不再設 `phase: "usage_confirmed"`；`usage/`／`impact/` 既有報告保留為冷溯源
- 2026-09-22｜Q1｜SKILL.md:前置 1｜多面向風險分析（原前置 1）整個刪除、不設替代機制；出生證：歷來 5 個 Tier 2 run 風險分析 0 次觸 🔴；非邊界類 Tier 2 run 無前置安全面檢查的風險載明於該 run Spec §5 Q1，使用者知情接受
- 2026-09-22｜Q10｜SKILL.md:前置 1｜eval_state 一筆＝一個 task、item 不入 eval_state 的裁決碼
- 2026-09-22｜—｜SKILL.md:HITL gate｜人閘門由「usage 報告確認」移到「分拆完成後」；打回率 0% 的 HITL 曾單次產出 11 條裁示含推翻設計，故價值信號改看裁示數
- 2026-09-06｜v3 使用者裁決｜SKILL.md:循環 step 1 批次派工｜派工單位由 item 改為 task（省 spawn 稅），不再逐 item spawn
- 2026-09-22｜D1｜SKILL.md:循環 step 1 測試管轄註記｜mine_log 落檔與 `--strike-key` 的 mine 端消費者一併刪除；交付稽核的 mine_log 指紋對照隨之刪除，改靠 checker 核對「契約 row 逐條有對應測試斷言」
- 2026-09-06｜—｜SKILL.md:循環 step 1 [P] item｜fan-out／循序退回兩路徑下 mine 範圍可正確推導，舊「指定測試檔清單」workaround 作廢
- 2026-09-22｜D1｜SKILL.md:循環 step 2｜批前快照（修跨批 staging 污染的補丁）刪除——審查改以 task 為界後成因消失，不留替代
- 2026-09-22｜Spec §3.3｜SKILL.md:循環 step 3｜審查單位由 item 改為 task（同 task 全部 item 交付完成後審一次）；checker 輸入集移除批前快照與 mine_log 摘要
- 2026-09-07｜實測｜SKILL.md:循環 step 3 信封註記｜haiku checker 首輪漏交信封／缺節共 3 例，故派工 prompt 末尾加 recency 前置句
- 2026-09-21｜—｜SKILL.md:循環 step 3 邊界直派｜理由碼含信任邊界／公開介面的 run 全部 sub_task 跳過 checker 直派 code-reviewer 的規則生效日
- 2026-09-22｜—｜SKILL.md:循環 step 3 升級觸發｜升級觸發由五類收斂為四類（mine_log 對照觸發隨機制刪除）
- 2026-09-05｜v3｜SKILL.md:循環 step 3｜checker 成為審查層預設位（取代預設派 code-reviewer）；回退機制隨之定義
- 2026-09-22｜D1／Q6｜SKILL.md:循環 step 3 審查落檔｜每輪審查結論不再落檔 `run/<run_id>.review-st<id>-r<N>.md`，只記 eval_state；原 write-ahead 防中斷作廢防線的代價（中斷恢復能力下降）由使用者接受
- 2026-09-05｜B4｜SKILL.md:循環 step 3 set-review｜「checker 輪 🔴 數固定填 0」對應的憑據契約編號
- 2026-09-06｜裁示 #7／#9｜SKILL.md:循環 step 4｜🟡-only 快速路徑（#7）與修正迭代上限只數升級輪（#9）的裁示編號
- 2026-07-17｜—｜SKILL.md:循環 step 5｜「不可進入評分與 commit」中的評分指已移除的 eval-scorer（run 2026-07-17-remove-eval-scorer）
- 2026-09-22｜D1｜SKILL.md:循環 step 6 ①｜審查落檔（`review-st*-r*.md`）與 `mine_log.json` 不再產生
- 2026-09-22｜—｜SKILL.md:循環 step 6 ②｜冷溯源檔不進版控的變更依據：要求進版控會與目標專案既有 `.gitignore`（`run/`／`task/`／`retro/`）衝突，manifest 被擋住時舊版 commit gate 因「以 staged 有無 manifest 為啟動條件」而靜默失效、憑據一項都不驗；`Run-Id` trailer 因此升為硬要求
- 2026-09-06｜使用者裁決｜SKILL.md:循環 step 7｜retro 只掛升級輪、checker 通過輪不呼叫 retro
- 2026-09-29｜D4｜SKILL.md:派工機制｜subagent 派工改走 headless CLI（dispatch.py），harness `Agent` 工具舊路徑仍合法、hook 不擋
- 2026-09-29｜D3｜SKILL.md:派工機制 權限｜headless 子 session 全放行（`--dangerously-skip-permissions`）
- 2026-09-30｜使用者指定｜SKILL.md:Model 指派原則｜Codex exec 全角色統一 `gpt-6.1-sol`／`model_reasoning_effort = "low"`；本體改指向 MODEL_POLICY.md Codex 政策表（單一枚舉點）
- 2026-09-22｜D2｜SKILL.md:Subagent 呼叫原則｜usage-analyzer 的獨立「使用者確認 gate」併入分拆完成後的 HITL gate
- 2026-09-22｜D1｜SKILL.md:主 flow 憑據紀律｜防線清單中的「mine 指紋」已隨 mine_log 刪除
- 2026-09-21｜—｜SKILL.md:主 flow 憑據紀律 信封缺損｜blocking／advisory 二分處置生效日
- 2026-09-07｜實測｜SKILL.md:主 flow 憑據紀律 信封 lint｜PostToolUse hook 機械偵測上線；動機：checker／writer 首輪信封缺損實測 4 例，每例付費重跑一次
- 2026-09-22｜Q1／D2｜SKILL.md:Tier 1 第 1 點｜`risk_report_path`／`usage_report_path`／`impact_report_path` 不再需要顯式填 `"skipped"`，維持 `null` 即預設
- 2026-09-22｜Q7｜SKILL.md:Tier 1 第 1 點｜Tier 1 手動事件留痕收斂為 5 個節點的裁決碼
- 2026-09-06｜v2｜SKILL.md:Tier 1 第 2 點 合併審查｜放寬為「同一連貫變更、合計 ≤約 400 行」；舊「純 prose＋單檔 ≤30 行＋語義同源」三條件為其子集
- 2026-09-06／2026-09-21｜v2｜SKILL.md:Tier 1 第 4 點 直寫捷徑｜v2 擴及 Tier 2（09-06）；委派依據由固定行數硬門檻改為「交接是否划算」（09-21）

### skills/eval-flow/references/formats.md

- 2026-09-06｜—｜formats.md:hitl_rejections｜打回率降為歷史指標；stats.py 舊「趨近 0% 即蓋章候選降級」警告移除
- 2026-09-22｜Q1／D2｜formats.md:phase｜值域由 `init`→`risk_done`→`usage_confirmed`→`decomposed`→`completed` 收斂為 `init`→`decomposed`→`completed`；舊值映射為 `init` 的硬性要求（DoD 2）依據：55 個既有 run 的 resume 依賴此映射；原「`usage_report_path` 非空推導 `usage_confirmed`」分支移除
- 2026-09-19｜實測｜formats.md:subagent_usage｜舊制「依 Agent 工具回執自報、main 憑印象估」廢止——2026-09-14 run 自報 loop 68161，transcript 實測主 flow cache 讀 10.09M，估計法系統性低估流程稅
- 2026-09-21｜—｜formats.md:executor_notes｜直寫捷徑由固定行數硬門檻改為「交接是否划算」判斷的生效日
- （前置 1.5 scout 移除）｜—｜formats.md:scout_report_path｜前置 1.5 scout 已移除，蒐證職責併回 usage-analyzer／impact-analyzer 自掃
- 2026-09-22｜Q1｜formats.md:risk_report_path｜隨前置 1 風險分析刪除而停用；既有 5 份 `risk/*.md` 為冷溯源
- 2026-09-22｜D2｜formats.md:usage_report_path｜task-decomposer 原本以此欄為 `null` 擋人的判定移除
- 2026-09-22｜Q2｜formats.md:eval_state 一筆＝一個 task｜此前一筆＝一個 item
- 2026-09-22｜Q10／Q5｜formats.md:eval_state 不存 item 層資料｜Q10 裁決；Q5「全數就緒才進 step 3」無 hook 強制為 Q10 的已知代價
- 2026-09-22｜Q8｜formats.md:eval_state risk_analysis｜`risk_analysis` 欄位與其 `blocking` 判定自 schema 與 eval_gates.py 移除
- 2026-09-22｜—｜formats.md:eval_state 向後相容｜當時既有 19 份 `run/*.eval.json` 為 item 語義
- 2026-09-21／2026-09-29｜—｜formats.md:events.jsonl｜`args.verify_command` 補指令原文（09-21）；Tier 1 收尾改跑累積聯集 `wrapup_related`、不計入「全套 N」（09-29）
- 2026-09-29｜run 2026-09-29-dispatch-guards｜formats.md:dispatch.jsonl｜`failure`／`out_of_scope` 兩鍵新增
- 2026-09-22｜D2／Q1｜formats.md:操作規則｜具名問題觸發不回寫 report path 欄（D2）；風險分析刪除、`risk_analysis` 與 blocking 判定自 eval_gates.py 移除（Q1）
- 2026-09-05｜—｜formats.md:操作規則 set-verify｜`verify_passed` 語義改為「checker 憑據節通過或升級輪 reviewer 完成度節通過」的生效日
- 2026-09-06｜裁示 #9｜formats.md:操作規則｜修正 2 輪上限只數升級輪
- —｜實測｜formats.md:操作規則 理由｜「一律用 helper script 更新」的出生證：單一 run 手動 Edit 30+ 次

### skills/eval-flow/references/gates.md

- 2026-09-22｜—｜gates.md:待驗 manifest 定位｜冷溯源檔不進版控後，commit gate 改以 Run-Id trailer → staged MANIFEST_RE → 工作目錄安全網三段定位的生效日
- 2026-08-20｜code-review 修正｜gates.md:gate 2｜防刪除 gate 須早於 gate 3 窄例外執行（R-008）的修正來源
- 2026-09-22｜—｜gates.md:gate 5｜假測試 lint 啟動條件由「staged manifest」改為「定位到 manifest」，否則溯源檔不進版控後整條失效
- 2026-09-22｜Q1／Q8｜gates.md:gate 7｜`PHASES` 值域收斂；usage-analyzer／impact-analyzer／task-decomposer 的 `AGENT_MIN_PHASE` 三者收斂為 `init`（風險分析刪除、usage／impact 改具名問題觸發、task-decomposer 改條件派工）；task-decomposer 不再要求 `usage_report_path` 非空；code-writer 的 `risk_analysis.blocking` 遍歷判定為死碼、一併清除
- 2026-09-29｜headless 派工｜gates.md:gate 7｜Bash `dispatch.py <role>` 指令同受 phase gate 的生效日
- 2026-09-07／2026-09-21／2026-09-29｜實測｜gates.md:報告信封 lint｜PostToolUse hook 上線（09-07，載荷依據為實測 `tool_response.content[].text`）；缺項二分（09-21）；dispatch.py 內建同一判定（09-29）

### skills/eval-flow/references/rare-paths.md

- 2026-10-03｜HITL 裁決②｜rare-paths.md:Hotfix 步驟 2／4｜補債清單移除 `risk` 項（改為 `["test", "retro"]`）、`risk_report_path: "deferred"` 移除；`skills/task-risk-analysis` 移至 `skills/_deprecated/`（風險分析已於 2026-09-22 Q1 刪除、不設替代，此為收口）
- （共用樹模型移除）｜—｜rare-paths.md:單一 run 原則｜舊「shared-tree join barrier」概念隨共用樹併發 writer 模型一併移除
- 2026-10-03｜HITL 裁決②｜rare-paths.md:Tier B 步驟 2｜「只跑部署、資料兩面向」改寫為「只檢視部署與資料兩面向的風險」——六面向風險分析 skill 已 deprecated，無 skill 可跑，改為主 flow 自行檢視
