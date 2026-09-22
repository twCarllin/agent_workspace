# 使用情境報告 — Tier 2 流程瘦身（前置收斂、審查改 per-task、記帳收斂）  (run_id: 2026-09-22-tier2-slimming)

> 本次「功能」＝這個 repo 自身的開發流程（Eval Flow）。「使用者」＝流程的執行者與消費者，非終端用戶。
> 情境 id 為下游 `task-decomposition` 每個 item 的對映錨點；一旦定下全程穩定。
> 引用位置以「檔名:行」給證據，供分拆與審查核對。此報告不依賴對話上下文即可讀懂。

## 角色

- **主 flow（Claude）**：流程編排者與最大成本承擔者（實測 88% token）。判級、觸發選配 advisor、建 task 檔或派 task-decomposer、跑循環、收尾記帳。變更後前置由 4 步收斂為 1 步，記帳動作大幅減少。
- **code-writer（subagent）**：批次派工單位＝task，同 task 多 item 一次派；mine 模式測試自驗保留，只停 `mine_log.json` 落檔與稽核。
- **task-verifier（checker，subagent）**：預設審查者，不讀 diff。審查單位由 item 改為 task；輸入集由「單 item DoD＋批前快照＋mine_log」改為「同 task 各 item DoD／契約表聯集」（批前快照、mine_log 摘要兩項輸入被移除）。
- **code-reviewer（subagent）**：升級輪／邊界直派全 diff 審。Spec §3.1 提到審查 prompt 可能增列 security pass（待 Q1 裁示）。
- **usage-analyzer（subagent）**：由 Tier 2 預設步驟改為「具名問題觸發」；答案寫進 Spec，不再產 `usage/<run_id>.md`。
- **impact-analyzer（subagent）**：同上，答案寫進 Spec，不再產 `impact/<run_id>.md`。
- **task-decomposer（subagent）**：由「一律派」改為「條件派」（>2 tasks 或 >8 items 才派）；其 `usage_report_path` 空／`"skipped"` 兩條擋人判定隨前置 2 降級一併移除。
- **retro（subagent）**：不在本次變更標的內，但共用收尾階段；需確認 events/manifest 欄位收斂不影響其寫入。
- **PreToolUse hook `eval_gates.py`（自動判定）**：以 `PHASES` 狀態機與 `AGENT_MIN_PHASE` 攔截亂序 subagent 呼叫與不合規 commit。本次改 `PHASES`（5→3 值）、`AGENT_MIN_PHASE`、`manifest_phase()`、task-decomposer 專屬判定。
- **人類使用者（HITL 裁示者）**：唯一的前置 gate 由「usage 報告確認」改掛「Spec 開放問題裁示＋task 計畫確認」（合為一次）。裁示條數（`hitl_rulings`）是唯一量測到價值的信號，須續記。
- **resume session（`eval-flow-resume`）**：接手中斷 run，依 manifest `phase` 與 `review-st` 落檔對賬定位進度。本次 `phase` 值域收斂與審查落檔刪除**直接波及**其恢復邏輯（消費點 `skills/eval-flow-resume/SKILL.md:23-27,43-50`）。
- **`stats.py`（遙測消費者）**：讀 `sub_tasks`（`review_reds`／`checked_by`／rework）、`events.jsonl`、`token_usage`。審查粒度改變後分母語義變，且須同時吃新舊兩種 sub_task 形狀（消費點 `stats.py:174-207`）。
- **`session_start.py`（副作用被影響者）**：session 啟動時讀殘留 manifest `phase` 提醒未收尾 run（消費點 `session_start.py:29-52`）。不主動操作流程，但顯示 `phase` 字串。
- **下游 10 個專案的部署（`init.sh`／`doctor.py`）**：`init.sh` 複製 `CLAUDE.md`／`.claude/agents/*`／`.claude/hooks/*` 到各專案；未重跑者仍跑舊流程，形成新舊混合狀態。`doctor.py` 為部署健檢（DoD 6）。

