> 本檔由 .agents/skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## 目錄

- Run Manifest 格式（`run/<run_id>.json`）
- eval_state.json 格式
- run/<run_id>.events.jsonl 格式
- run/tier0.jsonl 格式
- run/<run_id>.dispatch.jsonl 格式
- eval_state.json 操作規則

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

- `framework_version`：前置 0 從 `.agent-flow/scripts/VERSION` 讀入——事後鑑識「這個 run 是在哪一版流程規則下跑的」（部署健檢用 `python3 .agent-flow/scripts/doctor.py`）
- `hitl_rejections`：HITL gate 被使用者**打回**的累計次數（usage 報告退回重寫、計畫被否決都算）。打回當下 +1。餵 `stats.py` 的打回率——**歷史指標**：人閘門的價值信號是裁示數不是打回率（見 `hitl_rulings`）
- `hitl_rulings`：HITL 確認當下的**裁示條數**（int，選填；無裁示填 0）。Tier 2 的 HITL gate（Spec 開放問題裁示＋task 計畫確認）與 Tier 1 輕量 HITL 同名同義（寫入時機見 eval-flow SKILL.md 對應節）；消費端 `stats.py` 裁示數分佈
- `tier` / `tier_rationale`：Router 判定後寫入（供審計；Tier 1 若升級 Tier 2 須更新）
- `phase`：流程狀態機欄位，值域 `init` → `decomposed` → `completed`，hook 憑此攔亂序的 subagent 呼叫（見「Gate 的硬性執行」gate 7）
  - 轉移時機：前置 0 建立 `"init"` → 前置 1 分拆完成 `"decomposed"` → step 6 收尾 `"completed"`。Tier 1 於輕量 HITL 確認後直接設 `"decomposed"`
  - **舊值相容（硬性）**：既有 run 的 manifest 可能仍是 `"risk_done"`／`"usage_confirmed"`——`manifest_phase()` 在與值域比對前**必須先**把這兩值映射為 `"init"`，不得對舊值拋例外（既有 run 的 resume 依賴此映射；不可用 try/except 吞例外兜底，映射須發生在 `PHASES.index()` 之前）
  - 舊 manifest 無此欄時 hook 以 `task_file` 推導（向後相容）；`usage_report_path` 不參與推導
- `spec_path` / `spec_inline`：Tier 2 用 `spec_path`（Spec 檔）；Tier 1 用 `spec_inline`（需求原文一句話）。**兩者至少一個非空**，皆空不可往下（intent gate）。`spec_path` 指向的 `spec/<run_id>.md` **進版控**（與本文件開頭「run manifest」等冷溯源檔不同類；分類的單一枚舉點住 eval-flow SKILL.md step 6 子項②）
- `test_command`：本專案的**全套測試指令**（test-strategy script 省略 `--cmd` 時的預設來源，single source of truth——保證 baseline 與 check 範圍一致）。前置 0 可先 `null`，**第一次 step 5 前必須寫入**；同專案的後續 run 沿用前一個 manifest 的值；Tier B 於 DoD 驗證時寫入
- `hitl_confirmed_at`：HITL gate 的留痕——使用者確認當下寫入「時間 ＋ 確認範圍一句話」（例：`"2026-07-15 14:30 — 確認 usage 報告 v1（3 情境、2 開放問題已裁示）"`；Tier 1 記輕量計畫確認：`"… — 確認 1 task／3 items 計畫"`）
  - resume／換手時，接手者憑此驗證確認 gate 真的過過，不只信 `phase` 欄位。Tier B 記選型確認
