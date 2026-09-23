> 本檔由 skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Run Manifest 格式（`run/<run_id>.json`）

冷溯源檔。前置 0 建立，各前置步驟回填路徑，**留在工作目錄、永不清除；不進版控**（處置的單一枚舉點住 eval-flow SKILL.md step 6 子項②）。

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "created_at": "2026-07-06 14:30",
  "framework_version": "2026.07.15",
  "tier": 2,
  "tier_rationale": "多角色 + 觸及金流 → 強制 Tier 2",
  "phase": "init | decomposed | completed",
  "spec_path": "spec/2026-07-06-partial-settlement.md",
  "spec_inline": null,
  "test_command": null,
  "hitl_confirmed_at": null,
  "risk_report_path": null,
  "usage_report_path": null,
  "impact_report_path": null,
  "task_file": null,
  "status": "in_progress | ready_to_commit | completed | failed | aborted",
  "failed_reason": null,
  "local_test_passed": null,
  "local_test_evidence": null,
  "verification_commands": [],
  "review_reds": null,
  "verify_passed": null
}
```

- `framework_version`：前置 0 從 `.claude/hooks/VERSION` 讀入——事後鑑識「這個 run 是在哪一版流程規則下跑的」（部署健檢用 `python3 .claude/hooks/doctor.py`）
- `hitl_rejections`：HITL gate 被使用者**打回**的累計次數（usage 報告退回重寫、計畫被否決都算）。打回當下 +1。餵 `stats.py` 的打回率——**歷史指標**（2026-09-06 起降級：人閘門的價值信號是裁示數不是打回率，見 `hitl_rulings`；舊「趨近 0% 即蓋章候選降級」警告已自 stats.py 移除）
- `hitl_rulings`：HITL 確認當下的**裁示條數**（int，選填；無裁示填 0）。Tier 2 的 HITL gate（Spec 開放問題裁示＋task 計畫確認）與 Tier 1 輕量 HITL 同名同義（寫入時機見 eval-flow SKILL.md 對應節）；消費端 `stats.py` 裁示數分佈
- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，值域 2026-09-22 起收斂為 `init` → `decomposed` → `completed`（原 `risk_done`／`usage_confirmed` 兩值隨前置 1 風險分析刪除、usage 前置改具名問題觸發而移除，Q1／D2），hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 7）
  - 轉移時機：前置 0 建立 `"init"` → 前置 1 分拆完成 `"decomposed"` → step 6 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`
  - **舊值相容（硬性，DoD 2）**：既有 run 的 manifest 可能仍是 `"risk_done"`／`"usage_confirmed"`——`manifest_phase()` 在與新值域比對前**必須先**把這兩值映射為 `"init"`，不得因值域收斂而對舊值拋例外（55 個既有 run 的 resume 依賴此映射；不可用 try/except 吞例外兜底，映射須發生在 `PHASES.index()` 之前）
  - 舊 manifest 無此欄時 hook 以 `task_file` 推導（向後相容）；原本可用 `usage_report_path` 非空推導出 `"usage_confirmed"` 的分支已隨值域收斂移除，推導結果一律回 `"init"`
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）。`spec_path` 指向的 `spec/<run_id>.md` **進版控**（與本文件開頭「run manifest」等冷溯源檔不同類；分類的單一枚舉點住 eval-flow SKILL.md step 6 子項②）
- `test_command`：本專案的**全套測試指令**（test-strategy script 省略 `--cmd` 時的預設來源，single source of truth——保證 baseline 與 check 範圍一致）。前置 0 可先 `null`，**第一次 step 5 前必須寫入**；同專案的後續 run 沿用前一個 manifest 的值；Tier B 於 DoD 驗證時寫入
- `hitl_confirmed_at`：HITL gate 的留痕——使用者確認當下寫入「時間 ＋ 確認範圍一句話」（例：`"2026-07-15 14:30 — 確認 usage 報告 v1（3 情境、2 開放問題已裁示）"`；Tier 1 記輕量計畫確認：`"… — 確認 1 task／3 items 計畫"`）
  - resume／換手時，接手者憑此驗證確認 gate 真的過過，不只信 `phase` 欄位。Tier B 記選型確認
