> 本檔由 skills/eval-flow/SKILL.md 的「Tier 2 完整路徑」節按需載入，不單獨作為 skill 入口。Tier 2 的四個前置步驟住本檔；進場檢查、循環步驟 1–7、派工機制、憑據紀律與各 gate 住 `SKILL.md`。

# Tier 2 前置（四步，依序執行；步驟清單見 SKILL.md「路徑選擇」表）

## 前置 0：初始化（進入點，必須是第一個動作）

- **先完成 `SKILL.md`「共用：進場檢查」**（全 tier 共用的第一個動作，不在此重列——R-007）
- 接收本次要實作的 **Spec**（來源：Stage A intent→spec 的產出，或使用者手動指定的路徑）
- 決定 `run_id`：`YYYY-MM-DD-<spec-slug>`（例如 `2026-07-06-partial-settlement`），作為本次 run 貫穿各檔的關聯鍵
- **建立 run manifest** `run/<run_id>.json`（**冷溯源檔：留在工作目錄、永不清除；不進版控**，見 step 6 子項②），填入：
  - `run_id`、`created_at`
  - `spec_path`：指向這份 Spec 的實際路徑（進入點在此把 Spec **記錄下來**）
  - `usage_report_path`、`task_file`：先設 `null`
  - `phase`：`"init"`
  - `status`：`"in_progress"`
- **建立 `eval_state.json`**（**熱 scratchpad，commit 後清除**），填入 `run_id`（指回 manifest）、空的 `sub_tasks`
- **Gate（硬性）**：manifest 的 `spec_path` 未寫入前，**不可進入前置 1（分拆 task）**。沒有被記錄的 Spec，等於整條 pipeline 沒有輸入來源
- 各後續步驟一律用 `eval_state.json.run_id` 定位 `run/<run_id>.json`，從 manifest 讀 `spec_path` / `usage_report_path`，**不重組日期 / 檔名**

## 具名問題觸發：usage-analyzer／impact-analyzer（選配，非預設步驟）

`usage-analyzer` 與 `impact-analyzer` 不是 Tier 2 的預設前置步驟，由**具名問題觸發**：

- **觸發條件**：主 flow 寫得出要回答的**具名問題**（「這個模組的既有呼叫端有哪些？」→ 派 `impact-analyzer`；「這功能有哪些角色會用？」→ 派 `usage-analyzer`）。只點名 agent 而不附問題原文＝不合格（與 Tier 1 精簡路徑的 advisor 規則相同）；派工方式依「派工機制」節
- **產出**：答案**寫進 Spec**，不產獨立報告檔（不產 `usage/<run_id>.md`／`impact/<run_id>.md`，不回寫 `usage_report_path`／`impact_report_path`，不改 `phase`）——此二欄維持 `null` 屬正常，既有歷史報告（冷溯源）保留不刪
- **呼叫時序**：hook `AGENT_MIN_PHASE` 對兩者皆放行於 `phase: "init"`（隨時可觸發，不受分拆進度限制）
- 兩者可在循環執行中因新的具名問題再次觸發，不限於前置階段——每次觸發都須附問題原文

**Tier 2 沒有前置風險分析步驟，也不設替代機制**：邊界類理由碼（信任邊界／公開介面）的實作安全面由循環 step 3 的「邊界直派 code-reviewer 全 diff 審」承擔；非邊界類 Tier 2 run 無任何前置安全面檢查（使用者已知情接受此風險）。

## 前置 1：分拆 task（條件派工，必須在第一次呼叫 code-writer 之前完成）

- **條件派工門檻**：主 flow 估規模——**預估 ≤2 tasks 且 ≤8 items（含界）→ 主 flow 直建 task 檔**（比照 Tier 1 精簡路徑第 2 點：上限、四要素、DoD 措辭規則一併適用）；超過 → 依「派工機制」節派工 **`task-decomposer` subagent**。它讀 Spec（含已寫入的具名問題答案），拆成 task 與 item、寫入 `task/YYYY-MM-DD.md`、回寫 `manifest.task_file`、並執行交付前自檢。拆分粒度、上限、四要素等規則住在它的定義與 `task-decomposition` skill
- task-decomposer 交付前自檢通過後（或主 flow 直建完成後），將每個 task 展開為 `eval_state.json` 的 `sub_tasks`（**一個 task 一筆**；item 不入 `eval_state`，其 DoD 與契約表只住 task 檔），並將 manifest 的 `phase` 更新為 `"decomposed"`（hook 憑此放行 code-writer）

## HITL gate：Spec 開放問題裁示＋task 計畫確認（合為一次）

- 人閘門掛在**分拆完成後**：主 flow 輕量提報 Spec 的開放問題（若有）＋task 計畫（N tasks／M items），使用者逐條裁示
- **確認留痕**：確認當下主 flow 把「時間＋確認範圍一句話」寫入 manifest 的 `hitl_confirmed_at`（留痕，接手者可驗證），並把**裁示條數**寫入 `hitl_rulings`（int，選填；無裁示填 0）——人閘門的價值信號是裁示數不是打回率，消費端見 stats.py
- 確認後才進入 `SKILL.md`「循環」節的步驟 1–7