## 情境

### A — Tier 2 需求走新前置（4 步 → 1 步）  角色: 主 flow、人類使用者
- 前置: Router 判為 Tier 2；manifest 已建（phase=init）、Spec 路徑已填。
- 操作: 前置 0 初始化 → （不再預設跑風險分析／usage／impact）→ 主 flow 若有具名問題則觸發選配 advisor（情境 B）→ 分拆（情境 C）→ 輕量 HITL 提報 Spec 開放問題＋task 計畫（情境 G）→ 使用者裁示後進循環。
- 預期: 前置產出物由 1725 行報告收斂為「Spec 內裁示條數＋task 檔」；phase 直接 init → decomposed。
- I/O: input Spec＋Router 判級；output task 檔＋manifest.phase=decomposed；副作用 manifest 寫 `hitl_confirmed_at`／`hitl_rulings`、events 記 `init`／`hitl_confirmed`；**不**產 risk/usage/impact 報告檔。

### A-err1 — 非邊界類 Tier 2 run 無安全檢查點  角色: 主 flow、code-reviewer
- 觸發: 理由碼純「跨子系統協調」而入 Tier 2（不含信任邊界／公開契約），前置 1 刪除後既不觸發「邊界直派全 diff 審」，也無風險分析。
- 預期: 依 Q1 裁示——(a) 接受風險由 per-task 審查承擔；或 (b) 所有 Tier 2 審查 prompt 加 security pass。**此情境的處置由 Q1 決定**（見開放問題節）。
- I/O: input 理由碼清單；output 安全面覆蓋策略；副作用 審查 prompt 內容（若選 b）。

### B — 主 flow 具名問題觸發選配 advisor  角色: 主 flow、usage-analyzer／impact-analyzer
- 前置: phase=init；主 flow 寫得出要回答的具名問題（附問題原文）。
- 操作: 「這功能有哪些角色會用？」→ 派 usage-analyzer；「這模組既有呼叫端有哪些？」→ 派 impact-analyzer。answer 寫回 Spec。
- 預期: advisor 回答具體問題，答案併入 Spec；不產獨立報告檔。hook 對這兩個 agent 的 `AGENT_MIN_PHASE` 改為 `init`（隨時可觸發）。
- I/O: input 具名問題原文；output 寫進 Spec 的答案；副作用 Spec 檔追加、`AGENT_MIN_PHASE` 放行（消費點 `eval_gates.py:62-67`）。

### B-err1 — 只點名 advisor 未附問題原文  角色: 主 flow
- 觸發: 主 flow 點名 usage/impact-analyzer 但無具名問題原文。
- 預期: 不合格（沿用 Tier 1 精簡路徑 advisor 規則），不得觸發。
- I/O: input 缺問題原文的觸發；output 拒絕／要求補問題；副作用 無。

### C — 條件派工分拆  角色: 主 flow、task-decomposer
- 前置: phase=init；Spec 開放問題已裁示（或無開放問題）。
- 操作: 主 flow 估規模——預估 ≤2 tasks／≤8 items → 主 flow 直建 task 檔（比照 Tier 1）；超過 → 派 task-decomposer。
- 預期: task 檔產出，manifest.phase→decomposed；`task-decomposer` 的 `AGENT_MIN_PHASE` 改為 `init`。
- I/O: input Spec＋規模估計；output `task/<當日>.md`＋manifest.task_file；副作用 manifest.phase=decomposed。

### C-edge1 — 規模落在閾值邊界／估錯  角色: 主 flow
- 觸發: 預估恰為 2 tasks／8 items（含），或估 ≤8 實際超出。
- 預期: 需明確定義「≤2 tasks 且 ≤8 items」為主 flow 直建的界（含或不含邊界值須寫死於 skill）；估錯時的補救（升級為派 task-decomposer 或分批）須有規則。
- I/O: input 規模估計；output 派工路徑決策；副作用 無。（此界的精確定義見 Q4 相關討論。）

