# Spec — Tier 2 流程瘦身（前置收斂、審查改 per-task、記帳收斂）

- **run_id**：`2026-09-22-tier2-slimming`
- **建立**：2026-09-22
- **來源**：使用者反映「Tier 2 太浪費時間」，要求參考 agentflow 的 skill 設計與本 repo 歷次 run 的實測遙測，判定哪些步驟不需要。使用者已裁示兩項開放決策（見「§2 已裁示的決策」）。

---

## §1 問題陳述（出生證數據）

`python3 .claude/hooks/stats.py` 於 2026-09-22 的實測（55 個 run）：

| 指標 | 實測值 |
|---|---|
| tier 分佈 | Tier 1 ×50、Tier 2 ×5 |
| Tier 2 的前置 1 風險分析 | 5 份、243 行，🔴 觸發 **0 次** |
| Tier 2 的前置 2 usage 報告 | 5 份、792 行，HITL 打回 **0 次**，裁示 5–11 條／run |
| Tier 2 的前置 2.5 impact 報告 | 5 份、690 行，**無任何消費證據** |
| Tier 2 的 sub_task 審查 | 24 個 sub_task，合計 🔴 **1 個** |
| checker 升級率 | 0/4 |
| rework 率（首輪即有 🔴） | 5%（3/62） |
| 主 flow vs subagent token（4 個有實測的 run） | 主 flow 佔 **88%**（main 35.8M／loop 4.9M） |

三項結論：

1. **前置產出物與其攔截效果不成比例**。1725 行前置報告（risk＋usage＋impact）換到 0 個 🔴。唯一量測到價值的是 usage 報告的 **HITL 裁示條數**（5–11 條／run），而非情境枚舉本身。
2. **審查粒度過細**。24 個 sub_task 的逐 item 審查只抓到 1 個 🔴。
3. **成本在主 flow 的記帳，不在 subagent**。88% 的 token 花在主 flow，而主 flow 單一 run 內的記帳動作約 30 次（review 落檔、批前快照、mine_log 稽核、events、manifest 欄位、token_usage）。

**已知取樣限制（不得隱瞞）**：上述 5 個 Tier 2 run **全部是框架修改自己**，且依 Router v2（2026-09-06 起本地開發工具鏈不觸信任邊界）重判，其中 4 個會落到 Tier 1。Tier 2 幾乎沒有在真實 domain 專案上跑過。使用者已知此限制並裁示直接執行，不先做 domain 驗證。

## §2 已裁示的決策（使用者，2026-09-22）

**D1 — 記帳收斂到「中度」**：停掉過程留痕，保留量測能力。
- 停：每輪審查落檔 `run/<run_id>.review-st*-r*.md`、批前 `--stat` 快照、`run/<run_id>.mine_log.json`
- 留：`events.jsonl`（只記 5 個節點）、`token_usage.py` 收尾一次實測、manifest 四欄憑據＋`tier_rationale`
- 理由：`stats.py` 的成本比與時距分析依賴 events 與 token_usage，砍掉就無法再用數據論證流程好壞。

**D2 — usage-analyzer 與 impact-analyzer 都保留，但改為具名問題觸發**：
- 兩者皆**不再是 Tier 2 的預設步驟**
- 觸發條件：主 flow 寫得出要回答的**具名問題**（「這個模組的既有呼叫端有哪些？」→ impact；「這功能有哪些角色會用？」→ usage）。只點名 agent 而不附問題原文＝不合格（沿用 Tier 1 精簡路徑既有的 advisor 規則）
- 產出：答案**寫進 Spec**，不再產獨立報告檔（`usage/<run_id>.md`、`impact/<run_id>.md`）

## §3 目標狀態

### 3.1 Tier 2 前置：4 步 → 1 步

| 現行 | 變更後 |
|---|---|
| 前置 0 初始化 | **保留**（manifest＋eval_state＋Spec 路徑；intent gate 不變） |
| 前置 1 多面向風險分析 | **刪除，不設替代機制**（Q1 裁示）。邊界類理由碼仍觸發「直派 code-reviewer 全 diff 審」，該路徑不變；非邊界類 Tier 2 run 將無安全面檢查，風險已載明於 §5 Q1 |
| 前置 2 使用情境分析（預設跑） | **改具名問題觸發**（D2）。不再有「報告產出 → 使用者確認報告」的 gate |
| 前置 2.5 影響面盤點（預設跑） | **改具名問題觸發**（D2） |
| 前置 3 分拆 task（一律派 task-decomposer） | **改條件派工**：預估 ≤2 tasks／≤8 items 時主 flow 直建 task 檔（比照 Tier 1）；超過才派 `task-decomposer` |

