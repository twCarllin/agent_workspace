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

## 2026-10-03 搬出（run 2026-10-03-skills-dehistorize：其餘 skills）

### skills/test-strategy/SKILL.md

- —｜實測｜test-strategy:Baseline test_command 直譯器｜幻影欠帳的出生證：系統直譯器缺專案套件使外部專案累積 31 個 stable_failures
- 2026-09-29｜實測｜test-strategy:Baseline test_command 完整組｜TW_Analysis 日常組白名單上線後 `pytest tests/ -q` 靜默降為 695／2,375 筆，收尾檢查無人察覺縮水
- 2026-09-22｜D1｜test-strategy:Writer 層 mine 模式｜mine_log 落檔（script 端零 token 震盪指紋）刪除；`--strike-key` 的 mine 端消費者隨之消失；舊「指定測試檔清單」workaround 作廢
- —｜實測｜test-strategy:Step 5 假測試 lint｜寫 60+ 測試時假測試模式必然重現，retro 散文擋不住、只有 lint 擋得住
- —｜實測｜test-strategy:Mutation self-check｜制度化依據：事後補做 mutation test 才確認斷言有效；stale `.pyc` 曾誤判 2 個測試壞掉；主 flow 獨立重放曾抓到 writer 自報遺漏
- —｜實測｜test-strategy:真新失敗三分類｜「禁止自行調查歸因」的依據：調查燒大量 token 後結論多半是「與本 run 無關」
- 2026-09-29｜使用者裁決｜test-strategy:Commit 前收尾檢查｜收尾檢查分 tier 的依據：框架工作區 49 run＋TW_Analysis 60 run 的收尾全套從未抓到累積聯集漏掉的破壞；Tier 1 指令「--cmd 必須單引號」源自同日 `__suite__` 誤報實測

### skills/eval-flow-resume/SKILL.md

- 2026-09-22｜Q4｜eval-flow-resume:Step 2｜phase 值域收斂為 init→decomposed→completed；依 `usage/<run_id>.md`、`impact_report_path` 判斷卡點的舊邏輯移除；`usage_report_path` 推導 `usage_confirmed` 的分支移除
- 2026-09-22｜Q2｜eval-flow-resume:Step 3｜eval_state 一筆＝一個 task 的裁決碼（原文誤寫 item 降為 items 清單，與 formats.md「不存 item 層資料」矛盾，一併修正）
- 2026-09-22｜D1／Q6｜eval-flow-resume:Step 3 step 表｜審查落檔刪除後 reviewing／fixing 一律重跑並重派 checker；輪數判定改讀 `review_reds`（取代原落檔 `<N>` 接續）；兩項已知缺陷為 D1 換取記帳收斂的代價
- 2026-07-25／2026-09-05｜—｜eval-flow-resume:Step 3 verifying｜task-verifier 於 2026-07-25 退役、2026-09-05 復活為 checker（審查層預設位）
- 2026-07-17｜—｜eval-flow-resume:Step 3 scoring｜評分階段（eval-scorer）已移除，`scoring` 僅為舊 run 相容值

### skills/parallel-run/SKILL.md

- 2026-07-29｜R-005｜parallel-run:步驟 5｜「主 session 先 `git worktree add`、再叫 agent 進去」首次實跑失敗的日期
- —｜實測｜parallel-run:步驟 5 baseRef｜`worktree.baseRef: "head"` 經配對對照實測坐實（`head` 看得到未 push 的 commit ∧ `fresh` 看不到）
- 2026-10-03｜R-006 對齊｜parallel-run:步驟 6｜精簡初始化句原要求 `risk_report_path: "skipped"`／`usage_report_path: "skipped"`，與 eval-flow Tier 1 第 1 點（三欄維持 null）矛盾，改為「report path 欄維持 null」

### skills/task-decomposition/SKILL.md

- 2026-09-22｜D2｜task-decomposition:輸入｜`usage_report_path` 為 null 不再中止拆分
- —｜實測｜task-decomposition:行為契約表 邊界判準｜mine 子命令的 3 條 🔴 全藏在怪檔名輸入裡
- —｜—｜task-decomposition:Step 2 測試估算｜舊「實作 0.5–1 倍」估法作廢（把測試預算綁在實作行數上，變相鼓勵灌測試）
- —｜實測｜task-decomposition:Step 2 校準｜×2 校準源自實測 naive 粗估系統性低估 2–3 倍
- —｜R-017｜task-decomposition:推理密度｜純散文演算法規格曾使 writer 連續 4 次 thinking 燒滿、零產出
- 2026-09-29｜—｜task-decomposition:退場行｜測試退場規則生效日；動機數據：TW_Analysis 近 100 commit 測試函式 +1,786／-616

