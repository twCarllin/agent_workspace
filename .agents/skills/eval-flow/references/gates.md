> 本檔由 .agents/skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Gate 的硬性執行（hook）

以下 gate 由 PreToolUse hook（Claude：`.claude/settings.json`；Codex：`.codex/hooks.json`；共用 `.claude/hooks/eval_gates.py`）攔截。Git 的 `commit-msg` hook 另讀實際提交訊息，避免 `-F`、編輯器輸入與 shell 指令文字不同步。攔截點為提交時（gate 1–6）與呼叫流程管制的 subagent 時（gate 7）：

**待驗 manifest 的定位（gate 3–6 的共同前提，2026-09-22 起）**：冷溯源檔不再進版控（見 eval-flow SKILL.md step 6 子項②），故 commit gate **不以「staged 中有沒有 manifest」為啟動條件**。定位依序為：

- **① commit message 的 `Run-Id: <run_id>` trailer**（主路徑）→ 取工作目錄的 `run/<run_id>.json`。解析對象是 Bash 指令原文，故 run_id 只認 `[A-Za-z0-9._-]`、不加行尾錨點（`-m "…"` 的收尾引號不得讓比對整條失效）；路徑合法性仍一律交給 `MANIFEST_RE`（單一判定點，R-001）
- **② staged 中匹配 `MANIFEST_RE` 者**（向後相容：舊 run，以及仍把 `run/` 納入版控的專案），與①取聯集
- **③ 安全網**：①②皆落空時，掃工作目錄 `run/*.json`，任一 `status` 為 `"in_progress"` 或 `"ready_to_commit"` → 擋 commit；若已安裝本框架管理的 Git `commit-msg` hook，交由它核對 Git 實際訊息與憑據
  - 安全網刻意排在 gate 3 窄例外**之後**：窄例外的成立條件是「staged 恰一個 aborted／failed manifest、不含任何 code」，該 commit 純為留痕放棄的 run，不該被另一個未收尾的 run 卡死；兩者的 `status` 條件互斥，不存在攔截型被永久遮蔽的情境（與 R-008 的攔截型優先原則不衝突，組合測試見 `tests/test_eval_gates.py` C10）
- 判定基準是**工作目錄**（`os.path.exists`／`glob`），與 gate 2 防刪除的 git 索引基準（`--diff-filter=D`）不同；兩者的發散情境與處置明列於 `eval_gates.py` 的 `_manifest_path_from_command` docstring（R-009）

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔；失敗收尾時也會擋，屬預期）。**窄例外（見 gate 3）**：staged 檔案集合恰為該 run 的 manifest 一個檔、`status` 為 `aborted`／`failed`、`failed_reason` 非空 → 豁免本 gate（**不豁免 gate 2**）
2. **防刪除 gate**：staged 變更中出現 manifest（`run/*.json`，`MANIFEST_RE` 匹配者）的**刪除**（`git diff --cached --diff-filter=D`）→ 擋 commit，訊息指示改標 `aborted` 而非刪檔（歸檔檔／baseline 檔不受 `MANIFEST_RE` 匹配，不受本 gate 攔截）
   - **執行順序（硬性）**：本 gate 必須早於 gate 3 的窄例外判定執行——`git rm --cached` 會保留工作區檔案，若窄例外先讀檔案內容判定，會誤把「已從版控刪除」的 manifest 當成「內容合法的 aborted/failed 留痕」而放行，讓 manifest 消失卻繞過本 gate（2026-08-20 code-review 修正，R-008）
   - 窄例外**不豁免**本 gate
3. **intent gate**：**定位到的** `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `"ready_to_commit"`／舊版 `"completed"` → 擋
   - **窄例外**（aborted／failed 留痕）：staged 檔案集合恰等於該一個 manifest、且 `status` 為 `"aborted"` 或 `"failed"`、且 `failed_reason` 非空 → 放行（同時豁免 gate 1，**不豁免 gate 2**）；任一條件不成立 → 原判定不變
4. **測試 gate**：定位到的 manifest 對應的 `run/<run_id>.eval.json` **不存在**（staged 與工作目錄皆無）、或其中任一 sub_task 非 `passed`／`local_test_passed` 非 `true`、或 `review_reds` 未留痕（非 int 或負數）／`verify_passed` 非 `true` → 擋（`verify_passed` 語義＝reviewer 完成度節通過，見操作規則）
   - **Tier 1 分支**：若 `run/<run_id>.eval.json` 不存在，改驗 manifest 自身四欄（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`），全過放行、豁免歸檔檔；歸檔檔存在時走原路徑（Tier 2 現行，Tier 1 向後相容）