**HITL gate 保留但改掛點**：原本掛在「usage 報告確認」，改掛在 **Spec 的開放問題裁示 ＋ task 計畫確認**（合為一次）。`hitl_confirmed_at` 與 `hitl_rulings` 欄位語義不變——裁示條數是唯一量測到價值的信號，必須繼續記。

### 3.2 phase 狀態機收斂

```
現行：init → risk_done → usage_confirmed → decomposed → completed
變更：init → decomposed → completed
```

`AGENT_MIN_PHASE` 對應改為：`usage-analyzer`／`impact-analyzer`／`task-decomposer` 皆為 `init`（具名問題隨時可觸發、分拆隨時可做），`code-writer` 維持 `decomposed`。

**向後相容（硬性）**：既有 55 個 run 的 manifest 內含 `risk_done`／`usage_confirmed` 值。`manifest_phase()` 讀到舊值時必須映射到新序列（`risk_done`／`usage_confirmed` → 視同 `init`），**不可** 因 `PHASES.index()` 找不到值而拋例外或誤判——那會讓所有舊 run 無法 resume。

`task-decomposer` 原有的「`usage_report_path` 為空即擋／為 `"skipped"` 即擋」兩條判定隨前置 2 的預設地位一起移除。

### 3.3 循環：審查與測試改 per-task

| 現行 | 變更後 |
|---|---|
| step 3 審查以 **sub_task（item）** 為單位 | 以 **task** 為單位：同 task 的全部 item 完成後一次審查，輸入集為各 item DoD／契約表的聯集。`eval_state.sub_tasks` 同步改為「一個 task 一筆」（結構與消費端清單見 §5 Q2） |
| step 5 本地測試每 item 一次相關測試 | 每 **task** 一次相關測試 |
| step 6 ⓪ 另跑一次全套測試 | **全套測試整個 run 只跑一次**，即 step 6 ⓪；step 5 的 per-task 相關測試不重跑全套 |

**不可弱化**：gate 條件仍是「無新增穩定失敗」（`test_baseline.py check` 判定）；真新失敗仍立即回報使用者裁決（人是計數器，無自修額度）；「既有測試只增不改」不變。

### 3.4 記帳收斂（D1）

移除下列機制及其全部投放路徑（skill 條文、agent 定義、hook、測試）：

| 機制 | 現行位置 | 處置 |
|---|---|---|
| 每輪審查落檔 | eval-flow SKILL.md「審查報告 write-ahead」 | 刪除。審查結論改只記入 `eval_state` 的 `review_reds`／`checked_by` 與收尾回報 |
| 批前 `--stat` 快照 | eval-flow SKILL.md step 2／`task-verifier.md` 第 6 項 | 刪除。審查改 per-task 後，staging 以 task 為界，跨批污染的成因消失 |
| `mine_log.json` 指紋稽核 | eval-flow SKILL.md step 1 交付稽核②／`code-writer.md` | 刪除。writer 的 mine 模式測試自驗本身保留，只停掉落檔與稽核 |
| `events.jsonl` 細粒度事件 | `eval_state.py` 各子命令自動附掛 | **保留不動**（Q7 修正 D1）。只有 Tier 1 的主 flow 手動 `event` 呼叫收斂為 5 節點；自動附掛事件零額外成本，且 `stats.py` 的重入指標依賴它 |
| `token_usage.py --write` | eval-flow SKILL.md step 6 ② | **保留不動** |

### 3.5 不在本次範圍（明確排除，不得順手做）

- 不動 commit gate 的定位邏輯（`Run-Id` trailer ∪ staged ∪ in_progress 安全網，2026-09-22 前一個 run 才剛改完）
- 不動 Router 分級表本身（理由碼五碼、tier 進入條件）
- 不動 Tier 0／Tier B／hotfix／parallel-run 的路徑
- 不刪除既有的 `usage/`、`impact/`、`risk/` 目錄與其中 15 份歷史報告（冷溯源，永不清除）
- 不動 `retro/RETRO.md` 的條目內容

**明確在範圍內（前置 2 新發現，補列）**：`skills/eval-flow-resume/SKILL.md` 受 phase 值域收斂、審查落檔刪除、`sub_tasks` 結構變更三者直接波及，改法見 §5 Q4 與 Q6，必須同批改完。

## §4 驗收條件（DoD 總表）

1. `python3 -m unittest discover -s tests` 全綠，且 `test_baseline.py check --strike-key full_suite` 無新增穩定失敗
2. 舊 manifest 相容性有測試坐實：`phase` 為 `risk_done`／`usage_confirmed` 的 manifest 仍可通過 `check_task_gate` 與 `manifest_phase()`，不拋例外
3. `tests/test_docs_consistency.py` 全綠（skill／hook 引用不得斷）
4. 被刪除的機制在全 repo 無殘留投放路徑：`grep -rn "mine_log\|批前快照\|review-st"` 於 `skills/`、`.claude/agents/`、`.claude/hooks/` 僅剩刻意保留的歷史說明（若有，須在該處註明為歷史）
5. `stats.py` 不因欄位消失而崩潰；其消費的 `events.jsonl` 5 節點與 `token_usage` 照常統計
6. `python3 .claude/hooks/doctor.py` 通過（部署健檢）
7. 單一枚舉點不破：收尾 `git add` 的處置仍只在 eval-flow SKILL.md step 6 子項②（R-007）

