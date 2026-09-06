> 本檔由 skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

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
  "impact_report_path": null,
  "task_file": null,
  "status": "in_progress | completed | failed | aborted",
  "failed_reason": null,
  "local_test_passed": null,
  "local_test_evidence": null,
  "verification_commands": [],
  "review_reds": null,
  "verify_passed": null
}
```

- `framework_version`：前置 0 從 `.claude/hooks/VERSION` 讀入——事後鑑識「這個 run 是在哪一版流程規則下跑的」（部署健檢用 `python3 .claude/hooks/doctor.py`）
- `hitl_rejections`：HITL gate 被使用者**打回**的累計次數（usage 報告退回重寫、計畫被否決都算）。打回當下 +1。與 `hitl_confirmed_at` 一起餵 `stats.py` 的打回率——趨近 0% 的人閘門是蓋章，候選降級
- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 7）。轉移時機：前置 0 建立 `"init"` → 前置 1 無 🔴 `"risk_done"` → 前置 2 使用者確認 `"usage_confirmed"` → 前置 3 審查通過 `"decomposed"` → step 6 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`。舊 manifest 無此欄時 hook 以 `task_file` / `usage_report_path` 推導（向後相容）
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）
- `test_command`：本專案的**全套測試指令**（test-strategy script 省略 `--cmd` 時的預設來源，single source of truth——保證 baseline 與 check 範圍一致）。前置 0 可先 `null`，**第一次 step 5 前必須寫入**；同專案的後續 run 沿用前一個 manifest 的值；Tier B 於 DoD 驗證時寫入
- `hitl_confirmed_at`：HITL gate 的留痕——使用者確認當下寫入「時間 ＋ 確認範圍一句話」（例：`"2026-07-15 14:30 — 確認 usage 報告 v1（3 情境、2 開放問題已裁示）"`；Tier 1 記輕量計畫確認：`"… — 確認 1 task／3 items 計畫"`）。resume／換手時，接手者憑此驗證確認 gate 真的過過，不只信 `phase` 欄位。Tier B 記選型確認
- `estimated_active_minutes`／`actual_active_minutes`：**選填**。Router 判級時的預估主動工時與收尾補記的實際值（估實分記，agentflow 慣例；消費端為判級校準，缺欄＝無記錄）
- `dirty_tree_ruling`：**選填**。前置 0 進場檢查（見 eval-flow SKILL.md）發現 dirty tree 時，使用者對孤兒變更歸屬的裁決一句（納入本 run／擱置不動）；乾淨樹免記（欄位缺席＝進場乾淨或舊 run 無此制）
- `scout_report_path`：**已廢止**（前置 1.5 scout 已移除，蒐證職責併回 usage-analyzer／impact-analyzer 自掃）。舊 manifest 仍有此欄者不需回填移除——hook 對此欄無任何依賴，留著不影響任何 gate
- `usage_report_path`：Tier 2 前置 2 使用者確認後寫入（`null` → 不可分拆 task）；Tier 1 固定為 `"skipped"`
- `impact_report_path`：Tier 2 前置 2.5 impact-analyzer 產出後寫入路徑（或 `"skipped: <理由>"`）；Tier 1 固定為 `"skipped"`
- `task_file`：分拆／建 task 後寫入
- `status`：step 6 收尾時（commit 前）填 `"completed"`。`"aborted"`＝使用者或主 flow **決定不做了**（與 `"failed"`＝流程內判定失敗區分開）；標 `aborted` 時 `failed_reason` 必填（1d 窄例外 gate 為此的機械強制點，見「Gate 的硬性執行」）。manifest↔commit 的對應不記 `commit_sha`，改由 commit message 的 `Run-Id: <run_id>` trailer 反查（`git log --grep`）
- `failed_reason`：`status` 設為 `"failed"` 或 `"aborted"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼；`aborted` 則寫放棄理由），讓接手者不用翻對話記錄
- **`aborted`／`failed` 的 manifest 永不清除**：與本節開頭「冷溯源檔……永不清除」同一條規則，不因狀態放棄／失敗而被刪除或清空——防刪除 gate（見「Gate 的硬性執行」）機械強制此點
- **已知限制**：上述防線只攔 `git` 的刪除與 commit 面；Claude 用 Write／Edit 工具直接覆寫 manifest 內容（含把 `status`／`failed_reason` 改寫或清空）的路徑不在 hook matcher（`Bash|Task|Agent`）內，本版不攔（記入風險報告，不修）
- `local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`：**Tier 1 專用憑據欄（豁免歸檔檔）**——Tier 1 不建 `eval_state.json`，這四欄直接寫在 manifest、commit gate 憑此四欄驗放行（語義與 `eval_state.json` 各 sub_task 同欄一致）。Tier 2 仍走歸檔檔路徑，此四欄在 Tier 2 manifest 無意義（可不填）
- `verification_commands`：**Tier 1 記在 manifest**（同上，因 Tier 1 不建 `eval_state.json`）。語義與存放形狀見下方 eval_state.json 格式節的同名欄位，此處不重述
- `debt`：僅 hotfix 通道使用（見「Hotfix 通道」），記錄欠下的流程債，如 `["risk", "test", "retro"]`；還清一項移除一項，清空後才可啟動新 run（hook 強制）

## eval_state.json 格式

熱評分 scratchpad。靠 `run_id` 關聯 manifest；commit 後歸檔為 `run/<run_id>.eval.json` 再清除。

> 下方範例是**欄位形狀骨架**，數值為佔位符、非通過所有不變量的自洽樣本（例如 `review_reds: null` 配非空 `rounds`、全 0 的 `dimensions` 在真實歸檔檔中都會被 hook 擋）；合法組合見「操作規則」與「Gate 的硬性執行」。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "sub_tasks": [
    {
      "id": 1,
      "name": "子 task 名稱",
      "status": "passed | failed | in_progress",
      "step": "writing | reviewing | fixing | verifying | testing | done",
      "files": ["src/foo.ts", "src/bar.ts"],
      "warning": false,
      "local_test_passed": false,
      "local_test_evidence": null,
      "verification_commands": [
        {"command": "python3 -m unittest discover -s tests", "exit_code": 0}
      ],
      "review_reds": null,
      "review_dimensions": null,
      "verify_passed": false,
      "risk_analysis": {
        "technical": "🟢 無風險 | 🟡 ... | 🔴 ...",
        "security": "...",
        "data": "...",
        "performance": "...",
        "deployment": "...",
        "business_maintenance": "...",
        "blocking": false
      }
    }
  ]
}
```

