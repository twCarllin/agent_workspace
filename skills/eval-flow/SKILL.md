---
name: eval-flow
description: Eval Flow 的完整執行細節：Tier 2 前置 0–3（初始化、風險分析、使用情境、分拆 task）、循環步驟 1–8（code-writer → review → verify → 本地測試 → score → commit）、Tier 1 精簡路徑、run manifest 與 eval_state.json 格式與操作規則、hook gate 清單。觸發語：Router 判定需求為 Tier 1 或 Tier 2 時（執行前必須載入本 skill）、「跑 Eval Flow」、「照流程實作這個需求」。不適用於：Tier 0 微調（直接改，不建任何檔）、非實作類的問答。
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
- **建立 `eval_state.json`**（**熱評分 scratchpad，commit 後清除**），填入 `run_id`（指回 manifest）、`threshold`、空的 `sub_tasks`
- **Gate（硬性）**：manifest 的 `spec_path` 未寫入前，**不可進入前置 1（風險分析）**。沒有被記錄的 Spec，等於整條 pipeline 沒有輸入來源
- 各後續步驟一律用 `eval_state.json.run_id` 定位 `run/<run_id>.json`，從 manifest 讀 `spec_path` / `usage_report_path`，**不重組日期 / 檔名**

### 前置 1：多面向風險分析（必須在第一次呼叫 code-writer 之前完成）

- 使用 **task-risk-analysis** skill，讀取 manifest `run/<run_id>.json` 的 `spec_path` 指向的 Spec，從 6 大面向（技術、安全、資料、效能、部署、業務維護）逐一思考任務風險
- 每個面向需明確標註等級：🔴 重大 / 🟡 中等 / 🟢 輕微 / 無風險
- 產出「風險分析報告」，內容包含：每個面向的判斷、風險描述、對應對策
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

### 前置 3：分拆 task（必須在第一次呼叫 code-writer 之前完成）

- 呼叫 **`task-decomposer` subagent**。它讀 usage 報告與 Spec、拆成 task 與 item、寫入 `task/YYYY-MM-DD.md`、回寫 `manifest.task_file`、並接 `task-reviewer` 審查。拆分粒度、上限、五要素等規則住在它的定義與 `task-decomposition` skill。
- **flow 層級 gate**：`manifest.usage_report_path` 為 `null` 不可進入本步（task-decomposer 會自我中止）。
- task-decomposer 交付（含 task-reviewer 審查通過）後，將每個 task 展開為 `eval_state.json` 的 `sub_tasks`，並將 manifest 的 `phase` 更新為 `"decomposed"`（hook 憑此放行 code-writer / eval-scorer），才進入下方循環。

## 循環（每輪結果寫入 `eval_state.json`）

> **循環中的升級逃生門（Tier 2 也適用）**：循環執行中若冒出 🔴 重大風險、或發現需求歧義（DoD 講不清、Spec 有洞）→ 中止循環，回前置 1 修改 Spec 並重新風險分析；若影響使用情境或拆分，一併重跑前置 2／3。

1. 呼叫 `code-writer` subagent 產出程式碼
2. 將變更檔案 `git add` 進 staging area（確保 code-reviewer / eval-scorer 可透過 `git diff --cached` 讀取）
3. 呼叫 `code-reviewer` subagent 審查，解析 🔴 重大問題
   - 如果有 🔴：根據建議修正（或呼叫 `code-writer`），重新 `git add` 後再次呼叫 `code-reviewer` 驗證
4. 🔴 清零後，呼叫 `task-verifier` subagent 確認功能完整
   - 比對 task.md vs 實際 diff（子任務完成、DoD 達成、無 scope 偏移）
   - 如有遺漏，修正後回步驟 3
5. **本地測試驗證（硬性 gate，對應 CLAUDE.md「部署規則」）**：執行測試（或無測試框架時，實際運行功能驗證）
   - 通過 → 將該 sub_task 的 `local_test_passed` 設為 `true`（hook 於 commit 時強制檢查此欄位）
   - 失敗 → 修正後回步驟 3；未通過本步不可進入評分與 commit