## §5 開放問題與裁示（HITL gate 已通過，2026-09-22 18:20）

> Q1–Q3 由主 flow 於 Spec 初稿提出；Q4–Q7 由 `usage-analyzer` 於前置 2 新發現。
> 標「使用者裁示」者為 HITL gate 的實際裁決；標「主 flow 決定」者為慣例性質、依裁示方向推導，於本節留痕供稽核。

### Q1 — 前置 1 刪除後的安全面檢查（**使用者裁示：接受，不加**）

理由碼不含邊界類的 Tier 2 run 將無任何安全面檢查。裁決為**完全刪除前置 1，不設替代機制**。

依據：5 個 Tier 2 run 跑過前置 1，🔴 觸發 0 次。
**已載明的風險**：這 5 個全是框架改自己，本來就沒有安全面可談；真 domain 專案的樣本數為 0。邊界類理由碼仍會觸發 reviewer 直派全 diff 審，該路徑不變。

### Q2／Q5 — sub_tasks 結構與 per-task 審查的部分失敗（**使用者裁示：改成一個 task 一筆**）

`eval_state.json` 的 `sub_tasks` 由「一個 item 一筆」改為「一個 task 一筆」，item 降為該筆內的 `items` 清單。

```json
{ "id": 1, "name": "<task 名>", "items": [ ... ], "status": "...",
  "review_reds": 0, "verify_passed": true, "local_test_passed": true, ... }
```

連帶必須同步的消費端（本節為該清單的唯一枚舉點）：
- `.claude/hooks/eval_state.py`：`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`
- `.claude/hooks/eval_gates.py`：`validate_state()` 的不變量檢查
- `.claude/hooks/stats.py`：rework 率與 checker 升級率的分母語義，**須同時吃新舊兩種形狀**
- `eval-flow-resume` skill：`in_progress` sub_task 的定位邏輯

**Q5 的連帶裁決**：部分失敗時，失敗 item 補齊後才審整個 task（`items` 全數就緒才進 step 3）。批次派工的「失敗隔離只退該 item」不變。

**已載明的代價**：`stats.py` 的 rework／升級率分母由 item 數變 task 數，新舊 run 的趨勢不可直接比較。收尾回報須註明統計斷點日期為 2026-09-22。

### Q6 — 審查落檔刪除後的中斷恢復（**使用者裁示：一律重跑該輪，輪數讀 review_reds**）

`step` 為 `reviewing`／`fixing` 時中斷 → 不追究上一輪發生什麼，直接重派 `task-verifier`（checker）。輪數判定：`review_reds` 無值＝首輪；有值＝已跑過至少一輪。

**已載明且已接受的缺陷**（`usage-analyzer` 指出，使用者知情裁決）：
1. 中斷發生在「升級 reviewer 輪」時，恢復會誤降回 checker
2. 2 輪修正上限的計數可能歸零，理論上可突破上限

此二者為刪除審查落檔的直接代價，**不另設補償機制**。`eval-flow-resume` skill 須明文記載這兩條，讓接手者知道恢復後的輪數可能低估。

### Q7 — events 粒度（**使用者裁示：保留自動附掛事件，修正 D1**）

D1 的「events.jsonl 只記 5 節點」**僅適用於 Tier 1 的主 flow 手動 `event` 呼叫**。Tier 2 由 `eval_state.py` 各子命令**自動附掛**的事件（`set-step`／`set-test`／`set-review` 等）**照舊保留**。

依據：稅的來源是主 flow 的**額外動作**（審查落檔寫檔、批前快照擷取、mine_log 讀取與稽核），自動附掛的事件行是順道產生、零額外成本。保留後 `stats.py` 的重入次數（重試信號）與步驟級時距照常可用。

### Q3 — `usage/`、`impact/` 目錄慣例（**主 flow 決定**：從 skill 文件移除慣例，保留既有檔）

advisor 改為具名問題觸發後答案直接寫進 Spec，不再產生新報告檔。故從 skill 的目錄慣例中移除這兩項，但既有 10 份歷史報告（冷溯源）保留不刪，符合 §3.5 的排除項。
依據：D2 已裁示「產出：答案寫進 Spec，不產獨立報告檔」，本題為該裁示的直接推論。

### Q4 — `eval-flow-resume` 前置恢復語義（**主 flow 決定**）

