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
- **flow 層級 gate**：報告需經**使用者確認**；未確認前不進入前置 3（usage-analyzer 在確認後才回寫 `manifest.usage_report_path`，並將 `phase` 更新為 `"usage_confirmed"`）。確認當下主 flow 把「時間＋確認範圍一句話」寫入 manifest 的 `hitl_confirmed_at`（留痕，接手者可驗證）。

### 前置 3：分拆 task（必須在第一次呼叫 code-writer 之前完成）

- 呼叫 **`task-decomposer` subagent**。它讀 usage 報告與 Spec、拆成 task 與 item、寫入 `task/YYYY-MM-DD.md`、回寫 `manifest.task_file`、並執行交付前自檢。拆分粒度、上限、五要素等規則住在它的定義與 `task-decomposition` skill。
- **flow 層級 gate**：`manifest.usage_report_path` 為 `null` 不可進入本步（task-decomposer 會自我中止）。
- task-decomposer 交付前自檢通過後，將每個 task 展開為 `eval_state.json` 的 `sub_tasks`，並將 manifest 的 `phase` 更新為 `"decomposed"`（hook 憑此放行 code-writer / eval-scorer），才進入下方循環。

## 循環（每輪結果寫入 `eval_state.json`）

> **循環中的升級逃生門（Tier 2 也適用）**：循環執行中若冒出 🔴 重大風險、或發現需求歧義（DoD 講不清、Spec 有洞）→ 中止循環，回前置 1 修改 Spec 並重新風險分析；若影響使用情境或拆分，一併重跑前置 2／3。

1. 呼叫 `code-writer` subagent 產出程式碼
   - **retro 前置（硬性步驟）**：呼叫前，主 flow 從 `retro/RETRO.md` 挑出與本 item 相關的條目（同模組／同類操作／同類風險面），**原文貼進 writer prompt 的硬性約束區**——不是叫 writer「自己去讀 retro」。實測：writer 讀了 retro、檔頭還引用教訓，仍寫出一模一樣的問題模式；教訓只有以明文約束前置進 prompt 才有效。無相關條目時在 prompt 註明「retro 無相關條目」（留痕，防跳步）
2. 將變更檔案 `git add` 進 staging area（確保 code-reviewer / eval-scorer 可透過 `git diff --cached` 讀取）
3. 呼叫 `code-reviewer` subagent 審查，解析 🔴 重大問題
   - 如果有 🔴：根據建議修正（或呼叫 `code-writer`），重新 `git add` 後再次呼叫 `code-reviewer` 驗證
4. 🔴 清零後，呼叫 `task-verifier` subagent 確認功能完整
   - 比對 task.md vs 實際 diff（子任務完成、DoD 達成、無 scope 偏移）
   - 如有遺漏，修正後回步驟 3
5. **本地測試驗證（硬性 gate，對應 CLAUDE.md「部署規則」）**：依 **test-strategy** skill 執行。gate 條件＝**無新增穩定失敗**（以 `.claude/hooks/test_baseline.py check` 的判定為準；baseline 於第一次 step 5 前建立，flaky 由 script 自動過濾）
   - **Tier 2：新行為必須有自動化測試**（單元測試隨各實作 item 的 DoD、整合測試 item 由前置 3 分拆時建立，見 task-decomposition skill）；**Tier 1**：自動化測試或實際運行功能驗證皆可
   - 通過 → `local_test_passed: true`、`local_test_evidence` 填 script 輸出摘要（hook 於 commit 時檢查兩欄皆已填）
   - 真新失敗 → 依 skill 的失敗分類決策樹處置（測試過時須記依據；無依據改弱測試視同 🔴）；同一 sub_task 累計 2 次真失敗 → 停止自行修復，回報使用者
   - 未通過本步不可進入評分與 commit。細則（相關測試選擇、零測試專案、豁免窗口）住在 test-strategy skill，不在此重述