6. 呼叫 `eval-scorer` subagent 獨立打分（讀取 `git diff --cached`），結果 append 進 `eval_state.json`
   - **多 sub_task 時**：staging area 會累積先前 sub_task 的變更，須在 prompt 中限定 code-reviewer / eval-scorer 只評本 sub_task 涉及的檔案（`git diff --cached -- <本 sub_task 的檔案路徑>`，清單以 `eval_state.json` 該 sub_task 的 `files` 欄為準），避免評分範圍互相污染
7. 判斷分數：
   - **score >= threshold** → 收尾順序（**hook 強制**，見「Gate 的硬性執行」）：①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留各輪分數與扣分原因的永久紀錄），manifest 填 `status: "completed"`、`phase: "completed"`，**清除 `eval_state.json`** ②把 manifest `run/<run_id>.json`、eval 歸檔檔、usage 報告、task 檔一併 `git add` ③git commit，message 末尾附 `Run-Id: <run_id>` trailer（Spec↔usage↔task↔commit 的溯源由 `git log --grep "Run-Id: <run_id>"` 反查），結束
   - **score < threshold 且 rounds < 2** → 根據評分報告生成改進 brief，回步驟 1
   - **score < threshold 且 rounds == 2** → 讀取 `eval_state.json` 生成完整報告，回報使用者
8. **有條件** 呼叫 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - score < threshold（需要多輪改進）→ 最終 commit 前呼叫 retro
   - code-reviewer 無 🔴 且 score 一次通過 → **不呼叫 retro**（無需回顧）

## Model 指派原則

- Model 由各 agent 定義檔的 frontmatter `model` 欄指定（single source of truth），本文件不重複列表
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 風險分析是 skill、由主 flow 執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer / task-verifier / eval-scorer** 需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached`**（Bash 工具），不要用 Read 逐檔讀取完整檔案。`git diff` 只回傳變更部分，token 消耗遠低於讀整檔。
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **auto-mode 開啟時**：這 3 個 agent 可以放背景執行（`run_in_background: true`），Bash 會自動批准。
- **非 auto-mode 時**：這 3 個 agent 必須用前景執行，讓使用者能批准 Bash 權限。不可放背景執行（背景 agent 無法彈出權限確認，會導致 Bash 被拒絕）。
- **retro / task-reviewer** 等不需要 Bash 的 agent：可隨時放背景執行。
- **usage-analyzer / task-decomposer**（規劃型 agent，不需 Bash）：可背景產出。但兩者產出後都有把關、不可背景直接續跑：
  - `usage-analyzer` 後接**使用者確認 gate**（前置 2，逐條裁示開放問題）才回寫 `usage_report_path`
  - `task-decomposer` 後接 **`task-reviewer` 審查**才進循環（審查基準住在其定義／skill）；Tier 1 另由主 flow 做輕量計畫確認

## Run Manifest 格式（`run/<run_id>.json`）

冷溯源檔。前置 0 建立，各前置步驟回填路徑，commit 時隨 code 進 git、**永不清除**。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "created_at": "2026-07-06 14:30",
  "tier": 2,
  "tier_rationale": "多角色 + 觸及金流 → 強制 Tier 2",
  "phase": "init | risk_done | usage_confirmed | decomposed | completed",
  "spec_path": "spec/2026-07-06-partial-settlement.md",
  "spec_inline": null,
  "risk_report_path": null,
  "usage_report_path": null,
  "task_file": null,
  "status": "in_progress | completed | failed",
  "failed_reason": null
}
```

- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 5）。轉移時機：前置 0 建立 `"init"` → 前置 1 無 🔴 `"risk_done"` → 前置 2 使用者確認 `"usage_confirmed"` → 前置 3 審查通過 `"decomposed"` → step 7 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`。舊 manifest 無此欄時 hook 以 `task_file` / `usage_report_path` 推導（向後相容）
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）
- `risk_report_path`：前置 1 產出 `risk/<run_id>.md` 後寫入；Tier 1 固定為 `"skipped"`
- `usage_report_path`：Tier 2 前置 2 使用者確認後寫入（`null` → 不可分拆 task）；Tier 1 固定為 `"skipped"`
- `task_file`：分拆／建 task 後寫入
- `status`：step 7 收尾時（commit 前）填 `"completed"`。manifest↔commit 的對應不記 `commit_sha`，改由 commit message 的 `Run-Id: <run_id>` trailer 反查（`git log --grep`）
- `failed_reason`：`status` 設為 `"failed"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼），讓接手者不用翻對話記錄