### skills/usage-scenario-analysis/SKILL.md

- 2026-09-22｜D2｜usage-scenario-analysis:頭註／輸入輸出／輸出格式｜由 Tier 2 預設前置步驟改為具名問題觸發；不再產 `usage/<run_id>.md`、不回寫 `usage_report_path`；本 skill 不再是獨立 HITL 卡點
- —｜R-016｜usage-scenario-analysis:Step 4／Step 6｜一條未驗證的保序假設曾讓整條 flow 空轉數十輪；人打槍一條假設 30 秒 vs flow 空轉數十輪

### skills/root-cause-table/SKILL.md

- 2026-10-03｜—｜root-cause-table:description｜由「根因分類參考表與分析框架，供 retro 回顧反思時使用」擴為含觸發語與不適用於的三段式

## 2026-10-03 搬出（run 2026-10-03-agents-claudemd-dehistorize：agent 定義與 CLAUDE.md）

### .claude/agents/*.md frontmatter `model:` 行內註解（model 變更史；現行指派與理由住 MODEL_POLICY.md）

- 2026-09-29｜使用者裁決｜code-reviewer.md:model｜opus-4-8 → claude-sonnet-5-5（全部 sonnet-5-5）；與 writer 的去相關化改由 session 層承擔（MODEL_POLICY.md 約束節）
- 2026-08-10／2026-09-29｜—｜code-writer.md:model｜sonnet-4-6 → sonnet-5（08-10）→ claude-sonnet-5-5（09-29，近 Opus 級 coding）
- 2026-09-29｜使用者裁決｜impact-analyzer.md／usage-analyzer.md／task-decomposer.md:model｜opus-4-8 → claude-sonnet-5-5
- 2026-09-29｜—｜retro.md:model｜sonnet-4-6 → claude-sonnet-5-5
- 2026-09-29｜使用者裁決｜task-verifier.md:model｜haiku-4-5 → claude-sonnet-5-5（實測 haiku 首輪曾 1 turn 無憑據交付）；驗證以 DoD 逐條對照為主、含少量覆蓋語意判定；假通過率為回退依據

### .claude/agents/*.md description 與本體

- 2026-09-05｜—｜code-reviewer.md:description｜eval-flow 循環 step 3 預設由 code-reviewer 改派 task-verifier（checker），reviewer 退為升級路徑專用
- 2026-07-25｜—｜code-reviewer.md:審查流程 4｜完成度核對自 2026-07-25 起由 reviewer 接手原 task-verifier 職責
- 2026-07-28～30｜實測｜code-reviewer.md:工作守則 行號必須現查｜5 次行號漂移（引文為真、行號偏 1～16 行）皆出自推算或記憶
- 2026-09-05／2026-09-22｜—｜task-verifier.md:description｜checker 成為審查層預設位（09-05）；審查改以 task 為單位（09-22）
- 2026-09-22｜D1｜task-verifier.md:四種升級情況｜升級碼由五類收斂為四類，原「對照 mine_log 摘要」一類隨機制刪除
- 2026-09-22｜D1｜code-writer.md:測試管轄規則 2／5／8｜mine_log 落檔指紋稽核刪除；mine 端 `--strike-key` 消費者消失；原「strike-key 改用 `_sabotage` 後綴分開執行帳」規則作廢
- 2026-09-06｜使用者裁決｜code-writer.md:輸出格式 批次派工｜批次派工（一 task 多 item）逐 item 分節的生效日
- —｜實測｜retro.md:工作流程 2｜「writer 通讀散文教訓無效」為實測結論（R-011 同源）
- 2026-09-22｜Q1｜task-decomposer.md:交付前自檢 3｜「供風險分析對照」隨風險分析刪除而失去對照對象
- —｜—｜task-decomposer.md:交付規則｜原流程於自檢後另呼叫獨立審查 agent，已改為自檢即交付
- 2026-09-22｜D2｜impact-analyzer.md／usage-analyzer.md:description｜由 Tier 2 預設前置改為具名問題觸發
- 2026-09-22｜Q1／D2｜usage-analyzer.md:交付規則｜`usage_confirmed` 隨 phase 值域收斂移除；本 agent 不再是獨立 HITL 卡點

### CLAUDE.md