6. **評分（條件式——code-reviewer 零 🔴 時跳過，比照 step 8 跳過 retro 的規則）**：
   - **本 sub_task 的 code-reviewer 首輪即零 🔴（無 fixing 迭代）→ 跳過 `eval-scorer`**。實測：reviewer 零 🔴 時 score 幾乎必然過門檻，那個數字不改變任何決定、不觸發任何重跑；per-subtask 打分只是把同一個 round 複製到各 sub_task，零信號。直接把本 sub_task 設 `passed`（`rounds` 留空、不 append round——hook 的 `check_rounds_invariant` 只遍歷既有 rounds，空陣列照過），視同通過 threshold，進步驟 7 收尾。`local_test_passed`／`local_test_evidence` 仍須照 step 5 填妥（跳的是評分，不是測試）
   - **code-reviewer 曾有 🔴（修正後）→ 才呼叫 `eval-scorer`**：這時分數才有迭代意義（比較修正前後、判斷品質是否回穩、決定要不要再回 writer 一輪）。呼叫 `eval-scorer` 獨立打分（讀取 `git diff --cached`），結果 append 進 `eval_state.json`，走步驟 7 的 threshold 判斷
   - **多 sub_task 且有評分時**：staging area 會累積先前 sub_task 的變更，須在 prompt 中限定 code-reviewer / eval-scorer 只評本 sub_task 涉及的檔案（`git diff --cached -- <本 sub_task 的檔案路徑>`，清單以 `eval_state.json` 該 sub_task 的 `files` 欄為準），避免評分範圍互相污染
7. 判斷分數：
   - **step 6 跳過評分者** → sub_task 已設 `passed`，比照下方 score >= threshold 進收尾順序
   - **score >= threshold** → 收尾順序（**hook 強制**，見「Gate 的硬性執行」）：⓪先跑**全套測試檢查**（`test_baseline.py check --cmd "<全套指令>" --strike-key full_suite`，見 test-strategy skill）——出現新失敗代表相關測試沒抓到的跨 sub_task 破壞，依 skill 的「重開路徑」把肇事 sub_task 改回 in_progress 從步驟 3 重走，**不可收尾** ①將 `eval_state.json` 歸檔為 `run/<run_id>.eval.json`（保留各輪分數與扣分原因的永久紀錄），manifest 填 `status: "completed"`、`phase: "completed"`，**清除 `eval_state.json`** ②把 manifest `run/<run_id>.json`、eval 歸檔檔、usage 報告、task 檔一併 `git add` ③git commit，message 末尾附 `Run-Id: <run_id>` trailer（Spec↔usage↔task↔commit 的溯源由 `git log --grep "Run-Id: <run_id>"` 反查），結束
   - **score < threshold 且 rounds < 2** → 根據評分報告生成改進 brief，回步驟 1
   - **score < threshold 且 rounds == 2** → 讀取 `eval_state.json` 生成完整報告，回報使用者
8. **有條件** 呼叫 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - score < threshold（需要多輪改進）→ 最終 commit 前呼叫 retro
   - code-reviewer 無 🔴 → **不呼叫 retro**（此路徑評分也已於 step 6 跳過；reviewer 一次過即無回顧價值）

## Model 指派原則

- Model 由各 agent 定義檔的 frontmatter `model` 欄指定（single source of truth），本文件不重複列表
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 風險分析是 skill、由主 flow 執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer / task-verifier / eval-scorer** 需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached`**（Bash 工具），不要用 Read 逐檔讀取完整檔案。`git diff` 只回傳變更部分，token 消耗遠低於讀整檔。
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **auto-mode 開啟時**：這 3 個 agent 可以放背景執行（`run_in_background: true`），Bash 會自動批准。
- **非 auto-mode 時**：這 3 個 agent 必須用前景執行，讓使用者能批准 Bash 權限。不可放背景執行（背景 agent 無法彈出權限確認，會導致 Bash 被拒絕）。
- **retro** 等不需要 Bash 的 agent：可隨時放背景執行。
- **usage-analyzer / task-decomposer**（規劃型 agent，不需 Bash）：可背景產出。但兩者產出後都有把關、不可背景直接續跑：
  - `usage-analyzer` 後接**使用者確認 gate**（前置 2，逐條裁示開放問題）才回寫 `usage_report_path`
  - `task-decomposer` 交付前自檢通過後才進循環（自檢基準住在其定義）；Tier 1 另由主 flow 做輕量計畫確認

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
  "task_file": null,
  "status": "in_progress | completed | failed",
  "failed_reason": null
}
```