## eval_state.json 格式

熱評分 scratchpad。靠 `run_id` 關聯 manifest；commit 後歸檔為 `run/<run_id>.eval.json` 再清除。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "threshold": 6,
  "sub_tasks": [
    {
      "id": 1,
      "name": "子 task 名稱",
      "status": "passed | failed | in_progress",
      "step": "writing | reviewing | fixing | verifying | testing | scoring | done",
      "files": ["src/foo.ts", "src/bar.ts"],
      "warning": false,
      "local_test_passed": false,
      "risk_analysis": {
        "technical": "🟢 無風險 | 🟡 ... | 🔴 ...",
        "security": "...",
        "data": "...",
        "performance": "...",
        "deployment": "...",
        "business_maintenance": "...",
        "blocking": false
      },
      "rounds": [
        {
          "round": 1,
          "quality_score": 0,
          "dimensions": {
            "Clarity": 0,
            "Completeness": 0,
            "Testability": 0,
            "Non-functional": 0,
            "Technical_constraints": 0
          },
          "deduction_reasons": [
            {
              "points_lost": 1,
              "dimension": "Completeness",
              "reason": "缺少 X 邊界條件的處理",
              "evidence": "src/foo.ts:42"
            }
          ],
          "brief_sent_to_writer": "改進摘要（score < threshold 時填寫）"
        }
      ]
    }
  ],
  "status": "in_progress | completed | failed"
}
```

## eval_state.json 操作規則

- **前置 0（初始化）**：建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id`、`threshold`、空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **使用情境分析完成後 / 分拆 task 完成後**：`usage_report_path` 與 `task_file` 分別由 `usage-analyzer`、`task-decomposer` 於各自步驟回寫（時機與條件見 agent 定義）。前者為 `null` 時不可進入分拆 task
- **風險分析完成後**：將 6 大面向結果填入對應 sub_task 的 `risk_analysis`，若有 🔴 設 `blocking: true`，必須修正 Spec 後重新分析
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`（`writing`→`reviewing`→`fixing`（有 🔴 時）→`verifying`→`testing`→`scoring`→`done`），步驟完成後再更新為下一步。code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **本地測試通過後（step 5）**：將該 sub_task 的 `local_test_passed` 設為 `true`（預設 `false`；hook 於 commit 時檢查歸檔檔中所有 sub_task 此欄皆為 `true`）
- **每輪評分後**：將 `eval-scorer` 的結果 append 到對應 sub_task 的 `rounds` 陣列
- **quality_score < 10（即使通過 threshold）**：必須在該 round 的 `deduction_reasons` 陣列逐條列出扣分原因
  - 每筆需含 `points_lost`（扣分）、`dimension`（哪個維度扣的）、`reason`（具體理由）、`evidence`（檔案行號或證據）
  - 所有 `points_lost` 加總必須等於 `10 - quality_score`（例：8 分 → 扣分總和 = 2）
  - score = 10 時 `deduction_reasons` 為空陣列 `[]`
- **score < threshold**：在該 round 的 `brief_sent_to_writer` 填入改進摘要
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **sub_task 2 輪未過**：`status` 設為 `"failed"`，`warning` 設為 `true`
- **全部完成且通過**：`eval_state.json` 頂層 `status` 設為 `"completed"` 並**先歸檔為 `run/<run_id>.eval.json`**（保留評分歷史與扣分原因）、清除 `eval_state.json`、manifest `status` 設為 `"completed"`，**再** commit（歸檔檔與 manifest 同批進 git；順序由 hook 強制——`eval_state.json` 尚存在時 commit 會被擋）
- **有任一 failed**：manifest 與 `eval_state.json` 的 `status` 皆設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）。此時 hook 會擋下 Claude 端的任何 `git commit`（`eval_state.json` 尚存在），屬預期行為；使用者要部分 commit 可在自己的終端執行（hook 只攔 Claude 的 Bash 工具）

## Gate 的硬性執行（hook）

以下 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，設定於 `.claude/settings.json`，matcher `Bash|Task|Agent`）強制攔截，不再只靠文字約束。攔截點有二：Claude 執行 `git commit` 時（gate 1–4），與呼叫流程管制的 subagent 時（gate 5）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔；失敗收尾時也會擋，屬預期）
2. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `"completed"` → 擋
3. **測試 gate**：staged manifest 對應的 `run/<run_id>.eval.json` 未同批 staged、或其中任一 sub_task 非 `passed`／`local_test_passed` 非 `true` → 擋
4. **不變量驗證**：每輪 `deduction_reasons` 的 `points_lost` 加總 ≠ `10 - quality_score`、或歸檔檔 `run_id` 與 manifest 不一致 → 擋
5. **phase 狀態機（subagent 呼叫攔截）**：依 `eval_state.json.run_id` 定位 manifest，檢查 `phase` 是否達到該 agent 的最低要求，未達 → 擋呼叫：
   - `usage-analyzer` 需 `phase >= risk_done`（前置 1 未完不可跑前置 2）
   - `task-decomposer` 需 `phase >= usage_confirmed` 且 `usage_report_path` 非空；為 `"skipped"`（Tier 1）也擋
   - `code-writer` 需 `phase >= decomposed` 且 `task_file` 非空；任一 sub_task `risk_analysis.blocking: true` 也擋
   - `eval-scorer` 需 `phase >= decomposed`，且 in_progress 的 sub_task `local_test_passed` 為 `true`（step 5 未過不可評分）
   - 共通前提：`eval_state.json` 與 manifest 存在、intent gate 通過；缺任一 → 擋（前置 0 未完成）

被擋時 hook 會以 stderr 回報原因，依訊息補齊狀態後重試。流程中亦可隨時自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。hook 只攔 Claude 的 Bash 工具，不影響使用者自己終端的 git 操作。本 skill 對應條文為流程說明，實際防線以 hook 為準。

## 中斷恢復（Resume）

執行中斷（session 掛掉、compact 掉狀態、換 AI 接手）後要續跑時，**依 `eval-flow-resume` skill 的確定性程序恢復**，不靠記憶或猜測：掃 `run/` 找 `status: "in_progress"` 的 manifest → 依 `phase` 定位前置進度 → 已 `decomposed` 則讀 `eval_state.json` 的 in_progress sub_task 及其 `step`／`files` → 用 `git diff --cached -- <files>` 還原工作現場 → 從該步驟繼續。已 `passed` 的 sub_task 不重跑；hook gates 照常生效。

## Tier 1 精簡路徑

明確、單一路徑、不觸及高風險面的小功能。**跳過 Spec 檔與 usage 分析，但仍留溯源、仍守大小上限**。風險由 Router 的排除條件把關（觸及高風險面者根本進不到 Tier 1），故不另跑 6 面向分析。

1. **精簡初始化**：建 manifest `run/<run_id>.json`，填 `tier: 1`、`tier_rationale`、**`spec_inline`**（需求原文一句話，取代 `spec_path`）、`risk_report_path: "skipped"`、`usage_report_path: "skipped"`、`phase: "init"`；建 `eval_state.json`（`run_id` + `threshold` + 空 `sub_tasks`）
   - **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空，皆空不可往下
2. **直接建 task 檔**：免呼叫 `task-decomposer` subagent，但上限不變——**1 個 task、≤5 items（硬）、各 item 目標 ≤300 行（軟）**。item 數超 5、或出現遠超 300 行且拆不進 5 item 內的工作 → 觸發升級逃生門（回 Tier 2）
3. **輕量 HITL**：寫 code 前，把「1 task／N items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。確認後將 manifest 的 `phase` 設為 `"decomposed"`（hook 憑此放行 code-writer），才進循環
4. **共用循環**：進入上方循環的步驟 1–8（code-writer → review → verify → 本地測試 → score → commit）。收尾比照 step 7：先歸檔並清除 `eval_state.json`、manifest 標 `completed`，再一併 `git add` manifest／task 檔並 commit（message 附 `Run-Id: <run_id>` trailer）
   - sub_task 的 `risk_analysis` 可簡記為 `"router 已篩（Tier 1）"`，不需逐面向填

## 適用範圍

用於「Router 已判定 Tier 1 或 Tier 2 的需求，要照流程實作」的場景。不適用：
- **Tier 0 微調**——直接改，不建任何檔（分級表見 CLAUDE.md）
- 純問答、分析、不落 code 的討論