### D — 循環 per-task 審查  角色: 主 flow、task-verifier、code-reviewer
- 前置: 同一 task 的全部 item 由 code-writer 交付完成。
- 操作: 主 flow 以 **task** 為單位派審（輸入集＝各 item DoD／契約表聯集＋writer 工作報告＋`git diff --cached --stat`＋測試輸出尾段；**移除**批前快照與 mine_log 兩項輸入）→ checker 兩節報告（完成度節＋憑據節）→ 有 🔴 則升級 code-reviewer。
- 預期: 審查結論記入 `eval_state` 的 `review_reds`／`checked_by`＋收尾回報；**不**落 `run/<run_id>.review-st*-r*.md`。gate 條件仍為「無新增穩定失敗」。
- I/O: input task 聯集輸入集；output review_reds（非負整數）＋checked_by；副作用 `eval_state` 寫 review_reds／checked_by（消費點 `eval_gates.py:114-120` 憑據驗證、`stats.py:194-207` checked_by 分佈）。

### D-err1 — 一個 task 內某 item 失敗、其他 item 通過  角色: 主 flow、code-writer、task-verifier
- 觸發: 批次派工的失敗隔離（`eval-flow/SKILL.md:73` ④「單 item 帶失敗只退該 item，其餘照收」）遇上「審查以 task 為單位」（Spec §3.3）。審查輸入集是各 item DoD 聯集，但失敗 item 未交付。
- 預期: 需裁示處置——(a) 等失敗 item 補齊後才審整個 task；(b) 先審通過 item、失敗 item 補齊後補審。且 `review_reds`／`checked_by` 記在 task 還是仍逐 item，須明確。**此情境處置由 Q5 決定**（見開放問題節）。
- I/O: input 部分交付的 task；output 審查觸發時機＋憑據歸屬；副作用 review_reds 歸屬粒度。

### D-err2 — 審查輪執行中斷（落檔已刪，接手者恢復依據消失）  角色: resume session、主 flow
- 觸發: 審查落檔 `run/<run_id>.review-st*-r*.md` 刪除後，中斷發生在 reviewing／fixing 階段。
- 預期: 依 D1 使用者裁示，中斷恢復能力下降屬「已接受代價」；`eval-flow-resume` 須改為「審查輪中斷即重跑該輪」。但原本靠落檔恢復的三件事——①該輪是否真發生過、②`checked_by` 決定重派對象（checker vs 升級 reviewer）、③輪數 `<N>` 接續（2 輪上限計數）——刪檔後失去依據（消費點 `eval-flow-resume/SKILL.md:43-44,50`）。恢復改法須確認。**此情境處置由 Q6 決定**。
- I/O: input 中斷的 in_progress sub_task；output 重派對象＋輪數；副作用 `eval_state` 的 step／review_reds 恢復。

### E — per-task 本地測試＋全套測試整 run 一次  角色: 主 flow、task-verifier
- 前置: task 審查通過。
- 操作: step 5 每 **task** 跑一次相關測試（不再每 item）；全套測試整個 run 只在 step 6 ⓪ 跑一次，step 5 不重跑全套。
- 預期: `test_baseline.py check --strike-key full_suite` 無新增穩定失敗；「既有測試只增不改」不變；真新失敗立即回報使用者裁決（人是計數器）。
- I/O: input task 相關測試範圍；output local_test_passed＋local_test_evidence；副作用 events 記 `verified`／`full_suite`（消費點 `stats.py:78-107,101` full_suite；`eval_gates.py:107-113` 憑據驗證）。

### F — 收尾記帳收斂（D1）  角色: 主 flow
- 前置: 全 task 循環完成。
- 操作: 歸檔 `eval_state.json`→`run/<run_id>.eval.json`；`token_usage.py --write` 收尾實測一次；manifest 填 status／phase=completed＋四欄憑據＋tier_rationale；events 收斂為 5 節點（init／hitl_confirmed／reviewed／verified／completed）。收尾清除 eval_state（審查落檔／mine_log 因已不產生故無需清）。
- 預期: `stats.py` 的成本比、時距、rework、checked_by 仍可統計；`token_usage.py` 保留不動。
- I/O: input 循環結果；output `run/<run_id>.eval.json`＋manifest.completed＋events 5 節點＋token_usage 欄；副作用 消費點 `stats.py:157,174-207,233`、`token_usage` 欄。