- 刪除該 skill 中 `risk_done`／`usage_confirmed` 兩列，以及「依 usage 檔是否存在判斷 HITL 卡點」的判定
- 改依 `task_file`（已建＝前置完成）與 `hitl_confirmed_at`（已記＝HITL 過了）定位前置進度
- `≤2 tasks 且 ≤8 items` 的主 flow 直建門檻為**含界**（inclusive），與 Tier 1 精簡路徑既有措辭一致

依據：Q2／Q6 的裁示已決定 resume 的 sub_task 定位與輪數判定改法，本題為使其前置段落與新 phase 值域一致的推論。

### Q8 — `risk_analysis.blocking` gate 的死碼處置（**使用者裁示：刪掉，連同 `risk_analysis` 欄位**）

前置 1 刪除後其生產者消失，`eval_gates.py` 內「任一 sub_task 的 `risk_analysis.blocking` 為 true 即擋 `code-writer`」永遠不會觸發。裁決為連欄位一併清除：

- `.claude/hooks/eval_gates.py`：`check_task_gate()` 內的 blocking 遍歷
- `.claude/hooks/eval_state.py`：`risk_analysis` 欄位的寫入路徑
- `references/formats.md`：該欄位語義
- `eval-flow` SKILL.md：「把對應風險映射到各 sub_task 的 `risk_analysis`」一句

**既有 19 份 `run/*.eval.json` 歸檔檔內的 `risk_analysis` 內容不動**（冷溯源，永不清除）。讀取端移除後，舊檔多帶此鍵不影響任何判定。

### Q9 — `eval_state` 各欄位的 task 層／item 層歸屬（**主 flow 決定**）

Q2 只定了「一個 task 一筆、item 降為 `items` 清單」，未明定各欄位落哪一層。依 Q2 與 Q5 的裁示直接推導：

**task 層**（審查與測試都改 per-task，故其狀態全歸 task）：
`id`／`name`／`status`／`step`／`files`（該 task 全部 item 的聯集）／`local_test_passed`／`local_test_evidence`／`review_reds`／`checked_by`／`verify_passed`／`verification_commands`

**item 層**（`items` 陣列內，只承載審查輸入所需的靜態資訊）：
`id`／`name`／`dod`／`contract`（契約表 row）／`done`（該 item 是否已交付，供 Q5 的「全數就緒才進 step 3」判定）

依據：Q5 已裁示「失敗 item 補齊後才審整個 task」，代表 item 只需要一個就緒旗標，審查與測試的憑據一律掛 task。`eval_state.py` 的 `set-step`／`set-files`／`set-test`／`set-review`／`set-verify`／`add-verification` 全部以 task id 定址；`find_subtask` 維持只認頂層 id，不需新增 item 層定位入口。

### Q10 — `items` 陣列不存在（**使用者裁示：接受空陣列的替代案——直接刪除，Q5 改由主 flow 紀律保證**）

**成因**：item 4.1 實作後發現，Q9 定義的 item 層（`id`／`name`／`dod`／`contract`／`done`）**沒有任何子命令會寫入**——`add-subtask` 只建空陣列，流程中無填入點。Q5 的「失敗 item 補齊後才審整個 task」因此失去機械強制力，`items` 成為永遠是空的裝飾性欄位。

**裁決**：`items` 與配套的 `get_items()` 讀取入口**整個移除**，不留空陣列。

- item 的 DoD 與契約表 **single source ＝ task 檔**，`eval_state` 不複製一份（兩份必漂移，R-007）
- **Q5 改為主 flow 紀律**：規則寫在 eval-flow SKILL.md 循環 step 3，主 flow 對照 task 檔判斷該 task 的 item 是否全數就緒，**無 hook 強制**
- 依據：本 run 的目的是移除機制，為一條紀律新增「填 item ＋標 done」兩個記帳動作與一條 gate，與「記帳收斂」方向相反

**Q9 因此部分作廢**：其「item 層欄位歸屬」一節不再適用；「task 層欄位」與「`find_subtask` 只認頂層 id」兩項維持有效。

**已載明的代價**：Q5 漏判不會被任何 gate 攔截——某 item 帶失敗交付時若主 flow 誤判為就緒，checker 會拿到不完整的交付。此為換取零額外記帳的已知取捨。

**連帶影響**：Q2 的「`sub_tasks` 改構」在 code 層幾乎沒有改動——舊 flat 形狀的欄位位置與新 task 層完全重合（舊模型「一筆＝一個 item」與新模型「一筆＝一個 task」的欄位都在同一層），故無欄位搬遷。真正的變更是**語義**（一筆代表什麼）與其唯一的機械後果：`stats.py` 的分母由 item 數變 task 數（見 Task 5 的新舊雙吃）。