5. **假測試 lint gate**：**定位到 manifest**（flow 收尾 commit）時，staged 的 Python 測試檔跑 `test_lint.py`——啟動條件隨上方定位改變，不再只認 staged manifest，否則溯源檔不進版控後本 gate 會整條失效，檢出 if-guard 藏斷言／無斷言／恆真斷言 → 擋（誤報以行尾 `# testlint: allow` 豁免並留痕，見 test-strategy skill）
6. **不變量驗證**：歸檔檔 `run_id` 與 manifest 不一致 → 擋
   - `evidence_schema: 2` 的新 run 另核對最後一次全套驗證的程式樹快照；任何改動使快照失效，須重跑驗證
7. **phase 狀態機（subagent 呼叫攔截）**：依 `eval_state.json.run_id` 定位 manifest，檢查 `phase` 是否達到該 agent 的最低要求，未達 → 擋呼叫（`PHASES` 值域 2026-09-22 起收斂為 `init` → `decomposed` → `completed`，見 `references/formats.md`）：
   - `usage-analyzer`／`impact-analyzer`／`task-decomposer` 皆需 `phase >= init`（等同「manifest 已建即可呼叫」）——前置 1 風險分析已刪除（Q1）、usage／impact 改具名問題觸發、task-decomposer 改條件派工，三者 `AGENT_MIN_PHASE` 收斂為 `init`；`task-decomposer` **不再**要求 `usage_report_path` 非空
   - `code-writer` 需 `phase >= decomposed` 且 `task_file` 非空。`risk_analysis.blocking` 遍歷判定已移除（Q8）——`risk_analysis` 欄位隨前置 1 刪除不再寫入，該判定恆為死碼，一併清除，不留孤兒條文
   - **舊值相容**：既有 manifest 的 `phase` 為 `risk_done`／`usage_confirmed` 時，`manifest_phase()` 在比對值域前先映射為 `init`，不因值域收斂而拋例外（DoD 2，細節見 `references/formats.md`）
   - **共通前提**：intent gate 通過且 manifest 存在。`eval_state.json` 存在時依其 `run_id` 定位 manifest
   - **Tier 1 分支**：`eval_state.json` 不存在時，掃 `run/` 找唯一一個 `tier: 1` 且 `status: "in_progress"` 的 manifest 作為當前 run 依據（找到唯一一個 → 繼續後續 gate；找不到或多個 → 擋，原訊息語義）
   - `check_other_runs` 在兩條路徑下都執行（Tier 1 單一 run 原則不因豁免而失效）

被擋時 hook 會以 stderr 回報原因，依訊息補齊狀態後重試。流程中亦可隨時自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。工具 hook 覆蓋 agent 的受支援工具呼叫；Git `commit-msg` hook 也攔一般終端提交。hook 仍可能被停用或繞過，CI 可重跑同一驗證作為專案邊界。

## 報告信封 lint（PostToolUse hook，2026-09-07 起）

`.claude/hooks/report_envelope_check.py`（設定於 `.claude/settings.json`，matcher `Task|Agent`）於 subagent 交付時機械驗收報告信封。缺項二分（2026-09-21）：

| 類別 | 項目 | hook 行為 | 主 flow 處置 |
|---|---|---|---|
| **blocking** | 末行恰一個 `Self-check:`；`task-verifier` 兩節關鍵詞（完成度／憑據） | exit 2，stderr 標準化退件訊息（一併列出 advisory 缺項） | 退件重取，上限與第 2 次處置見 SKILL.md 憑據紀律 |
| **advisory** | 首行戳記行（前 3 個非空行內） | exit 0，stdout 印 PostToolUse JSON `hookSpecificOutput.additionalContext` 警告 | 不退件，照常解析，回報留痕一句 |

合規（兩類皆無缺項）→ exit 0、無輸出。

- **性質**：品質 lint、**fail-open**（stdin 非 JSON、欄位缺席、背景啟動回執、非信封名單 agent 一律放行）——**不是安全 gate**，不承擔攔截惡意內容的職責；與上方 PreToolUse gate 1–7 的攔截性質不同
- 信封名單與載荷依據（2026-09-07 實測 PostToolUse `tool_response.content[].text`）住 script 檔頭，改名單時只改 script