- `estimated_active_minutes`／`actual_active_minutes`：**選填**。Router 判級時的預估主動工時與收尾補記的實際值（估實分記，agentflow 慣例；消費端為判級校準，缺欄＝無記錄）
- `subagent_usage`：**選填**。step 6 子項②收尾時由 `python3 .agent-flow/scripts/token_usage.py <run_id> --write` **實測回寫**的 tokens 彙總 `{"prep": int, "loop": int, "main": int}`——三鍵皆為 transcript 四欄（`input_tokens`／`cache_creation_input_tokens`／`cache_read_input_tokens`／`output_tokens`）加總；`prep`＝usage-analyzer／task-decomposer／impact-analyzer 的 subagent 合計、`loop`＝其餘 subagent 合計、`main`＝主 flow 自身。不以 Agent 工具回執自報、不憑印象估 `main`（估計法系統性低估流程稅）。消費端 `stats.py`：prep／loop 缺一或非 int → 整筆計無記錄；`main` 非 int → 只跳過 main、prep/loop 照收
- `token_usage`：**選填**。與 `subagent_usage` 同時由 `token_usage.py --write` 寫入的明細：`{"session_id", "window": [lo, hi]|null, "main": {四欄＋turns}, "subagents": [{"agent_type", "description", 四欄＋turns}]}`；`window` 取自 `events.jsonl` 首尾 `ts`（init 之前的判級／載 skill 用量不在窗內，屬已知低估面）；`subagents` 為 transcript `subagents/` 目錄 ∪ `run/<run_id>.dispatch.jsonl` 派工留痕（後者 `description` 為 `dispatch:<backend>`、不切窗）。純記錄，無 gate 消費
- `harness`：新 run 依目前 harness 設為 `"codex"` 或 `"claude"`；舊 run 缺欄時使用 Claude 相容行為。`token_usage.py --write` 遇 Codex 時只寫 `token_usage_status: "unknown_codex"`，不把 Claude transcript 當作 Codex 用量
- `session_id`／`config_dir`：**選填**。init 事件（Tier 2 `init --run-id`、Tier 1 `init-run --run-id`）由 `eval_state.py` 自 `CLAUDE_CODE_SESSION_ID`／`CLAUDE_CONFIG_DIR` 環境變數自動寫入，已有值不覆寫（resume 換 session 保留首次）；`token_usage.py` 憑此開 `<config_dir>/projects/<cwd 編碼>/<session_id>.jsonl`。舊 run 缺欄＝該腳本走 fallback 掃描 `~/.claude*/projects/*/` 含 run_id 的 transcript
- `executor_notes`：**選填**。list[str]，每 item 一句 `item <id>: 直寫｜派工 — <理由>`——主 flow 直寫捷徑（eval-flow SKILL.md Tier 1 第 4 點）的執行者選擇留痕；判斷依據是「交接是否划算」，本欄供事後審計。純記錄欄位，無 gate 消費
- `auto_decisions`：**選填**。list[str]，每筆一句 `<問題>｜<選項>｜<採用>｜<理由>`——預設採納模式（ROUTER.md 同名條）下 agent 代替提問所做的決定留痕，收尾回報逐筆列出供使用者檢查。純記錄欄位，無 gate 消費
- `dirty_tree_ruling`：**選填**。前置 0 進場檢查（見 eval-flow SKILL.md）發現 dirty tree 時，使用者對孤兒變更歸屬的裁決一句（納入本 run／擱置不動）；乾淨樹免記（欄位缺席＝進場乾淨或舊 run 無此制）
- `scout_report_path`：**廢止欄位**。無任何步驟寫入、hook 無任何依賴；舊 manifest 仍有此欄者不需回填移除
- `risk_report_path`：**停用欄位**。無任何步驟寫入，新 run 長期維持 `null`；欄位保留於 schema 只為讀舊 manifest（既有 `risk/*.md` 報告為冷溯源，保留不刪）
- `usage_report_path`：**維持 `null` 屬正常**——`usage-analyzer` 由具名問題觸發，答案寫進 Spec、不產獨立報告檔、不回寫此欄；無任何 gate 依賴此欄非空
- `impact_report_path`：語義同上——`impact-analyzer` 由具名問題觸發，答案寫進 Spec、不回寫此欄，新 run 長期維持 `null` 屬正常
- `task_file`：分拆／建 task 後寫入
- `status`：step 6 先由 `run_commit.py prepare` 設為 `"ready_to_commit"`；commit 成功後由 `run_commit.py finalize` 設為 `"completed"`，並回填 `commit_sha`。新 run 的提交快照判定見本文件 `verification_commands` 條款
  - `"aborted"`＝使用者或主 flow **決定不做了**（與 `"failed"`＝流程內判定失敗區分開）；標 `aborted` 時 `failed_reason` 必填（1d 窄例外 gate 為此的機械強制點，見「Gate 的硬性執行」）
  - manifest↔commit 由 `Run-Id: <run_id>` trailer 與 `commit_sha` 雙向核對