- `framework_version`：前置 0 從 `.claude/hooks/VERSION` 讀入——事後鑑識「這個 run 是在哪一版流程規則下跑的」（部署健檢用 `python3 .claude/hooks/doctor.py`）
- `hitl_rejections`：HITL gate 被使用者**打回**的累計次數（usage 報告退回重寫、計畫被否決都算）。打回當下 +1。與 `hitl_confirmed_at` 一起餵 `stats.py` 的打回率——趨近 0% 的人閘門是蓋章，候選降級
- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 6）。轉移時機：前置 0 建立 `"init"` → 前置 1 無 🔴 `"risk_done"` → 前置 2 使用者確認 `"usage_confirmed"` → 前置 3 審查通過 `"decomposed"` → step 7 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`。舊 manifest 無此欄時 hook 以 `task_file` / `usage_report_path` 推導（向後相容）
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）
- `test_command`：本專案的**全套測試指令**（test-strategy script 省略 `--cmd` 時的預設來源，single source of truth——保證 baseline 與 check 範圍一致）。前置 0 可先 `null`，**第一次 step 5 前必須寫入**；同專案的後續 run 沿用前一個 manifest 的值；Tier B 於 DoD 驗證時寫入
- `hitl_confirmed_at`：HITL gate 的留痕——使用者確認當下寫入「時間 ＋ 確認範圍一句話」（例：`"2026-07-15 14:30 — 確認 usage 報告 v1（3 情境、2 開放問題已裁示）"`；Tier 1 記輕量計畫確認：`"… — 確認 1 task／3 items 計畫"`）。resume／換手時，接手者憑此驗證確認 gate 真的過過，不只信 `phase` 欄位。Tier B 記選型確認
- `usage_report_path`：Tier 2 前置 2 使用者確認後寫入（`null` → 不可分拆 task）；Tier 1 固定為 `"skipped"`
- `task_file`：分拆／建 task 後寫入
- `status`：step 7 收尾時（commit 前）填 `"completed"`。manifest↔commit 的對應不記 `commit_sha`，改由 commit message 的 `Run-Id: <run_id>` trailer 反查（`git log --grep`）
- `failed_reason`：`status` 設為 `"failed"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼），讓接手者不用翻對話記錄
- `debt`：僅 hotfix 通道使用（見「Hotfix 通道」），記錄欠下的流程債，如 `["risk", "test", "retro"]`；還清一項移除一項，清空後才可啟動新 run（hook 強制）

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
      "local_test_evidence": null,
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
          "review_reds": 0,
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
  ]
}
```

## eval_state.json 操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .claude/hooks/eval_state.py`（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`append-round`／`list-files`／`archive`）。實測單一 run 手動 Edit 30+ 次是高錯誤面；helper 在寫入前驗證不變量（append-round 驗扣分總和、archive 驗全數 passed），錯誤在落盤前就擋下
- **前置 0（初始化）**：建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id`、`threshold`、空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **使用情境分析完成後 / 分拆 task 完成後**：`usage_report_path` 與 `task_file` 分別由 `usage-analyzer`、`task-decomposer` 於各自步驟回寫（時機與條件見 agent 定義）。前者為 `null` 時不可進入分拆 task
- **風險分析完成後**：將 6 大面向結果填入對應 sub_task 的 `risk_analysis`，若有 🔴 設 `blocking: true`，必須修正 Spec 後重新分析
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`（`writing`→`reviewing`→`fixing`（有 🔴 時）→`verifying`→`testing`→`scoring`→`done`），步驟完成後再更新為下一步。code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **本地測試通過後（step 5）**：將該 sub_task 的 `local_test_passed` 設為 `true`、`local_test_evidence` 填入驗證證據（指令＋結果摘要；Tier 2 若更新過既有測試，一併註明 Spec／task 依據）。預設 `false`／`null`；hook 於 commit 時檢查歸檔檔中所有 sub_task 兩欄皆已填
- **每輪評分後**：將 `eval-scorer` 的結果 append 到對應 sub_task 的 `rounds` 陣列，並在該 round 記 `review_reds`（該輪 code-reviewer 的 🔴 數，修正前的原始數）——這是 `stats.py` 審計「eval-scorer 有沒有獨立貢獻」（reviewer 零 🔴 但 score 低於門檻）的資料來源，缺了審計就是 n/a
- **quality_score < 10（即使通過 threshold）**：必須在該 round 的 `deduction_reasons` 陣列逐條列出扣分原因
  - 每筆需含 `points_lost`（扣分）、`dimension`（哪個維度扣的）、`reason`（具體理由）、`evidence`（檔案行號或證據）
  - 所有 `points_lost` 加總必須等於 `10 - quality_score`（例：8 分 → 扣分總和 = 2）
  - score = 10 時 `deduction_reasons` 為空陣列 `[]`
