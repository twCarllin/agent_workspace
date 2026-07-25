# Scout 蒐證：2026-07-25-tier2-p-worktree

> Spec: `spec/2026-07-25-tier2-p-worktree.md`
> 只記事實與原文引文（附行號），不下判斷。

## 相關模組／檔案清單

- `skills/eval-flow/SKILL.md` — Tier 2 完整 eval flow 執行細節：前置 0–3、循環 step 1–7、Tier 1 精簡路徑、manifest 與 eval_state.json 格式、hook gate 清單
- `skills/parallel-run/SKILL.md` — 多 Tier 1 需求並行執行：worktree 隔離、背景 agent、rolling merge、卡住協定
- `skills/task-decomposition/SKILL.md` — 工作拆分框架：拆分粒度、平行化條件、item 行數估計、輸出格式
- `.claude/agents/task-verifier.md` — 任務完成度驗證員：讀 staged diff、DoD 逐條核對、scope 偏移檢查
- `.claude/agents/code-reviewer.md` — 程式碼審查員：讀 staged diff、五大面向
- `.claude/hooks/eval_gates.py` — gate 1–6、phase 狀態機、manifest 讀取、不變量驗證
- `.claude/hooks/eval_state.py` — eval_state.json 操作 helper（init／add-subtask／set-step／set-files／set-test／set-status／set-review／set-verify／list-files／archive）
- `.claude/hooks/gate-check.sh` — PreToolUse hook shell 外殼，將 hook JSON 交給 eval_gates.py
- `tests/test_eval_gates.py` — ValidateStateTest、ManifestPhaseTest、ManifestRegexTest、TestFileDetectionTest
- `tests/test_eval_state.py` — EvalStateHelperTest（CLI 子指令覆蓋）

## 關鍵 symbol 與函式簽名

### eval_gates.py

- `validate_state(state, source, require_passed=False)` @ 74–102 — 驗證 eval_state 不變量：run_id、sub_task 狀態、local_test_passed、local_test_evidence、review_reds、verify_passed
- `check_manifest(manifest_path, staged)` @ 104–132 — manifest 與 eval 歸檔檔一致性
- `manifest_phase(manifest)` @ 135–144 — 讀 manifest.phase；舊 manifest 無此欄時推導（task_file → "decomposed"、usage_report_path → "usage_confirmed"、預設 "init"）
- `check_task_gate(tool_input)` @ 201–245 — subagent 呼叫 phase 門檻檢查
- `AGENT_MIN_PHASE` dict @ 31–36 — `{"usage-analyzer": "risk_done", "impact-analyzer": "usage_confirmed", "task-decomposer": "usage_confirmed", "code-writer": "decomposed"}`
- `PHASES` list @ 30 — `["init", "risk_done", "usage_confirmed", "decomposed", "completed"]`
- `MANIFEST_RE` regex @ 22–24 — `r"^run/(?P<run_id>[^/]+?)(?<!\.eval)(?<!\.test_baseline)\.json$"`

### eval_state.py

- `cmd_init(args)` @ 62–66 — 初始化：run_id ＋ 空 sub_tasks
- `cmd_add_subtask(args)` @ 69–82 — 新 sub_task 欄位骨架：`{"id", "name", "status": "in_progress", "step": None, "files": [], "warning": False, "local_test_passed": False, "local_test_evidence": None, "review_reds": None, "verify_passed": False, "risk_analysis": None, "review_dimensions": None}`
- `cmd_set_step(args)` @ 84–88 — step 合法值 `["writing", "reviewing", "fixing", "verifying", "testing", "done"]`
- `cmd_set_files(args)` @ 91–95 — files 清單（去重保序）
- `cmd_set_test(args)` @ 98–111 — local_test_passed／local_test_evidence
- `cmd_set_status(args)` @ 114–122 — status 合法值 `["passed", "failed", "in_progress"]`
- `cmd_set_review(args)` @ 127–156 — `set-review <id> <reds> [--dimensions '<json>']`；維度有效鍵 `{"Clarity", "Completeness", "Testability", "Non-functional", "Technical_constraints"}`
- `cmd_set_verify(args)` @ 159–163 — verify_passed: true
- `cmd_list_files(args)` @ 166–173 — 所有 sub_task 的 files 聯集（逐行），用於 `git diff --cached -- <files>`
- `cmd_archive(args)` @ 176–188 — 呼叫 `eval_gates.validate_state(state, STATE_PATH, require_passed=True)`，通過後歸檔 `run/<run_id>.eval.json` 並刪 `eval_state.json`

### task-verifier.md

- `git diff --cached` 讀 staged 變更 @ 行 21–24 — 固定指令、staged area 為空時停止驗證
- DoD↔測試對應核對 @ 行 43

### code-reviewer.md

- `git diff --cached` 讀 staged 變更 @ 行 15–18 — 固定指令、staged area 為空時停止審查
- 五維詞彙 @ 行 70；維度統計輸出 @ 行 102（合法 JSON、無問題時寫「無」）