### F-err1 — events 節點名稱與 stats.py 期望不符  角色: 主 flow、stats.py
- 觸發: 5 節點命名（init／hitl_confirmed／reviewed／verified／completed）與 `stats.py:78-107` 的 `_events_summary`（count／span_seconds／reentry／full_suite）計數依賴不一致。
- 預期: `_events_summary` 依 `ts` 取極值、依 cmd+step 計數、無 events 顯示「無記錄」——節點收斂後 span／reentry 仍須算得出；`full_suite` 事件仍須存在（step 6 ⓪）。命名對應須逐一核對，缺節即統計失真。
- I/O: input events.jsonl；output 時距／重入統計；副作用 無（統計失真為可觀察差異）。

### G — HITL gate 改掛點（Spec 開放問題＋task 計畫合為一次）  角色: 主 flow、人類使用者
- 前置: Spec 有開放問題或 task 計畫待確認。
- 操作: 主 flow 輕量提報 Spec 開放問題＋task 計畫，使用者逐條裁示。
- 預期: 裁示寫回 Spec／manifest；`hitl_confirmed_at`／`hitl_rulings` 欄位語義不變，續記裁示條數。原「usage 報告確認」gate 移除。
- I/O: input Spec 開放問題；output 裁示條數（hitl_rulings）；副作用 manifest 寫 hitl_confirmed_at／hitl_rulings、events 記 `hitl_confirmed`。

### H — PreToolUse hook 新 phase 狀態機放行／攔截  角色: eval_gates.py、主 flow
- 前置: hook 已改為新 `PHASES = ["init", "decomposed", "completed"]`、`AGENT_MIN_PHASE` 三 agent 改 `init`。
- 操作: 主 flow 呼叫 subagent → hook 讀 manifest.phase、比對 `AGENT_MIN_PHASE` 放行或 block。
- 預期: usage/impact/task-decomposer 於 phase=init 即放行；code-writer 需 decomposed。task-decomposer 的 `usage_report_path` 空／`"skipped"` 兩條擋人判定移除（消費點 `eval_gates.py:414-419`）。
- I/O: input subagent 呼叫；output exit 0（放行）／exit 2（block）；副作用 `run/gate_hits.log`。

### H-err1 — 舊 manifest（risk_done／usage_confirmed）遇新 hook  角色: eval_gates.py、resume session
- 觸發: 55 個既有 run 的 manifest.phase 為 `risk_done`／`usage_confirmed`，新 `PHASES` 只有 3 值。
- 預期: `manifest_phase()` 必須在 `PHASES.index()` **之前**把 `risk_done`／`usage_confirmed` 映射為 `init`（消費點 `eval_gates.py:181-187,408`）；不可靠 try/except 兜底（吞例外使 gate 靜默走偏，R-005 同型）。DoD 2 要求以真實舊 manifest 形狀測試 `check_task_gate` 不拋例外。
- I/O: input 舊 phase 值；output 映射為 init；副作用 gate 正確攔截。被破壞時：`PHASES.index("risk_done")` 拋 ValueError → hook exit 非 2 → gate 靜默不套用（55 run 全 resume 失效）。

### H-err2 — 新 manifest（init／decomposed／completed）遇未重部署的舊 hook  角色: eval_gates.py（下游專案）
- 觸發: 某下游專案 hook 仍為舊版（PHASES 含 5 值），操作者手上 skill 已新版，manifest 只產生 init／decomposed／completed。
- 預期: init／decomposed／completed 三值皆在舊 `PHASES` 值域內 → 舊 `PHASES.index()` 找得到，不拋例外 → **雙向相容成立**（風險報告 §5 對策）。此情境須有測試或推論坐實「新值 ⊂ 舊值域」。
- I/O: input 新 phase 值；output 舊 hook 正常比對；副作用 無。