- `review_dimensions`：維度→問題數的字典（例 `{"Non-functional": 2}`）；null 表示零 🔴 無問題可標。五維詞彙：`Clarity`／`Completeness`／`Testability`／`Non-functional`／`Technical_constraints`。由主 flow 於 set-review 時以 `--dimensions` 寫入，供 stats.py 維度分佈遙測
- `verification_commands`：step 5 實際跑過的驗證指令清單，每筆 `{"command": "<指令原文>", "exit_code": <整數>}`，由 `add-verification` 逐條 append（見操作規則）。**純記錄欄位，不被任何 gate 消費**——與 `local_test_evidence` **並存而非取代**：後者記推理留痕（散文：仲裁結論、sabotage 點、測試過時依據、豁免理由），本欄只記「跑了哪些指令、結果如何」這個機器可彙總的面向，供 `stats.py` 統計每個 run 的獨立驗證條數。**加 gate 消費此欄即為 Tier 2 變更**（會使它從記錄轉為判定行為）

## run/<run_id>.events.jsonl 格式

**冷溯源檔**（與本文件開頭「run manifest」節的分類相同：commit 時隨 manifest 同批 `git add`、永不清除）。每個會寫入狀態的子命令（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`archive`）成功寫入（`save()` 之後）append 一行 JSON：`{"ts": "<ISO8601>", "cmd": "<子命令>", "args": {...}}`；唯讀的 `list-files` 不記。`args` 鍵全記，字串值 >200 字元截斷並標 `…[truncated]`。append 是旁路記錄：寫入失敗（如 `run/` 不可寫）僅 stderr warning，不影響原子命令的 exit code；`eval_state.json` 缺 `run_id` 時同樣只 warning 並略過記錄。**已知限制**：Tier 1 不建 `eval_state.json`，故無此檔（與 `verification_commands` 等 Tier 1 專用欄位同一類覆蓋限制）。消費端見 `stats.py`（依 `ts` 欄位取極值計時距；`set-step` 重入依事件的 sub_task id＋`step` 計數，不依賴檔內物理行序）。