## 既有慣例觀察（原文引用）

### eval-flow「單一 run 原則與併發」（skills/eval-flow/SKILL.md 273–279）

```
## 單一 run 原則與併發（worktree 隔離）

- **一個 worktree 同一時間只允許一個 in_progress 的 run**。這不是任意規定：`eval_state.json` 是單例、git staging area 也是單例，同工作區並行兩個 run 必然互相污染（staged 變更分不開、commit 切不乾淨）
- **要並行 → 開 `git worktree`**：每個 run 在自己的 worktree／branch 裡跑，單例假設在 worktree 內自然成立，收尾各自 commit 後合回主線。**≥2 個互不相依的 Tier 1 需求同時進來時，依 `parallel-run` skill 執行**（批次 HITL、背景 agent、merge 收尾的細節住在該 skill）
- **插單（run 跑到一半來了急件）**：原 run 的 worktree **原地凍結**（狀態已全在 manifest／`eval_state.json`／staging area 裡，不需要任何「暫停」操作），急件在新 worktree 處理，完成後回原 worktree 依 `eval-flow-resume` skill 接續
```

### 單一 run 內 [P] 平行測試 barrier（skills/eval-flow/SKILL.md 279）

```
**單一 run 內 [P] 平行寫作的測試 barrier**：若同一 run 內多個 `[P]` item 由併發 code-writer 寫作，各 item 的 step 5 相關測試可各自先跑，但**全套 baseline/check（step 6 ⓪ full_suite）是 join barrier**——必須等**所有**平行 writer 都交付、各自 🔴 清零並過 task-verifier 後，才跑一次；不可在部分 writer 交付時就跑（會測到不完整／交錯的樹，gate 判定失真）。此條僅限「單一 run 內」平行；跨 run 平行走 `parallel-run` skill，各自 worktree 各跑各的 step 5，不受此條約束。**mine 模式在 `[P]` 平行下不適用**：共用同一棵樹時未提交變更混雜多個 writer，範圍推導失效——派工 prompt 改指定測試檔清單，或各開 worktree（見 test-strategy skill 的 writer 層 mine 模式節）
```

### 循環 step 2–3 派 reviewer/verifier（skills/eval-flow/SKILL.md 80–81）

```
2. 將變更檔案 `git add` 進 staging area（確保 code-reviewer / task-verifier 可透過 `git diff --cached` 讀取）
3. **同一訊息並發呼叫** `code-reviewer` 與 `task-verifier`（兩者皆唯讀、讀同一份 staged diff、互不依賴輸出——序列跑是純浪費）。`step` 欄位於並行階段記 `reviewing`（`verifying` 保留供舊 run resume 相容，新路徑不再單獨使用）
```

### 測試管轄註記（skills/eval-flow/SKILL.md 77）

```
**測試管轄註記**：派工 prompt 附一句「測試自驗只准跑 `python3 .claude/hooks/test_baseline.py mine --strike-key sub_task_<id>`，依你定義中的測試管轄規則」（writer 層 mine 模式細節住 test-strategy skill，不重述；`[P]` 平行 item 不適用 mine，改在 prompt 指定測試檔清單，或各開 worktree）
```

### parallel-run worktree 開設（skills/parallel-run/SKILL.md 28–32）

```
5. **每需求開一個 worktree**：
   git worktree add ../<repo>-<slug> -b feat/<run_id>
   `run_id` 依 eval-flow 慣例：`YYYY-MM-DD-<slug>`。
```

### parallel-run 既有測試只增不改（skills/parallel-run/SKILL.md 39）

```
- **既有測試只增不改**（含 fixture／conftest／測試工具檔）：發現必須修改既有測試＝這個變更動到既有行為＝獨立性假設已破 → 觸發「卡住即停」，該需求退出並行（之後改序列跑）。單一 run 的「有意行為變更同步舊測試」規則僅在非並行模式適用。
```

### parallel-run rolling merge 序列（skills/parallel-run/SKILL.md 49–53）

```
1. **機械檢查①（測試完整性）**：`git diff main...feat/<run_id> --name-status` 過濾測試路徑（含 conftest／fixture／測試工具檔），出現 M／D → 不 merge，把 diff 列給使用者過目（判準只有一個：測試有沒有被改弱）。純 A（新增檔）放行。
2. **機械檢查②（實際交集重驗）**：本支與其他未合支的**實際** changed-file 清單取交集，非空 → 停下回報（前置 2 是預估，此處以實際值重驗）。
3. **後合者先同步**：在自己 worktree `git merge main`，重跑自己的相關測試，綠了才進下一步（真衝突 → 停下回報，不自行硬解）。
4. `git merge feat/<run_id>` 進 main → 跑**全套測試**，判準為「相對 merge 前 main 的 baseline 無新增失敗」（非絕對全綠，避免 main 既有 flaky 卡死收尾）。全套 baseline 在合**第一支前**跑一次快照，存 `run/parallel-merge-YYYY-MM-DD.test_baseline.json`（批次層級，不屬於任一 run）。
5. 綠 → append 該 run 帶回的 BUGLOG 條目（append 前先 grep 舊條目做兩層制升級判定）→ `git worktree remove ../<repo>-<slug>` 並刪除 feat branch。
```