### I — Tier 1 精簡路徑受 per-task 審查波及  角色: 主 flow、task-verifier
- 前置: Tier 1 run 走精簡路徑，共用循環 step 1–7。
- 操作: 循環 step 3 審查／step 5 測試改 per-task 的條文若寫在共用段，Tier 1 一併適用。
- 預期: Tier 1 的審查粒度變更須確認不破壞其既有「單 item task 照舊」路徑（`eval-flow/SKILL.md:73`「單 item 的 task 照舊」）；Tier 1 manifest 四欄憑據驗證（`eval_gates.py:169-171`）不受影響。
- I/O: input Tier 1 循環；output 審查／測試觸發；副作用 manifest 四欄憑據。

### J — resume session 恢復中斷 run  角色: resume session
- 前置: 有 in_progress manifest 待恢復。
- 操作: 依 manifest.phase 定位前置進度（`eval-flow-resume/SKILL.md:21-27`）→ 循環內依 step 欄與憑據對賬。
- 預期: 新流程下 phase 只會是 init／decomposed／completed；resume 的 `risk_done`／`usage_confirmed` 兩列恢復動作（依 `usage/<run_id>.md` 是否存在判斷 HITL 卡點、依 impact_report_path 判斷前置 2.5）在新流程下永不觸發，且 usage 檔可能永不產生——該段恢復語義須改寫。**此情境處置由 Q4 決定**。
- I/O: input 殘留 manifest／eval_state；output 續跑起點；副作用 回報 run 現況摘要。

### K — stats.py 統計新舊混合  角色: stats.py
- 前置: `run/` 下同時有舊制（per-item sub_tasks）與新制（per-task）歸檔檔。
- 操作: `stats.py` 掃全部 `run/*.eval.json`，逐 sub_task 累計 rework／checked_by／sub_tasks 數。
- 預期: 須同時吃兩種形狀且不崩潰（消費點 `stats.py:174-207`）；rework 分母（sub_task 數）語義因粒度改變而不連續，收尾回報須註明統計斷點日期。`review_reds` 頂層優先、legacy fallback rounds 的既有寬容邏輯（`stats.py:177-184`）須維持。
- I/O: input 新舊歸檔檔；output 統計數字＋斷點註記；副作用 無。被破壞時：新形狀缺 `review_reds`／`checked_by` 鍵時應計「無記錄」而非崩潰。

### L — init.sh 部署＋doctor.py 健檢  角色: 下游 10 專案部署、doctor.py
- 前置: 本 run 改完並本地測試通過。
- 操作: 重跑 `init.sh` 把新 CLAUDE.md／agents／hooks 複製到各專案 → `doctor.py` 健檢。
- 預期: `doctor.py` 通過（DoD 6）；收尾回報明列「需重跑 init.sh」。未重部署專案仍跑舊流程（雙向相容承接，見 H-err2）。
- I/O: input 新框架檔；output 部署＋健檢結果；副作用 10 專案的 .claude 內容更新。

## 與現有功能互動點

