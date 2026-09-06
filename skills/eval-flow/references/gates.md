> 本檔由 skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Gate 的硬性執行（hook）

以下 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，設定於 `.claude/settings.json`，matcher `Bash|Task|Agent`）強制攔截，不再只靠文字約束。攔截點有二：Claude 執行 `git commit` 時（gate 1–6），與呼叫流程管制的 subagent 時（gate 7）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔；失敗收尾時也會擋，屬預期）。**窄例外（見 gate 3）**：staged 檔案集合恰為該 run 的 manifest 一個檔、`status` 為 `aborted`／`failed`、`failed_reason` 非空 → 豁免本 gate（**不豁免 gate 2**）
2. **防刪除 gate**：staged 變更中出現 manifest（`run/*.json`，`MANIFEST_RE` 匹配者）的**刪除**（`git diff --cached --diff-filter=D`）→ 擋 commit，訊息指示改標 `aborted` 而非刪檔（歸檔檔／baseline 檔不受 `MANIFEST_RE` 匹配，不受本 gate 攔截）
   - **執行順序（硬性）**：本 gate 必須早於 gate 3 的窄例外判定執行——`git rm --cached` 會保留工作區檔案，若窄例外先讀檔案內容判定，會誤把「已從版控刪除」的 manifest 當成「內容合法的 aborted/failed 留痕」而放行，讓 manifest 消失卻繞過本 gate（2026-08-20 code-review 修正，R-008）
   - 窄例外**不豁免**本 gate
3. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `"completed"` → 擋
   - **窄例外**（aborted／failed 留痕）：staged 檔案集合恰等於該一個 manifest、且 `status` 為 `"aborted"` 或 `"failed"`、且 `failed_reason` 非空 → 放行（同時豁免 gate 1，**不豁免 gate 2**）；任一條件不成立 → 原判定不變
4. **測試 gate**：staged manifest 對應的 `run/<run_id>.eval.json` 未同批 staged、或其中任一 sub_task 非 `passed`／`local_test_passed` 非 `true`、或 `review_reds` 未留痕（非 int 或負數）／`verify_passed` 非 `true` → 擋（`verify_passed` 語義＝reviewer 完成度節通過，見操作規則）
   - **Tier 1 分支**：若 `run/<run_id>.eval.json` 未 staged，改驗 manifest 自身四欄（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`），全過放行、豁免歸檔檔；已 staged 時走原路徑（向後相容）
5. **假測試 lint gate**：staged 有 manifest（flow 收尾 commit）時，staged 的 Python 測試檔跑 `test_lint.py`，檢出 if-guard 藏斷言／無斷言／恆真斷言 → 擋（誤報以行尾 `# testlint: allow` 豁免並留痕，見 test-strategy skill）
6. **不變量驗證**：歸檔檔 `run_id` 與 manifest 不一致 → 擋
7. **phase 狀態機（subagent 呼叫攔截）**：依 `eval_state.json.run_id` 定位 manifest，檢查 `phase` 是否達到該 agent 的最低要求，未達 → 擋呼叫：
   - `usage-analyzer` 需 `phase >= risk_done`（前置 1 未完不可跑前置 2）
   - `task-decomposer` 需 `phase >= usage_confirmed` 且 `usage_report_path` 非空；為 `"skipped"`（Tier 1）也擋
   - `code-writer` 需 `phase >= decomposed` 且 `task_file` 非空；任一 sub_task `risk_analysis.blocking: true` 也擋
   - **共通前提**：intent gate 通過且 manifest 存在。`eval_state.json` 存在時依其 `run_id` 定位 manifest
   - **Tier 1 分支**：`eval_state.json` 不存在時，掃 `run/` 找唯一一個 `tier: 1` 且 `status: "in_progress"` 的 manifest 作為當前 run 依據（找到唯一一個 → 繼續後續 gate；找不到或多個 → 擋，原訊息語義）
   - `check_other_runs` 在兩條路徑下都執行（Tier 1 單一 run 原則不因豁免而失效）

被擋時 hook 會以 stderr 回報原因，依訊息補齊狀態後重試。流程中亦可隨時自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。hook 只攔 Claude 的 Bash 工具，不影響使用者自己終端的 git 操作。本 skill 對應條文為流程說明，實際防線以 hook 為準。