### parallel-run 卡住協定（skills/parallel-run/SKILL.md 57–61，條 11–13）

```
11. **停前落盤（硬要求）**：manifest 標 `status: "blocked"`＋一句 blocked_reason；寫自足卡點報告 `run/<run_id>-blocked.md`（重現步驟、目前的根因假設、試過什麼且為何失敗、要使用者裁決的問題與選項）。落盤後才停——恢復路徑不保證是同一個 agent，沒落盤備援就斷了。
```

### task-decomposition Step 4 [P] 標註（skills/task-decomposition/SKILL.md 81–88）

```
## Step 4：標註平行化與依賴

- **`[P]` 可平行化**的條件（兩者都要成立）：
  - 不共用檔案（無 merge 衝突面）
  - 無資料依賴（不需要另一個 item 的產出當輸入）
- 有依賴的 item 明確標 `depends: <item id>`。前置基礎 task（DB schema / 共用型別）幾乎都是其他 item 的依賴，不可標 `[P]`。
```

### task-decomposition item 行數估計格式（skills/task-decomposition/SKILL.md 99–102）

```
- [ ] 1.1 <item 描述＋單元測試>  ~<估計行數（含測試、已 ×2 校準）>行  files: <實作路徑>, tests/...
      DoD: <可驗收條件>  情境: <usage 報告中的情境 id>
      契約: <輸入> → <可觀察效果>；<輸入> → <效果>；[邊界] <怪輸入> → <效果>
```

### task-decomposition 行數校準（skills/task-decomposition/SKILL.md 60）

```
**校準（實測教訓）：** 上表是「邏輯骨架」的量級，實際 diff 還有 docstring、錯誤路徑、常數表——實測顯示 naive 粗估**系統性低估 2–3 倍**。申報行數 = 表列量級估出的數 **×2**。寧可高估觸發再拆，不可低估躲 300 行上限（低估會讓軟上限形同虛設）。
```

## 呼叫端與現有測試位置

### eval_gates.py 引用處

- hook 配置：`.claude/settings.json`（matcher `Bash|Task|Agent`）；`gate-check.sh` 1–5 呼叫 `eval_gates.py --hook`
- manifest 欄位讀取：eval_gates.py 104–132、135–144、220–227 — 讀 spec_path、spec_inline、status、phase、usage_report_path、task_file、risk_analysis.blocking；舊 manifest 無 phase 欄位時向後相容推導
- phase 狀態機：AGENT_MIN_PHASE dict（31–36）、manifest_phase（135–144）、check_task_gate（201–245）

### eval_state.py 引用處

- eval_gates.py 27、183 — `import eval_gates`、`validate_state(..., require_passed=True)`
- `set-review`：eval-flow/SKILL.md 行 206、eval_state.py 行 227–233
- `set-verify`：eval-flow/SKILL.md 行 206、eval_state.py 行 235–237
- `list-files`：eval-flow/SKILL.md 行 200（操作規則、helper 子指令清單）、eval_state.py 行 239–240

### 測試檔清單

- `tests/test_eval_gates.py`：ValidateStateTest（28–111）／ManifestPhaseTest（113–129，向後相容推導）／ManifestRegexTest（132–147，含排除 .eval.json 與 .test_baseline.json）／TestFileDetectionTest（150～）
- `tests/test_eval_state.py`：EvalStateHelperTest（23–150）— init（41–51）、set-step／set-files（53–59）、set-test（61–67）、list-files（69–78）、archive（80–98、120–129）、set-review（105–108、137–150）、set-verify（115–118）

## Manifest 既有欄位全集

（樣本：`2026-07-16-floor-audit-gates.json`、`2026-07-17-remove-eval-scorer.json`、`2026-07-18-scout-agent.json`、`2026-07-25-tier2-p-worktree.json`）

`run_id`、`created_at`、`framework_version`、`tier`（1／2／"B"／"hotfix"）、`tier_rationale`、`phase`（init／risk_done／usage_confirmed／decomposed／completed；舊檔無此欄由 hook 推導）、`spec_path`、`spec_inline`、`test_command`、`hitl_confirmed_at`、`hitl_rejections`（或無此欄，向後相容）、`risk_report_path`、`scout_report_path`（舊檔無此欄視同 skipped）、`usage_report_path`、`impact_report_path`、`task_file`、`status`（in_progress／completed／failed／blocked〔parallel-run 專用〕）、`failed_reason`、`debt`（hotfix 專用）、`bootstrap_verified`（Tier B 專用）

向後相容推導邏輯（eval_gates.py 135–144）：無 phase 欄位 → 有 task_file 推 "decomposed"；有 usage_report_path 推 "usage_confirmed"；否則 "init"。