- `estimated_active_minutes`／`actual_active_minutes`：**選填**。Router 判級時的預估主動工時與收尾補記的實際值（估實分記，agentflow 慣例；消費端為判級校準，缺欄＝無記錄）
- `subagent_usage`：**選填**。step 6 子項②收尾時由 `python3 .claude/hooks/token_usage.py <run_id> --write` **實測回寫**的 tokens 彙總 `{"prep": int, "loop": int, "main": int}`——三鍵皆為 transcript 四欄（`input_tokens`／`cache_creation_input_tokens`／`cache_read_input_tokens`／`output_tokens`）加總；`prep`＝usage-analyzer／task-decomposer／impact-analyzer 的 subagent 合計、`loop`＝其餘 subagent 合計、`main`＝主 flow 自身。舊制「依 Agent 工具回執自報、`main` 憑印象估」**廢止**（實測 2026-09-14 run：自報 loop 68161，transcript 實測主 flow cache 讀 10.09M——估計法系統性低估流程稅，2026-09-19）。消費端 `stats.py`：prep／loop 缺一或非 int → 整筆計無記錄；`main` 非 int → 只跳過 main、prep/loop 照收
- `token_usage`：**選填**。與 `subagent_usage` 同時由 `token_usage.py --write` 寫入的明細：`{"session_id", "window": [lo, hi]|null, "main": {四欄＋turns}, "subagents": [{"agent_type", "description", 四欄＋turns}]}`；`window` 取自 `events.jsonl` 首尾 `ts`（init 之前的判級／載 skill 用量不在窗內，屬已知低估面）。純記錄，無 gate 消費
- `harness`：Codex run 設為 `"codex"`；Claude run 可省略。`token_usage.py --write` 遇 Codex 時只寫 `token_usage_status: "unknown_codex"`，不把 Claude transcript 當作 Codex 用量
- `session_id`／`config_dir`：**選填**。init 事件（Tier 2 `init --run-id`、Tier 1 `event <run_id> init`）由 `eval_state.py` 自 `CLAUDE_CODE_SESSION_ID`／`CLAUDE_CONFIG_DIR` 環境變數自動寫入，已有值不覆寫（resume 換 session 保留首次）；`token_usage.py` 憑此開 `<config_dir>/projects/<cwd 編碼>/<session_id>.jsonl`。舊 run 缺欄＝該腳本走 fallback 掃描 `~/.claude*/projects/*/` 含 run_id 的 transcript
- `executor_notes`：**選填**。list[str]，每 item 一句 `item <id>: 直寫｜派工 — <理由>`——主 flow 直寫捷徑（eval-flow SKILL.md Tier 1 第 4 點）的執行者選擇留痕；2026-09-21 起取代舊的固定行數硬門檻，判斷依據是「交接是否划算」，本欄供事後審計。純記錄欄位，無 gate 消費
- `dirty_tree_ruling`：**選填**。前置 0 進場檢查（見 eval-flow SKILL.md）發現 dirty tree 時，使用者對孤兒變更歸屬的裁決一句（納入本 run／擱置不動）；乾淨樹免記（欄位缺席＝進場乾淨或舊 run 無此制）
- `scout_report_path`：**已廢止**（前置 1.5 scout 已移除，蒐證職責併回 usage-analyzer／impact-analyzer 自掃）。舊 manifest 仍有此欄者不需回填移除——hook 對此欄無任何依賴，留著不影響任何 gate
- `risk_report_path`：**已隨前置 1（多面向風險分析）刪除而停用**（Q1，2026-09-22，不設替代機制）。不再有任何步驟寫入此欄，新 run 長期維持 `null`；欄位保留於 schema 只為讀舊 manifest（既有 5 份 `risk/*.md` 報告為冷溯源，保留不刪）
- `usage_report_path`：**改具名問題觸發後長期維持 `null` 屬正常**（D2，2026-09-22）——`usage-analyzer` 不再是 Tier 2 預設前置步驟，觸發後答案寫進 Spec、不產獨立報告檔、不回寫此欄；無任何 gate 再依賴此欄非空（`task-decomposer` 原本的擋人判定已移除）
- `impact_report_path`：語義同上——`impact-analyzer` 改具名問題觸發，答案寫進 Spec、不回寫此欄，新 run 長期維持 `null` 屬正常
- `task_file`：分拆／建 task 後寫入
- `status`：step 6 先由 `run_commit.py prepare` 設為 `"ready_to_commit"`；commit 成功後由 `run_commit.py finalize` 設為 `"completed"`，並回填 `commit_sha`。新 run 在 manifest 設 `"evidence_schema": 2`，以 `run_verify.py` 記最後一次全套驗證的快照到 manifest `verification_commands`；提交前 gate 會比對目前程式樹，變動後須重驗
  - `"aborted"`＝使用者或主 flow **決定不做了**（與 `"failed"`＝流程內判定失敗區分開）；標 `aborted` 時 `failed_reason` 必填（1d 窄例外 gate 為此的機械強制點，見「Gate 的硬性執行」）
  - manifest↔commit 由 `Run-Id: <run_id>` trailer 與 `commit_sha` 雙向核對