- **`eval_gates.py`（PHASES／AGENT_MIN_PHASE／manifest_phase／check_task_gate）**：本次核心改動點。回歸風險最高——`PHASES.index()` 對舊值拋例外會使 gate 靜默失效（H-err1，R-005 同型）。task-decomposer 專屬判定移除（`:414-419`）須同步。
- **`eval-flow-resume` skill**：`phase` 值域收斂與審查落檔刪除**直接波及**其 Step 2／Step 3 恢復邏輯（`:23-27,43-50`）。這是最大的隱性回歸面——Spec 未列入 §3.5 排除，屬本次應動範圍，但改法未定（Q4／Q6）。
- **`stats.py`**：審查粒度改變使 rework／checked_by 分母語義不連續；須同時吃新舊 sub_task 形狀（K）。events 節點收斂須與 `_events_summary` 對齊（F-err1）。
- **`session_start.py`（`:29-52`）**：讀殘留 manifest.phase——新舊值皆為字串可讀，無 index 操作，無害；但為求完整列為互動點。
- **`code-writer.md`／`task-verifier.md`**：批次派工失敗隔離與 per-task 審查的介面（D-err1）；批前快照與 mine_log 輸入移除須同步刪除 agent 定義內對應段落（DoD 4 grep 核銷）。
- **Tier 1 精簡路徑**：共用循環 step 1–7，per-task 條文若寫在共用段會一併波及（I）。
- **`token_usage.py`**：保留不動，但收尾順序（step 6 ②，R-007 單一枚舉點）不可被記帳收斂動到（DoD 7）。

## 正確性假設清單（需使用者逐條裁示）

1. **新 phase 值域是舊值域的子集**（init／decomposed／completed ∈ 舊 5 值）——支撐 H-err2 雙向相容。消費點 `eval_gates.py:408`（`PHASES.index(phase)`）。被破壞時：舊 hook 讀到不在舊值域的新值 → `ValueError` → exit 非 2 → gate 靜默不套用。（可觀察差異明確，屬真需求，須測試或推論坐實。）
2. **`manifest_phase()` 的舊值映射必須先於 `PHASES.index()` 發生，且不得用 try/except 吞例外**——支撐 H-err1。消費點 `eval_gates.py:178-187,408`。被破壞時：`risk_done`／`usage_confirmed` 未映射即 index → ValueError → gate 靜默 → 55 個舊 run 全部 resume 失效。（可觀察差異明確，屬真需求。）
3. **events 5 節點足以支撐 `stats.py` 的時距與重入分析**。消費點 `stats.py:78-107`（`_events_summary` 依 `ts` 取 span、依 cmd+step 計 reentry、`full_suite` 旗標）。被破壞時：若收斂掉了 `set-step` 類重入事件，reentry（重試信號）恆為 0，成本論證失真。（差異可觀察，屬真需求——但須確認 5 節點是否含足夠的重入信號，否則此假設實際不成立，見 Q7。）
4. **`review_reds` 仍為每筆 sub_task 一個非負整數**，且 per-task 後每 task 一筆憑據足以通過 `_validate_credentials`。消費點 `eval_gates.py:114-120`、`stats.py:177-184`。被破壞時：per-task 下 review_reds 若記在 item 層而 gate 驗 task 層（或反之），憑據驗證找不到值即 block。（此假設之成立與否取決於 Q2 的 sub_tasks 結構裁示——非獨立需求，隨 Q2 定。）
5. **`token_usage.py --write` 的收尾位置（step 6 ②）為單一枚舉點，記帳收斂不得移動它**（R-007）。消費點 `eval-flow/SKILL.md:150` 收尾順序、DoD 7。被破壞時：`git add` 枚舉點分裂，重演 R-007 漏改。（差異可觀察，屬真需求。）

## 開放問題（需使用者確認）

> Spec §5 已列 Q1–Q3，不重述。以下先標明 Q1–Q3 各牽動哪些情境，再列本報告新發現的 Q4 起。

**Q1–Q3 對本報告情境的牽動：**
- **Q1（非邊界類 Tier 2 的 security pass）** → 牽動 **A-err1**、**D**（審查 prompt 是否加 security pass 段）。未裁示前 A-err1 的處置懸空。
- **Q2（sub_tasks 結構：per-task 一筆 vs 結構不動）** → 牽動 **D**（review_reds 歸屬）、**F**、**K**（stats.py 分母語義）、以及正確性假設 4（憑據驗證粒度）。此裁示是 D-err1／Q5 的前提。
- **Q3（`usage/`／`impact/` 目錄慣例去留）** → 牽動 **B**（答案寫 Spec vs 仍可落檔）、**J**（resume 依 `usage/<run_id>.md` 是否存在判斷 HITL 卡點）。