## eval_state.json 操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .claude/hooks/eval_state.py`（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`list-files`／`archive`）。實測單一 run 手動 Edit 30+ 次是高錯誤面；helper 在寫入前驗證不變量（archive 驗全數 passed），錯誤在落盤前就擋下
- **前置 0（初始化）**：建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id` ＋ 空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **使用情境分析完成後 / 分拆 task 完成後**：`usage_report_path` 與 `task_file` 分別由 `usage-analyzer`、`task-decomposer` 於各自步驟回寫（時機與條件見 agent 定義）。前者為 `null` 時不可進入分拆 task
- **風險分析完成後**：將 6 大面向結果填入對應 sub_task 的 `risk_analysis`，若有 🔴 設 `blocking: true`，必須修正 Spec 後重新分析
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`（`writing`→`reviewing`（並發 review＋verify 階段）→`fixing`（有 🔴 時）→`testing`→`done`；`verifying`／`scoring` 為舊版 run 的相容值，新路徑不寫入），步驟完成後再更新為下一步。code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **首輪審查結果出來後（step 3，checker 或升級輪 reviewer）**：執行 `python3 .claude/hooks/eval_state.py set-review <id> <🔴數> [--dimensions '<json>']`——`<🔴數>` 記首輪的 🔴 原始數（修正前，有無 🔴 皆須執行；**checker 輪固定填 0**，B4 憑據契約不動）；`--dimensions` 為升級輪 reviewer 報告末尾的維度統計（維度→問題數，五維詞彙：Clarity／Completeness／Testability／Non-functional／Technical_constraints），有 🔴／🟡 時必填，供 stats.py 維度分佈遙測（checker 輪無此節、免填）——commit gate 必填 `<🔴數>`，缺一擋歸檔
- **checker 通過或升級輪 reviewer 完成度節通過且該輪零 🔴（step 4 放行、真正進 step 5 的輪次）**：執行 `python3 .claude/hooks/eval_state.py set-verify <id>`，將 `verify_passed` 設為 `true`——commit gate 必填，缺一擋歸檔。**語義（2026-09-05 起）**：`verify_passed` 記的是「checker 憑據節通過、或升級輪 reviewer 完成度節通過（DoD 無缺席、scope 無偏移）」；hook gate 判定不變。有 🔴 的輪次**不得** set-verify（該輪修正可能改 code 行為）；與 `set-review` 記首輪原始數不同，`set-verify` 記的是**最終通過輪**
- **本地測試通過後（step 5）**：將該 sub_task 的 `local_test_passed` 設為 `true`、`local_test_evidence` 填入驗證證據（指令＋結果摘要；Tier 2 若更新過既有測試，一併註明 Spec／task 依據）。預設 `false`／`null`；hook 於 commit 時檢查歸檔檔中所有 sub_task 兩欄皆已填
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **同一 sub_task 修正 2 輪後 reviewer 仍有 🔴**：`status` 設為 `"failed"`，`warning` 設為 `true`，回報使用者（詳見循環 step 4 修正迭代上限；checker 輪與升級本身不計入此 2 輪，裁示 #9）
- **全部完成且通過**：**先歸檔為 `run/<run_id>.eval.json`**（保留評分歷史與扣分原因）、清除 `eval_state.json`、manifest `status` 設為 `"completed"`，**再** commit（歸檔檔與 manifest 同批進 git；順序由 hook 強制——`eval_state.json` 尚存在時 commit 會被擋）
- **有任一 failed**：manifest 的 `status` 設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）。此時 hook 會擋下 Claude 端的任何 `git commit`（`eval_state.json` 尚存在），屬預期行為；使用者要部分 commit 可在自己的終端執行（hook 只攔 Claude 的 Bash 工具）