- `failed_reason`：`status` 設為 `"failed"` 或 `"aborted"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼；`aborted` 則寫放棄理由），讓接手者不用翻對話記錄
- **`aborted`／`failed` 的 manifest 永不清除**：與本節開頭「冷溯源檔……永不清除」同一條規則，不因狀態放棄／失敗而被刪除或清空——防刪除 gate（見「Gate 的硬性執行」）機械強制此點
- **已知限制**：上述防線只攔 `git` 的刪除與 commit 面；Claude 用 Write／Edit 工具直接覆寫 manifest 內容（含把 `status`／`failed_reason` 改寫或清空）的路徑不在 hook matcher（`Bash|Task|Agent`）內，本版不攔（記入風險報告，不修）
- `local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`：**Tier 1 專用憑據欄（豁免歸檔檔）**——Tier 1 不建 `eval_state.json`，這四欄直接寫在 manifest、commit gate 憑此四欄驗放行（語義與 `eval_state.json` 各 sub_task 同欄一致）。Tier 2 仍走歸檔檔路徑，此四欄在 Tier 2 manifest 無意義（可不填）
- `verification_commands`：**Tier 1 記在 manifest**（同上，因 Tier 1 不建 `eval_state.json`）。語義與存放形狀見下方 eval_state.json 格式節的同名欄位，此處不重述
- `debt`：僅 hotfix 通道使用（見「Hotfix 通道」），記錄欠下的流程債，如 `["risk", "test", "retro"]`；還清一項移除一項，清空後才可啟動新 run（hook 強制）

## eval_state.json 格式

熱評分 scratchpad。靠 `run_id` 關聯 manifest；commit 後歸檔為 `run/<run_id>.eval.json` 再清除。

> 下方範例是**欄位形狀骨架**，數值為佔位符、非通過所有不變量的自洽樣本（例如 `review_reds: null` 配非空 `rounds`、全 0 的 `dimensions` 在真實歸檔檔中都會被 hook 擋）；合法組合見「操作規則」與「Gate 的硬性執行」。

**一筆＝一個 task**（2026-09-22 起，Q2 裁決；此前一筆＝一個 item）：審查與測試都改以 task 為單位（§3.3），故狀態與憑據全記在這一層。

- **欄位**：`id`／`name`／`status`／`step`／`files`（該 task 全部 item 的聯集）／`warning`／`local_test_passed`／`local_test_evidence`／`verification_commands`／`review_reds`／`review_dimensions`／`checked_by`／`verify_passed`
- **不存 item 層資料**（Q10 裁決）：item 的 DoD 與契約表**只住 task 檔**，`eval_state` 不複製一份——兩份必漂移（R-007）。`find_subtask` 只認頂層 task id，不設 item 層定位入口
- **Q5 的「全數就緒才進 step 3」無 hook 強制**，由主 flow 對照 task 檔判斷（規則住 eval-flow SKILL.md 循環 step 3）。此為 Q10 的已知代價：換得零額外記帳
- **`risk_analysis` 欄位已移除**（Q8，隨前置 1 風險分析刪除）——不再有任何面向映射或 `blocking` 判定
- **向後相容**：既有 19 份 `run/*.eval.json` 歸檔檔的每一筆代表一個 item（舊語義），且多帶 `risk_analysis` 鍵。欄位位置與新形狀相同，故子命令與 `validate_state` 對其照常可操作；差別只在「一筆代表什麼」，這影響的是 `stats.py` 的分母語義（見該 script 的新舊雙吃）

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
      "checked_by": null,
      "verify_passed": false
    }
  ]
}
```

- `review_dimensions`：維度→問題數的字典（例 `{"Non-functional": 2}`）；null 表示零 🔴 無問題可標。五維詞彙：`Clarity`／`Completeness`／`Testability`／`Non-functional`／`Technical_constraints`。由主 flow 於 set-review 時以 `--dimensions` 寫入，供 stats.py 維度分佈遙測
- `verification_commands`：step 5 實際跑過的驗證指令清單，每筆 `{"command": "<指令原文>", "exit_code": <整數>}`，由 `add-verification` 逐條 append（見操作規則）
  - **純記錄欄位，不被任何 gate 消費**——與 `local_test_evidence` **並存而非取代**：後者記推理留痕（散文：仲裁結論、sabotage 點、測試過時依據、豁免理由），本欄只記「跑了哪些指令、結果如何」這個機器可彙總的面向，供 `stats.py` 統計每個 run 的獨立驗證條數
  - **加 gate 消費此欄即為 Tier 2 變更**（會使它從記錄轉為判定行為）

## run/<run_id>.events.jsonl 格式

**冷溯源檔**（與本文件開頭「run manifest」節的分類相同：留在工作目錄、永不清除；不進版控）。

- 每個會寫入狀態的子命令（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`archive`）成功寫入（`save()` 之後）append 一行 JSON：`{"ts": "<ISO8601>", "cmd": "<子命令>", "args": {...}}`；唯讀的 `list-files` 不記
- `args` 鍵全記（`func` 與子命令 dest `command` 除外），字串值 >200 字元截斷並標 `…[truncated]`
- `verify_cmd`（Tier 1，run_verify.py 寫）與 `add-verification`（Tier 2）事件的 `args.verify_command`＝驗證指令原文（2026-09-21 起；因 `command` 鍵被過濾，舊事件只有 `exit_code`）。消費端 `stats.py` 事件節「全套 N」＝含 `--strike-key full_suite` 的此類事件數，供收尾停止規則（記錄級修正不重跑全套）累積證據
- append 是旁路記錄：寫入失敗（如 `run/` 不可寫）僅 stderr warning，不影響原子命令的 exit code；`eval_state.json` 缺 `run_id` 時同樣只 warning 並略過記錄
- **Tier 1 的寫入路徑**：Tier 1 不建 `eval_state.json`，改以 `event` 子命令（`python3 .claude/hooks/eval_state.py event <run_id> <節點名> [--note <str>]`，不經 load()）於流程節點直寫本檔——呼叫點住 eval-flow SKILL.md「Tier 1 精簡路徑」；事件行形狀同上（`cmd` 為節點名）
- 消費端見 `stats.py`（依 `ts` 欄位取極值計時距；`set-step` 重入依事件的 sub_task id＋`step` 計數，不依賴檔內物理行序）

## run/tier0.jsonl 格式

**冷溯源檔**（單一共用檔、append-only、永不清除；留在工作目錄、不進版控。Tier 0 本身不 commit 的規則不變，見 CLAUDE.md Router）。Tier 0 改完回報時 append 一行：

- 指令：`python3 .claude/hooks/eval_state.py tier0 --summary "<一句>" --files "<逗號分隔清單>" --lines <int：git diff 增＋刪>`
- 行形狀：`{"ts": "<ISO8601 UTC>", "summary": "...", "files": [...], "lines": <int>}`
- **純記錄欄位，不被任何 gate 消費**——加 gate 消費此檔即為判定行為變更（比照 `verification_commands` 同條款）
- 消費端：`stats.py`「Tier 0 留痕」節（筆數／合計行數／最近一筆 ts；壞行寬容跳過）

## eval_state.json 操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .claude/hooks/eval_state.py`（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`list-files`／`archive`）
  - 理由：實測單一 run 手動 Edit 30+ 次是高錯誤面；helper 在寫入前驗證不變量（archive 驗全數 passed），錯誤在落盤前就擋下
- **前置 0（初始化）**：建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id` ＋ 空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **分拆 task 完成後**：`task_file` 由主 flow（直建，≤2 tasks 且 ≤8 items 含界）或 `task-decomposer`（超門檻條件派工）回寫（時機與條件見 eval-flow SKILL.md 前置 1）；`phase` 隨之更新為 `"decomposed"`
- **具名問題觸發 usage-analyzer／impact-analyzer 時**（D2，2026-09-22）：答案寫進 Spec，**不**回寫 `usage_report_path`／`impact_report_path`（兩欄長期維持 `null` 屬正常），無 gate 依賴此二欄
- **風險分析已刪除**（Q1，2026-09-22，不設替代機制）：不再有步驟填寫 sub_task 的 `risk_analysis`，該欄位與其 `blocking` 判定已從本 schema 與 `eval_gates.py` 的擋人邏輯移除
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`，步驟完成後再更新為下一步
  - `step` 值序：`writing`→`reviewing`（並發 review＋verify 階段）→`fixing`（有 🔴 時）→`testing`→`done`；`verifying`／`scoring` 為舊版 run 的相容值，新路徑不寫入
  - code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **首輪審查結果出來後（step 3，checker 或升級輪 reviewer）**：執行 `python3 .claude/hooks/eval_state.py set-review <id> <🔴數> [--dimensions '<json>']`
  - `<🔴數>` 記首輪的 🔴 原始數（修正前，有無 🔴 皆須執行；**checker 輪固定填 0**，B4 憑據契約不動）
  - `--dimensions` 為升級輪 reviewer 報告末尾的維度統計（維度→問題數，五維詞彙：Clarity／Completeness／Testability／Non-functional／Technical_constraints），有 🔴／🟡 時必填，供 stats.py 維度分佈遙測（checker 輪無此節、免填）
  - commit gate 必填 `<🔴數>`，缺一擋歸檔
- **checker 通過或升級輪 reviewer 完成度節通過且該輪零 🔴（step 4 放行、真正進 step 5 的輪次）**：執行 `python3 .claude/hooks/eval_state.py set-verify <id>`，將 `verify_passed` 設為 `true`——commit gate 必填，缺一擋歸檔
  - **語義（2026-09-05 起）**：`verify_passed` 記的是「checker 憑據節通過、或升級輪 reviewer 完成度節通過（DoD 無缺席、scope 無偏移）」；hook gate 判定不變
  - 有 🔴 的輪次**不得** set-verify（該輪修正可能改 code 行為）；與 `set-review` 記首輪原始數不同，`set-verify` 記的是**最終通過輪**
- **本地測試通過後（step 5）**：將該 sub_task 的 `local_test_passed` 設為 `true`、`local_test_evidence` 填入驗證證據（指令＋結果摘要；Tier 2 若更新過既有測試，一併註明 Spec／task 依據）。預設 `false`／`null`；hook 於 commit 時檢查歸檔檔中所有 sub_task 兩欄皆已填
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **同一 sub_task 修正 2 輪後 reviewer 仍有 🔴**：`status` 設為 `"failed"`，`warning` 設為 `true`，回報使用者（詳見循環 step 4 修正迭代上限；checker 輪與升級本身不計入此 2 輪，裁示 #9）
- **全部完成且通過**：先歸檔為 `run/<run_id>.eval.json`、清除 `eval_state.json`；`run_commit.py prepare <run_id>` 設 `ready_to_commit` 後 commit，成功後 `run_commit.py finalize <run_id>` 回填 `completed` 與 SHA。歸檔檔與 manifest 是工作目錄冷溯源檔，不進版控
- **有任一 failed**：manifest 的 `status` 設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）
  - 失敗收尾時工具 hook 會擋下 agent 的 `git commit`（`eval_state.json` 尚存在）；使用者若決定部分 commit，需先依裁決處置現場狀態