- 2026-09-06｜v2｜CLAUDE.md:Router 第一步｜「本地開發工具鏈不因檔案類別自動觸碼」的出生證：run 2026-09-06-baseline-suite-guard，25 行本機可復原修改被類別制排除送 Tier 2，前置佔成本 44%
- —｜實測｜CLAUDE.md:Router 第一步｜「行數不預測執行時間」為實測結論
- 2026-09-06｜v2｜CLAUDE.md:Router 第二步 Minimality 尾註｜本節 v2 借 agentflow 理由碼制；被否決的更大替代（devlog 對話制、四層模型 profile、Tier 2 前置 trigger 制）與出生證數據見 `run/2026-09-06-tier-router-v2.json` 的 `spec_inline`
- 2026-09-06｜v2｜CLAUDE.md:防濫用規則｜「本地開發工具鏈不在此清單」為 v2 變更
- 2026-09-22｜Q1｜CLAUDE.md:防濫用規則 升級逃生門／Eval Flow 執行｜前置風險分析移除；eval-flow 前置 0–1 括註原列「風險分析已刪除不設替代、使用情境／影響面盤點改具名問題觸發」
- 2026-09-22｜Q1／D2｜CLAUDE.md:Task Principle｜`usage/`／`impact/`／`risk/` 三目錄自 2026-09-22 起不再是任何步驟的預設輸出目標

## 2026-10-03 搬出（run 2026-10-03-parked-fixes：code-writer 校準標記退役）

使用者裁示刪除 `.claude/agents/code-writer.md` 的五處 `〔校準:sonnet-4-6〕` 標記。**標記刪除、四條規則本體保留**——「逐字引文防偽」被 `.claude/agents/task-verifier.md` 工作流程 2 依賴（核對仲裁行是否逐字引用契約表 row 以抓假仲裁），「2 次上限」被 code-writer 自身的不變量索引引用；刪規則會使 checker 的檢查空轉。以下為各標記原本承載的實測依據。

- 2026-09-22 前｜校準:sonnet-4-6｜code-writer.md:開始工作前 1｜「不要自行通讀 RETRO.md，以約束區為準」的依據：通讀無效為實測結論（與 R-011「知識只有以明文約束前置進 prompt 才有效」同源）
- 2026-09-22 前｜校準:sonnet-4-6｜code-writer.md:測試管轄規則 1｜「禁止邊寫 code 邊寫測試交錯」的依據：每個小步觸發一輪自我質疑是寫不完的主因
- 2026-09-22 前｜校準:sonnet-4-6｜code-writer.md:測試管轄規則 4｜判「測試超出契約」須逐字引用 row 原文的依據：逐字引文防偽（無引文要求時會出現假仲裁）
- 2026-09-22 前｜校準:sonnet-4-6｜code-writer.md:測試管轄規則 5｜「同一失敗測試最多修 2 次」的 2 次這個數字為校準值
- 2026-09-22 前｜校準:sonnet-4-6｜code-writer.md:測試管轄規則 節前說明行｜標記的定義與退場條件原文：「標記＝針對舊模型行為缺陷的防護條款。sonnet-5 實測數個 run 無再犯後，可向使用者提議刪除；未經實測不得自行刪。」——退場條件已於 2026-10-03 由使用者裁示達成（依據：2026-09-22 起 rework 率 0%）

### .claude/hooks/eval_gates.py／MODEL_POLICY.md 過期範例

- 2026-09-22｜Q1｜eval_gates.py:183｜hotfix 缺 debt 欄位的提示訊息範例原列 `["risk", "test", "retro"]`；`risk`（補跑風險分析）類別已隨前置 1 風險分析刪除，範例改為 `["test", "retro"]`（與 rare-paths.md 的 hotfix debt 初值一致）
- 2026-09-22｜Q1｜MODEL_POLICY.md:38｜「主 session／skill 執行（如前置 1 風險分析）」的舉例指向已刪除的機制，改舉現存例子（前置 1 直建門檻內的主 flow 分拆、主 flow 直寫捷徑）

## 2026-10-08 搬出（run 2026-10-08-retro-dispatch-inject：retro 前置改由 dispatch 執行）

### skills/eval-flow/references/writing.md

- 2026-10-08｜2026-10-08-retro-dispatch-inject｜writing.md:step 1 retro 條目｜刪除「主 flow 再補判同類操作／同類風險面的條目」（兩處）：補判要求主 flow 通讀 RETRO.md，與「主 session 不載 RETRO.md」的省 context 目標相反；派工路徑的 retro 條目改由 dispatch.py 依 --files 自動前置，篩選以標籤命中為準

## 2026-10-09 新增（run 2026-10-09-spec-fact-sources：Spec 事實句附來源）

### skills/eval-flow/references/tier2-prep.md

- 2026-10-09｜2026-10-09-spec-fact-sources｜tier2-prep.md:前置 0 事實句附來源｜出生證：10k-analysis 一次 run 的 Spec 以推論寫「insurance_other_cost 一律取絕對值」「ROA／ROE 沿用工業平均規則」，與資料及程式事實矛盾，循環中才發現（5 家勾稽失敗、追加 item）