**本報告新發現的開放問題：**

1. **Q4 — `eval-flow-resume` 的前置恢復語義如何改寫？** 預設傾向：把 resume Step 2 的 `risk_done`／`usage_confirmed` 兩列刪除，phase 只餘 init／decomposed／completed 三列，`init` 列的恢復動作改為「檢查 task_file／hitl_confirmed_at 定位卡在 HITL 前或分拆前」；不再依 `usage/<run_id>.md` 存在與否判斷。若改 A（只補映射、resume skill 條文不動）則舊條文指向永不存在的 usage 檔、指向不再產生的 phase，接手者會依失效指引誤判進度。此外 C-edge1「≤2 tasks 且 ≤8 items」的邊界值含否（是否含 2／8）須在 skill 寫死，避免估界爭議。**牽動 J、C-edge1。**（註：`eval-flow-resume` 不在 Spec §3.5 排除清單內，屬本次應動範圍。）

2. **Q5 — per-task 審查下，「一個 item 失敗、其他 item 通過」如何處置？** 批次派工失敗隔離（`eval-flow/SKILL.md:73` ④只退失敗 item）與「審查以 task 為單位、輸入集為各 item DoD 聯集」（Spec §3.3）在部分交付時衝突：失敗 item 未交付，聯集輸入不完整。預設傾向：(a) 等失敗 item 補齊後才審整個 task（審查輸入完整、review_reds 記在 task 層乾淨）。若改 (b) 先審通過 item、失敗補齊後補審，則同一 task 會有多輪部分審查，review_reds 歸屬與 2 輪上限計數變模糊。此裁示以 Q2 的 sub_tasks 結構為前提。**牽動 D-err1、D、F。**

3. **Q6 — 審查落檔刪除後，`eval-flow-resume` 的 reviewing／fixing 恢復三要素如何替代？** 原本靠 `run/<run_id>.review-st<id>-r<N>.md` 恢復的三件事——①該輪是否真發生過、②`checked_by` 決定重派 checker 或升級 reviewer、③輪數 `<N>` 接續（2 輪上限計數）——刪檔後失依據（消費點 `eval-flow-resume/SKILL.md:43-44,50`）。風險報告對策只說「中斷需重跑該輪」。預設傾向：改為「reviewing／fixing 中斷一律重跑該輪、重派 checker、輪數以 `eval_state` 的 `review_reds` 是否已寫判斷是否已完成過至少一輪」——即把恢復依據從落檔改為 `eval_state` 現有欄位。若無替代方案而僅刪落檔，則中斷在升級 reviewer 的修正輪時，接手者會誤降回 checker、且輪數歸零可能突破 2 輪上限。**牽動 D-err2、J。**

4. **Q7 — events 收斂為 5 節點是否保留了「重入（重試）信號」？** `stats.py:78-107` 的 reentry 統計依 `set-step`／`cmd+step` 計數作為重試信號；Spec §3.4 的 5 節點（init／hitl_confirmed／reviewed／verified／completed）看似不含逐步 set-step 事件。預設傾向：確認 reentry 是否仍為 stats.py 的 load-bearing 指標——若是，5 節點需保留能反映重入的粒度（或明確接受 reentry 統計退化為 0）；若 reentry 已非關鍵指標，則正確性假設 3 可降級。差異：reentry 恆 0 會讓「重試信號」失效。此為避免砍掉 stats.py 仍在用的信號（D1 明言「砍掉就無法再用數據論證流程好壞」）。**牽動 F-err1、正確性假設 3。**

Self-check: 已窮舉 14 類角色與 12 條 happy path＋7 條邊界／異常情境（含舊/新 manifest×hook 雙向、per-task 部分失敗、審查中斷恢復、stats 新舊混合），每情境有穩定 id 與含副作用的 I/O 契約，Q1–Q3 已對映情境且新增 Q4–Q7，未擴大 Spec §3.5 排除範圍；報告待使用者逐條裁示開放問題後才可回寫 manifest。