- `failed_reason`：`status` 設為 `"failed"` 或 `"aborted"` 時必填，一句話寫死因（哪個 sub_task、卡在哪一步、為什麼；`aborted` 則寫放棄理由），讓接手者不用翻對話記錄
- **`aborted`／`failed` 的 manifest 永不清除**：與本節開頭「冷溯源檔……永不清除」同一條規則，不因狀態放棄／失敗而被刪除或清空——防刪除 gate（見「Gate 的硬性執行」）機械強制此點
- **已知限制**：上述防線只攔 `git` 的刪除與 commit 面；Claude 用 Write／Edit 工具直接覆寫 manifest 內容（含把 `status`／`failed_reason` 改寫或清空）的路徑不在 hook matcher（`Bash|Task|Agent`）內，不攔（已知限制，不修）
- `local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`：**Tier 1 專用憑據欄（豁免歸檔檔）**——Tier 1 不建 `eval_state.json`，這四欄直接寫在 manifest、commit gate 憑此四欄驗放行（語義與 `eval_state.json` 各 sub_task 同欄一致）。Tier 2 的逐 task 憑據仍走歸檔檔路徑；Tier 2 收尾寫入 manifest 的測試摘要不取代各 task 的憑據
- `verification_commands`：Tier 1 與兩個 tier 的收尾驗證記在 manifest；Tier 2 指定 `--sub-task` 的驗證記在對應 task。語義見下方同名欄位。
- `debt`：僅 hotfix 通道使用（見「Hotfix 通道」），記錄欠下的流程債，如 `["test", "retro"]`；還清一項移除一項，清空後才可啟動新 run（hook 強制）

## eval_state.json 格式

熱評分 scratchpad。靠 `run_id` 關聯 manifest；commit 後歸檔為 `run/<run_id>.eval.json` 再清除。

> 下方範例是**欄位形狀骨架**，數值為佔位符、非通過所有不變量的自洽樣本（例如 `review_reds: null` 配非空 `rounds`、全 0 的 `dimensions` 在真實歸檔檔中都會被 hook 擋）；合法組合見「操作規則」與「Gate 的硬性執行」。

**一筆＝一個 task**：審查與測試以 task 為單位，故狀態與憑據全記在這一層。

- **欄位**：`id`／`name`／`status`／`step`／`files`（該 task 全部 item 的聯集）／`warning`／`local_test_passed`／`local_test_evidence`／`verification_commands`／`review_reds`／`review_dimensions`／`checked_by`／`verify_passed`
- **不存 item 層資料**：item 的 DoD 與契約表**只住 task 檔**，`eval_state` 不複製一份——兩份必漂移（R-007）。`find_subtask` 只認頂層 task id，不設 item 層定位入口
- **「全數就緒才進 step 3」無 hook 強制**，由主 flow 對照 task 檔判斷（規則住 eval-flow SKILL.md 循環 step 3）。這是不存 item 層資料的已知代價：換得零額外記帳
- **向後相容**：舊歸檔檔 `run/*.eval.json` 的每一筆代表一個 item（舊語義），且可能帶已移除的 `risk_analysis` 鍵。欄位位置與現行形狀相同，故子命令與 `validate_state` 對其照常可操作；差別只在「一筆代表什麼」，這影響的是 `stats.py` 的分母語義（見該 script 的新舊雙吃）

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
- `verification_commands`：由 `run_verify.py` 執行驗證並追加命令、退出碼及 schema 2 快照；與 `local_test_evidence` 的仲裁、豁免等說明並存。
  - **提交快照判定（單一說明）**：`evidence_schema: 2` 的 Tier 1／2 run，commit gate 檢查 manifest 最後一筆驗證須 `exit_code: 0`、有有效快照且符合目前程式樹；缺席、失敗或輸入變動都拒絕。測試範圍依 tier 與專案要求選定；快照相同不代表測試範圍已足夠。
  - 舊 schema 與 Tier B／hotfix 沿用既有相容規則。`add-verification` 只保留逐 task 命令紀錄，不產生提交所需快照；Tier 2 收尾仍需不帶 `--sub-task` 執行 `run_verify.py`。