- **score < threshold**：在該 round 的 `brief_sent_to_writer` 填入改進摘要
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **評分跳過路徑（code-reviewer 零 🔴）**：不呼叫 `eval-scorer`、不 append round，`rounds` 留空即設 `status: "passed"`（測試欄位仍須填）。`stats.py` 對空 `rounds` 的 sub_task 視同「reviewer 一次過、無評分」，非資料缺漏——這是刻意省掉的零信號打分，不是漏記
- **sub_task 2 輪未過**：`status` 設為 `"failed"`，`warning` 設為 `true`
- **全部完成且通過**：**先歸檔為 `run/<run_id>.eval.json`**（保留評分歷史與扣分原因）、清除 `eval_state.json`、manifest `status` 設為 `"completed"`，**再** commit（歸檔檔與 manifest 同批進 git；順序由 hook 強制——`eval_state.json` 尚存在時 commit 會被擋）
- **有任一 failed**：manifest 的 `status` 設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）。此時 hook 會擋下 Claude 端的任何 `git commit`（`eval_state.json` 尚存在），屬預期行為；使用者要部分 commit 可在自己的終端執行（hook 只攔 Claude 的 Bash 工具）

## Gate 的硬性執行（hook）

以下 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，設定於 `.claude/settings.json`，matcher `Bash|Task|Agent`）強制攔截，不再只靠文字約束。攔截點有二：Claude 執行 `git commit` 時（gate 1–5），與呼叫流程管制的 subagent 時（gate 6）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔；失敗收尾時也會擋，屬預期）
2. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `"completed"` → 擋
3. **測試 gate**：staged manifest 對應的 `run/<run_id>.eval.json` 未同批 staged、或其中任一 sub_task 非 `passed`／`local_test_passed` 非 `true` → 擋
4. **假測試 lint gate**：staged 有 manifest（flow 收尾 commit）時，staged 的 Python 測試檔跑 `test_lint.py`，檢出 if-guard 藏斷言／無斷言／恆真斷言 → 擋（誤報以行尾 `# testlint: allow` 豁免並留痕，見 test-strategy skill）
5. **不變量驗證**：每輪 `deduction_reasons` 的 `points_lost` 加總 ≠ `10 - quality_score`、或歸檔檔 `run_id` 與 manifest 不一致 → 擋
6. **phase 狀態機（subagent 呼叫攔截）**：依 `eval_state.json.run_id` 定位 manifest，檢查 `phase` 是否達到該 agent 的最低要求，未達 → 擋呼叫：
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
3. **輕量 HITL**：寫 code 前，把「1 task／N items」的計畫回報使用者確認一次（防 tier 誤判就悶頭寫）。確認後將 manifest 的 `phase` 設為 `"decomposed"`（hook 憑此放行 code-writer）、`hitl_confirmed_at` 記「時間＋確認範圍一句話」，才進循環
4. **共用循環**：進入上方循環的步驟 1–8（code-writer → review → verify → 本地測試 → score → commit）。收尾比照 step 7：先歸檔並清除 `eval_state.json`、manifest 標 `completed`，再一併 `git add` manifest／task 檔並 commit（message 附 `Run-Id: <run_id>` trailer）
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

## 適用範圍

用於「Router 已判定 Tier 1 或 Tier 2 的需求，要照流程實作」的場景。不適用：
- **Tier 0 微調**——直接改，不建任何檔（分級表見 CLAUDE.md）
- 純問答、分析、不落 code 的討論