## run/<run_id>.events.jsonl 格式

**冷溯源檔**（與本文件開頭「run manifest」節的分類相同：留在工作目錄、永不清除；不進版控）。

- 每個會寫入狀態的子命令（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`archive`）成功寫入（`save()` 之後）append 一行 JSON：`{"ts": "<ISO8601>", "cmd": "<子命令>", "args": {...}}`；唯讀的 `list-files` 不記
- `args` 鍵全記（`func` 與子命令 dest `command` 除外），字串值 >200 字元截斷並標 `…[truncated]`
- `verify_cmd`（Tier 1，run_verify.py 寫）與 `add-verification`（Tier 2）事件的 `args.verify_command`＝驗證指令原文（舊事件因 `command` 鍵被過濾只有 `exit_code`）。消費端 `stats.py` 事件節「全套 N」＝含 `--strike-key full_suite` 的此類事件數，供收尾停止規則（記錄級修正不重跑全套）累積證據；Tier 1 收尾跑累積聯集（`--strike-key wrapup_related`），不計入此數，Tier 1 run 顯示「全套 0」屬正常
- append 是旁路記錄：寫入失敗（如 `run/` 不可寫）僅 stderr warning，不影響原子命令的 exit code；`eval_state.json` 缺 `run_id` 時同樣只 warning 並略過記錄
- **生命週期事件**：Tier 1 的 `init-run`、`hitl-confirm`、`review-run` 分別在狀態寫入後追加 `init`、`hitl_confirmed`、`reviewed`。審查未通過也可記 `reviewed`；事件不代表通過。
  - `run_verify.py` 保留原有 `verify_cmd`／`add-verification`，成功保存驗證結果且退出碼為 0 才追加 `verified`。失敗更新測試欄位為未通過，不寫 `verified`；不改獨立審查結論。
  - `run_commit.py finalize` 核對實際提交、保存完成狀態後才追加 `completed`；prepare 或提交失敗不產生完成事件。事件仍為旁路紀錄，缺事件時依 manifest 與 Git 核對，不能只由事件推定完成。
  - `event` 子命令保留供舊 run 與人工註記使用；標準路徑不手動重複追加上述事件。
- 消費端見 `stats.py`（依 `ts` 欄位取極值計時距；`set-step` 重入依事件的 sub_task id＋`step` 計數，不依賴檔內物理行序）

## run/tier0.jsonl 格式

**冷溯源檔**（單一共用檔、append-only、永不清除；留在工作目錄、不進版控。Tier 0 本身不 commit 的規則不變，見 .agent-flow/ROUTER.md Router）。Tier 0 改完回報時 append 一行：

- 指令：`python3 .agent-flow/scripts/eval_state.py tier0 --summary "<一句>" --files "<逗號分隔清單>" --lines <int：git diff 增＋刪>`
- 行形狀：`{"ts": "<ISO8601 UTC>", "summary": "...", "files": [...], "lines": <int>}`
- **純記錄欄位，不被任何 gate 消費**——加 gate 消費此檔即為判定行為變更，不以留痕存在推定分級通過
- 消費端：`stats.py`「Tier 0 留痕」節（筆數／合計行數／最近一筆 ts；壞行寬容跳過）

## run/<run_id>.dispatch.jsonl 格式

**冷溯源檔**（同 `events.jsonl` 分類：留在工作目錄、永不清除；不進版控）。headless 派工 script `.agent-flow/scripts/dispatch.py` 每次派工 append 一行（派工機制住 eval-flow SKILL.md「派工機制」節）：

- 行形狀：`{"ts": "<ISO8601 UTC>", "role": "<角色>", "backend": "claude|codex", "permissions": "inherit|edits|unrestricted", "session_id": "<claude session_id｜codex thread_id>", "resumed": <bool>, "model": "<model id>", "turns": <int>, "input_tokens": <int>, "cache_creation_input_tokens": <int>, "cache_read_input_tokens": <int>, "output_tokens": <int>, "cost_usd": <float|null>, "duration_ms": <int>, "exit_code": <0|2|3|4>, "envelope": "ok|advisory|blocking|null", "failure": null|"timed_out"|"output_truncated"|"child_error", "out_of_scope": null|[<越界路徑>...], "retro": null|{"selected": [<R-NNN>...], "retire": [<R-NNN>...]}, "permission_denials": [<工具名>...]}`
- `failure`／`out_of_scope`：前者記子程序失敗分類（成功為 null；超時／超量時 `envelope` 為 null、未做信封判定）；後者記 `--files` 越界檢查結果（未給 `--files` 或非 git repo 為 null，無越界為空 list）
- `retro`：code-writer 派工且有 `--files`、無 `--resume` 時，dispatch 自動前置的 retro 條目 id 與 retire 候選 id（RETRO.md 不存在時兩者皆空 list）；其他情況為 null
- `permissions`：實際使用的權限模式（省略參數時依角色：有寫入工具→`edits`，其他→`inherit`）；`permission_denials`：子 agent 被權限拒絕的工具呼叫（Claude 結果的 `permission_denials` 工具名；codex 與子程序失敗為空 list），非空時 `exit_code` 為 2（越界 4 優先）
- codex 用量映射：`cached_input_tokens`→`cache_read_input_tokens`、`cache_write_input_tokens`→`cache_creation_input_tokens`；`cost_usd` 為 null（codex 不回報）
- run_id 由 script 解析（`eval_state.json` → 唯一 tier 1 in_progress manifest，同 gate 7 基準）；解析不到（run 外手動觸發）不落檔
- **純記錄檔，不被任何 gate 消費**；派工紀錄不替代審查結果。消費端：`token_usage.py`（每行一筆 subagent，與 transcript 來源聯集、不切窗）

## eval_state.json 操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .agent-flow/scripts/eval_state.py`（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`list-files`／`archive`）
  - 理由：手動 Edit 是高錯誤面；helper 在寫入前驗證不變量（archive 驗全數 passed），錯誤在落盤前就擋下
- **前置 0（初始化）**：Tier 1 使用 `init-run`；Tier 2 建立 manifest `run/<run_id>.json`（填 `run_id`、`created_at`、`spec_path`，其餘 `null`，`status: "in_progress"`）與 `eval_state.json`（填 `run_id` ＋ 空 `sub_tasks`）。manifest 的 `spec_path` 未填不可往下
- **分拆 task 完成後**：`task_file` 由主 flow（直建，≤2 tasks 且 ≤8 items 含界）或 `task-decomposer`（超門檻條件派工）回寫（時機與條件見 eval-flow SKILL.md 的「Tier 2 完整路徑」節（Tier 2）與「Tier 1 精簡路徑」第 2 點（Tier 1））；`phase` 隨之更新為 `"decomposed"`
- **具名問題觸發 usage-analyzer／impact-analyzer 時**：答案寫進 Spec，**不**回寫 `usage_report_path`／`impact_report_path`（兩欄維持 `null` 屬正常），無 gate 依賴此二欄
- **循環進度記錄（write-ahead，中斷恢復的關鍵）**：每個循環步驟**開始前**先把該 sub_task 的 `step` 寫入 `eval_state.json`，步驟完成後再更新為下一步
  - `step` 值序：`writing`→`reviewing`（並發 review＋verify 階段）→`fixing`（有 🔴 時）→`testing`→`done`；`verifying`／`scoring` 為舊版 run 的相容值，新路徑不寫入
  - code-writer 交付後立刻把本 sub_task 涉及的檔案清單寫入 `files`（修正時同步增補）——staged 變更與 sub_task 的對應關係只准活在這裡，不准只活在對話裡
- **Tier 1 審查記錄**：用 `review-run <run_id> <reds> --checked-by <角色> --evidence "<獨立審查憑據>" [--passed]`；首輪紅數保留，當輪未通過會清除 `verify_passed`。只有全部 task 通過且當輪零紅問題才加 `--passed`。工具只記錄已取得的獨立結論。
- **首輪審查結果出來後（step 3，checker 或升級輪 reviewer；下列 set-* 為 Tier 2 入口）**：執行 `python3 .agent-flow/scripts/eval_state.py set-review <id> <🔴數> [--dimensions '<json>']`
  - `<🔴數>` 記首輪的 🔴 原始數（修正前，有無 🔴 皆須執行；**checker 輪固定填 0**）
  - `--dimensions` 為升級輪 reviewer 報告末尾的維度統計（維度→問題數，五維詞彙：Clarity／Completeness／Testability／Non-functional／Technical_constraints），有 🔴／🟡 時必填，供 stats.py 維度分佈遙測（checker 輪無此節、免填）
  - commit gate 必填 `<🔴數>`，缺一擋歸檔
- **checker 通過或升級輪 reviewer 完成度節通過且該輪零 🔴（step 4 放行、真正進 step 5 的輪次）**：執行 `python3 .agent-flow/scripts/eval_state.py set-verify <id>`，將 `verify_passed` 設為 `true`——commit gate 必填，缺一擋歸檔
  - **語義**：`verify_passed` 記的是「checker 憑據節通過、或升級輪 reviewer 完成度節通過（DoD 無缺席、scope 無偏移）」；hook gate 判定不變
  - 有 🔴 的輪次**不得** set-verify（該輪修正可能改 code 行為）；與 `set-review` 記首輪原始數不同，`set-verify` 記的是**最終通過輪**
- **本地測試通過後（step 5）**：`run_verify.py` 將該 sub_task 的 `local_test_passed` 設為 `true`、`local_test_evidence` 填入驗證證據（指令＋結果摘要；Tier 2 若更新過既有測試，一併註明 Spec／task 依據）。預設 `false`／`null`；hook 於 commit 時檢查歸檔檔中所有 sub_task 兩欄皆已填
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **同一 sub_task 修正 2 輪後 reviewer 仍有 🔴**：`status` 設為 `"failed"`，`warning` 設為 `true`，回報使用者（詳見循環 step 4 修正迭代上限；checker 輪與升級本身不計入此 2 輪）
- **全部完成且通過**：先歸檔為 `run/<run_id>.eval.json`、清除 `eval_state.json`；`run_commit.py prepare <run_id>` 設 `ready_to_commit` 後 commit，成功後 `run_commit.py finalize <run_id>` 回填 `completed` 與 SHA。歸檔檔與 manifest 是工作目錄冷溯源檔，不進版控
- **有任一 failed**：manifest 的 `status` 設為 `"failed"`，並在 manifest 的 `failed_reason` 寫一句話死因（哪個 sub_task、卡在哪步、為什麼），回報使用者
  - **失敗收尾**：staging area 保持原狀（已通過 sub_task 的變更留在 staged），**不自行 unstage、不部分 commit、不清除 `eval_state.json`**，由使用者裁決後續（續跑、部分 commit 或放棄）
  - 失敗收尾時工具 hook 會擋下 agent 的 `git commit`（`eval_state.json` 尚存在）；使用者若決定部分 commit，需先依裁決處置現場狀態
