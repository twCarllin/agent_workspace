* _2026-09-22 18:45 (claude-opus-4-8[1m])_

# 影響面盤點 — Tier 2 流程瘦身（run_id: 2026-09-22-tier2-slimming）

> 依 `spec/2026-09-22-tier2-slimming.md` §3 目標狀態、§4 DoD、§5 裁示 Q1–Q7 與 `usage/2026-09-22-tier2-slimming.md` 盤點。
> 行號以 `grep -n` 現查取得（2026-09-22）。本報告不依賴對話上下文，任何接手者讀檔即可核對。
> 重心在第 4 節（被改介面呼叫端窮舉）；四個被改／被刪介面分列 4A–4D 子表。

---

## 1. 觸及模組清單

- `.claude/hooks/eval_gates.py` — `PHASES`／`AGENT_MIN_PHASE`／`manifest_phase()`／`check_task_gate()` 是 phase 值域收斂（§3.2）與 task-decomposer 專屬判定移除（§3.2 末）的核心改動點。
- `.claude/hooks/eval_state.py` — `sub_tasks` 由「一 item 一筆」改「一 task 一筆、item 降為 `items`」（§5 Q2）後，各子命令的 `find_subtask` 定位與 skeleton 欄位須同動。
- `.claude/hooks/stats.py` — rework／checked_by／維度分母改讀 task 層並須同時吃新舊兩種 sub_task 形狀（§5 Q2 已載明分母語義斷點）。
- `.claude/hooks/session_start.py` — 讀殘留 manifest `phase` 字串顯示提醒（不做 index，值域收斂後無害，列為完整性互動點）。
- `.claude/hooks/devlog.py` — ③sub_task 段遍歷 `archive["sub_tasks"]`、①段印 `phase`／`usage_report_path`／`impact_report_path`（純顯示，須容忍新形狀與長期 null）。
- `.claude/hooks/test_baseline.py` — `_append_mine_log`（落檔，D1 刪）與 `cmd_mine` 的 mine 自驗本體（D1 留）耦合在同一函式呼叫鏈。
- `skills/eval-flow/SKILL.md` — 前置 0–3 條文、循環 step 1–7（審查改 per-task、批前快照／mine_log／審查落檔刪除）、收尾清檔清單，本次條文改動最集中處。
- `skills/eval-flow-resume/SKILL.md` — phase 值域、審查落檔恢復、sub_task 定位三者直接波及（§3.5 末已明列在範圍內；Q4／Q6）。
- `skills/usage-scenario-analysis/SKILL.md`／`skills/task-decomposition/SKILL.md` — 前置 2 降為具名問題觸發、task-decomposer 擋人判定移除（D2、§3.2 末）。
- `skills/test-strategy/SKILL.md` — mine_log 落檔條文（D1）。
- `.claude/agents/usage-analyzer.md`／`impact-analyzer.md`／`task-decomposer.md`／`code-writer.md`／`task-verifier.md` — 具名問題觸發、報告不落檔、批前快照／mine_log 輸入移除（D1、D2）。
- `tests/`（test_eval_gates.py、test_eval_state.py、test_stats.py、test_run_verify.py、test_devlog.py、test_session_start.py、test_test_baseline.py、test_docs_consistency.py）— fixture 建構與斷言隨上述介面同動（DoD 1／2／3）。
- 既有歸檔檔 `run/*.eval.json`（**19 份**，非 Spec 概述的 5 份）— 舊「per-item flat」形狀，`stats.py` 須同時吃（見第 4 節 4A、第 5 節）。

---

## 2. 各模組既有慣例

### 2.1 hook script 的 fail-open／fail-safe 慣例

- **主判定路徑 fail-safe（擋）**：`eval_gates.block()` 一律 `sys.exit(2)`（`.claude/hooks/eval_gates.py:89-94`）；`load_json` 讀不到即 `block`（`:97-102`）。gate 判定不通過就擋，不放行。
- **旁路動作 fail-open（不擋主路）**：事件留痕失敗只 stderr warning、不改 exit code（`.claude/hooks/eval_state.py:69-86` `append_event`、`:89-107` `record_session`）；gate 遙測寫檔失敗吞掉（`eval_gates.py:75-86` `log_gate_hit`，`except OSError: pass`）；`_append_mine_log` 失敗回 `None` 不阻擋測試（`test_baseline.py:335-365`，docstring 明寫「純記帳，失敗不得阻擋測試流程」）。
- **推導不得吞例外**：`manifest_phase()` 用「先比對值域、命中才回、否則推導」而非 try/except 吞 `ValueError`（`eval_gates.py:178-187`）——usage 報告正確性假設 2 明列「不得用 try/except 吞例外」（R-005 同型）。**新映射須沿此慣例：在 `PHASES.index()` 之前把舊值轉成新值，不可靠兜底。**

### 2.2 helper script 的子命令結構慣例

- `eval_state.py` 用 argparse subparsers＋`set_defaults(func=cmd_*)`（`:320-395`）；每個 `cmd_*` 固定序：`load()` →`find_subtask(state, args.id)` 取該筆 →就地改欄 →`save(state)` →`append_event(state.get("run_id"), "<cmd>", args)` →`print`（範例 `cmd_set_step` `:143-148`、`cmd_set_review` `:194-234`）。
- 定位唯一入口 `find_subtask(state, sid)`（`:110-114`）：遍歷 `state["sub_tasks"]` 比對 `id`，找不到即 `fail`。**per-task 改構後，item 層的定位須新增第二層鍵（`items`）或新 helper，不可再假設頂層一筆即 item。**
- skeleton 欄位集中在 `cmd_add_subtask`（`:130-137`）——新增/改欄位須改此處預設值並同步 `find_subtask` 消費點。
- 合法值以模組級常數集中：`STEPS`（`:33`）、`STATUSES`（`:34`）、`VALID_DIMENSIONS`（`:187`）、`VALID_CHECKED_BY`（`:190-191`）。
- 向後相容既有寫法：`cmd_add_verification` 用 `st.setdefault("verification_commands", [])`（`:253`）容忍舊 sub_task 無此鍵——per-task 讀 `items` 時可沿用 `.get("items", [])` 同型寬容。

### 2.3 測試的 fixture 建構慣例

- `make_sub_task(**overrides)` 工廠（`tests/test_eval_gates.py:14-25`）產一筆「per-item」sub_task（含 `review_reds`／`verify_passed`／`local_test_passed`）；`state(**overrides)` 包成 `{"run_id":"t","sub_tasks":[make_sub_task(...)]}`（`:29-30`）。**per-task 改構後這個工廠是新舊形狀的分界，須決定它產新形狀還是新增 `make_task` 工廠。**
- CLI 型測試用 `run_cli(...)` 呼子命令、`read_state()` 讀回斷言（`tests/test_eval_state.py`，如 `:41,55-63`）。
- gate 型測試用 `_write_state_and_manifest(phase)` 建 manifest＋空 `sub_tasks`（`tests/test_eval_gates.py:254-267`）；phase 以字串直填（`:262,456,605`）。
- 慣例：斷言「不拋例外」的測試須加 `# testlint: allow` 註記（多處，如 `:32,53,84`）。

---

## 3. 可重用既有元件（優先沿用，勿新發明）

- `.claude/hooks/eval_gates.py:178-187` `manifest_phase()` — **既有向後相容推導範式**。舊 manifest 無 `phase` 欄時由 `task_file`／`usage_report_path` 推導。§3.2 的「risk_done／usage_confirmed → init」映射應加在此函式內、置於 `PHASES.index()` 消費點之前，直接擴充既有分支，不另寫映射層。
- `.claude/hooks/stats.py:177-184` — **既有 legacy fallback 範式**：「頂層 `review_reds` 優先，無則 fallback `rounds` 數」。新舊 sub_task 形狀相容應沿此模式（先試 task 層新鍵、缺則退回 item 層舊讀法），勿另起爐灶。
- `.claude/hooks/stats.py` 全檔的「鍵不存在＝無記錄、不計入分母」寬容讀法（`:143-148,168-170,192-207`）— per-task 分母改讀 task 數時沿用同一寬容原則，缺鍵計「無記錄」而非崩潰（K 情境 DoD 5）。
- `.claude/hooks/eval_gates.py:105-120` `_validate_credentials()` — **四欄憑據單一判定點**，per-subtask 與 Tier 1 manifest 共用。per-task 改構後每 task 一筆憑據仍可餵此函式（usage 正確性假設 4），不需複製一份 task 層驗證。
- `.claude/hooks/eval_state.py:110-114` `find_subtask()` — task 層定位可直接復用；item 層定位建議在其回傳的 task dict 上再取 `items`，沿用同一遍歷風格。
- `.claude/hooks/eval_state.py:253` `st.setdefault(...)` 與 `.get(key, default)` 寬容取值 — 讀新增 `items` 鍵時沿用，兼容尚未遷移的舊 state。

---

## 4. 被改介面的呼叫端清單（窮舉）

> 每子表末附「查詢方法」欄（實際 grep pattern＋命中數），接手者可重跑稽核。

### 4A. `eval_state.sub_tasks` 結構：per-item → per-task（§5 Q2）

現行每筆＝一個 item（skeleton 見 `eval_state.py:130-137`）。變更後每筆＝一個 task，item 降為該筆內 `items` 清單。以下為所有讀寫點：

| 檔案:行號 | 讀取/寫入什麼 | 結構變更後的後果 | 是否必改 |
|---|---|---|---|
| `.claude/hooks/eval_state.py:110-114` `find_subtask` | 遍歷 `sub_tasks` 比對頂層 `id` | 頂層 id 改為 task id；item 定位失去入口 | 是（新增 item 層定位或雙層 helper） |
| `.claude/hooks/eval_state.py:126-140` `cmd_add_subtask` | append 一筆 per-item skeleton | 須改為建 task 筆＋巢狀 `items`，或新增 add-item 語義 | 是 |
| `.claude/hooks/eval_state.py:143-148` `set-step` | `find_subtask(...).step` | step 屬 item 或 task？粒度須定（審查改 per-task，但 writing/testing 可能仍 per-item） | 是（歸屬待定，見第 6 節） |
| `.claude/hooks/eval_state.py:151-156` `set-files` | `find_subtask(...).files` | files 聚合層級改變（list-files 聯集受影響） | 是 |
| `.claude/hooks/eval_state.py:159-173` `set-test` | 寫 `local_test_passed`／`local_test_evidence` | §3.3 測試改 per-task → 應寫 task 層 | 是 |
| `.claude/hooks/eval_state.py:176-184` `set-status` | 寫 `status`／`warning` | status 歸屬 task 層（Q5：items 全就緒才 passed） | 是 |
| `.claude/hooks/eval_state.py:194-234` `set-review` | 寫 `review_reds`／`review_dimensions`／`checked_by` | 審查 per-task → 憑據記 task 層（usage 假設 4） | 是 |
| `.claude/hooks/eval_state.py:237-242` `set-verify` | 寫 `verify_passed` | 同上，task 層 | 是 |
| `.claude/hooks/eval_state.py:245-262` `add-verification` | `st.setdefault("verification_commands",[]).append` | 歸屬 task 或 item 須定 | 是 |
| `.claude/hooks/eval_state.py:265-272` `list-files` | 遍歷 `sub_tasks` 各 `files` 聯集 | 須改為遍歷 task→items→files 兩層 | 是 |
| `.claude/hooks/eval_state.py:304-317` `archive` | `if not state.get("sub_tasks")` 空檢＋`validate_state` | 空檢語義不變；下游 validate 須跟改 | 是（連帶） |
| `.claude/hooks/eval_gates.py:123-133` `validate_state` | 遍歷 `sub_tasks` 逐筆 `status==passed`＋`_validate_credentials` | 憑據驗證對象由 item 變 task 筆；items 未全 passed 時 task 不得 passed（Q5） | 是 |
| `.claude/hooks/eval_gates.py:424-429` `check_task_gate`（code-writer 分支）| 遍歷 `sub_tasks` 查 `risk_analysis.blocking` | 前置 1 已刪（Q1）→ `risk_analysis` 不再寫入；此遍歷可能成死碼（見第 6 節，勿逕刪，屬 §3.5 邊界） | 待裁決 |
| `.claude/hooks/eval_state.py:309-310` `archive` sub_tasks 空檢 | `state.get("sub_tasks")` | 無害（頂層仍是 list） | 否 |
| `.claude/hooks/stats.py:172-221` collect（archive 迴圈）| 遍歷 `archive["sub_tasks"]` 累計 `sub_tasks`／`rework`／`checked_by`／`review_dimensions`／`verification_commands` | 新形狀憑據在 task 層、item 層無 review_reds → 若仍逐 item 累計則分母錯或崩潰 | 是（須同時吃新舊，見 4A 末） |
| `.claude/hooks/devlog.py:96-100` `_subtask_section` | `archive.get("sub_tasks")` 逐筆列 | 顯示層；新形狀須決定印 task 還是展開 items | 是（顯示正確性） |
| `.claude/hooks/run_verify.py:32-55` | `find_subtask(state, args.sub_task)` 寫 verification | `--sub-task` id 現指 item；改構後指 task 或 item 須定 | 是（連帶 find_subtask） |
| `tests/test_eval_gates.py:14-25` `make_sub_task` 工廠 | 產 per-item skeleton | 新舊分界；決定產新形狀或新增 make_task | 是 |
| `tests/test_eval_gates.py:29-30,85,100,404,1292-1315` | 用 `make_sub_task`／內聯 sub_task 建 state/archive | 隨工廠同動 | 是 |
| `tests/test_eval_state.py:41-374`（多處）| `add-subtask`＋`read_state()["sub_tasks"][0]` 斷言各欄 | 斷言路徑由 `[0][key]` 變 `[0]["items"][0][key]` 或 task 層 | 是 |
| `tests/test_stats.py:38-274`（多處）| 內聯 `sub_tasks` fixture（新舊 review_reds/rounds/checked_by/dims）| 須新增 per-task 形狀 fixture 坐實「同時吃新舊」 | 是 |
| `tests/test_run_verify.py:81-84` | `read_state()["sub_tasks"][0]` 斷言 verification | 隨 run_verify 定位改動 | 是 |
| `tests/test_devlog.py`（sub_tasks fixture）| archive fixture | 隨 devlog 顯示改動 | 是 |
| `run/*.eval.json`（**19 份**歸檔檔）| 舊 per-item flat 形狀（`['id','name','status','step','files','warning','local_test_passed','local_test_evidence','risk_analysis','rounds','review_reds','verify_passed']`）| `stats.py` 掃全部歸檔——舊檔無 `items` 鍵，新檔 review_reds 在 task 層 → 兩形狀並存 | stats.py 須雙吃（不改歸檔檔，§3.5） |

**4A 沿用既有寫法建議**：`stats.py` 的雙吃沿 `:177-184` legacy fallback 範式（先試 task 層 items 累計、無 items 鍵則退回舊 flat 逐筆），符合硬性要求 3。

**4A 查詢方法**：`grep -rn "sub_tasks\|find_subtask\|sub-task\|add-subtask" .claude/hooks/ tests/` → hooks 命中 5 檔（eval_state.py、eval_gates.py、stats.py、devlog.py、run_verify.py），tests 命中 5 檔（test_eval_gates／test_eval_state／test_stats／test_run_verify／test_devlog）；`ls run/*.eval.json | wc -l` → 19；`python3 -c "..."` 取首檔 sub_task 鍵集確認 flat 形狀。

### 4B. `PHASES` 值域收斂 5→3（§3.2）

現行 `PHASES = ["init","risk_done","usage_confirmed","decomposed","completed"]`（`eval_gates.py:61`）。變更後 `["init","decomposed","completed"]`。

| 檔案:行號 | 讀取什麼 | 結構變更後的後果 | 是否必改 |
|---|---|---|---|
| `.claude/hooks/eval_gates.py:61` `PHASES` 定義 | 值域清單 | 移除 risk_done／usage_confirmed 兩值 | 是 |
| `.claude/hooks/eval_gates.py:62-67` `AGENT_MIN_PHASE` | usage-analyzer=risk_done、impact-analyzer/task-decomposer=usage_confirmed、code-writer=decomposed | §3.2：三 advisor 改 init、code-writer 維持 decomposed | 是 |
| `.claude/hooks/eval_gates.py:181-182` `manifest_phase`（顯式值分支）| `if phase in PHASES: return phase` | 舊 manifest 顯式 phase=risk_done/usage_confirmed 不再 in PHASES → 落入推導 | 是（映射邏輯） |
| `.claude/hooks/eval_gates.py:185-186` `manifest_phase`（推導分支）| `if usage_report_path: return "usage_confirmed"` | **回傳值本身不在新 PHASES** → 下游 `:408` index 拋 ValueError | 是（此分支回傳值必改為 init 或 decomposed，易漏） |
| `.claude/hooks/eval_gates.py:407-408` `check_task_gate` | `PHASES.index(phase) < PHASES.index(required)` | 唯一 index 消費點；映射須先於此發生（usage 假設 2、DoD 2） | 是（連帶，映射修好即安全） |
| `.claude/hooks/eval_gates.py:414-419` task-decomposer 分支 | 讀 `usage_report_path` 空/skipped 擋人 | §3.2 末：兩條擋人判定隨前置 2 降級移除 | 是 |
| `.claude/hooks/session_start.py:48-52` | `manifest.get("phase")` 純字串顯示 | 無 index，舊值仍可印，無害 | 否 |
| `tests/test_eval_gates.py:115` `manifest_phase({"phase":"risk_done"})` 期望回 risk_done | 顯式值直回 | 映射後應回 init → 斷言須改（DoD 2） | 是 |
| `tests/test_eval_gates.py:120-122` `manifest_phase({"usage_report_path":...})` 期望 usage_confirmed | 推導回 usage_confirmed | 映射後應回 init → 斷言須改 | 是 |
| `tests/test_eval_gates.py:129` `manifest_phase({"phase":"bogus"})` 期望 init | 未知值落推導 | 行為不變；可作 risk_done/usage_confirmed 映射的坐實模板 | 沿用/新增 |
| `tests/test_eval_gates.py:133-136` parent_run_id 不影響 risk_done | phase=risk_done 期望原樣 | 隨 4B 映射改斷言 | 是 |
| `tests/test_eval_gates.py:254-278` `_write_state_and_manifest`＋impact-analyzer gate 測試（`test_phase_below_usage_confirmed_blocks` 用 risk_done 擋、`test_phase_usage_confirmed_passes` 用 usage_confirmed 放行）| AGENT_MIN_PHASE 舊語義 | impact-analyzer 改 init → 這兩測整體重寫（新語義：init 即放行） | 是 |
| `tests/test_session_start.py:191,240` fixture `phase="risk_done"` | 任意字串 fixture | session_start 不驗 phase，功能不壞；為潔淨可改 init | 否（建議改） |
| `run/*.json`（56 份 manifest，現況 phase 分佈：completed×45、decomposed×10、usage_confirmed×1）| 舊 phase 值 | completed/decomposed ∈ 新值域（H-err2 雙向相容成立）；usage_confirmed×1＝本 run，risk_done×0——實際遷移面極小，但測試須坐實 risk_done/usage_confirmed 可映射（DoD 2） | 不改檔，靠映射＋測試 |

**4B 查詢方法**：`grep -rn "PHASES\|AGENT_MIN_PHASE\|manifest_phase\|risk_done\|usage_confirmed\|\.index(" .claude/hooks/` → 唯一 `PHASES.index` 在 eval_gates.py:408；`grep -rn "risk_done\|usage_confirmed\|PHASES\|manifest_phase" tests/` → test_eval_gates（8 處）、test_session_start（2 處）。`python3` 掃 56 manifest 得 phase 分佈。

### 4C. `usage_report_path`／`impact_report_path` 語義：改長期 null（D2、Q3）

兩 advisor 改具名問題觸發、不再產報告檔，兩欄長期 null。以下為把「非空」當前置完成信號的判定式：

| 檔案:行號 | 把非空當什麼信號 | 變更後後果 | 是否必改 |
|---|---|---|---|
| `.claude/hooks/eval_gates.py:185-186` `manifest_phase` | `usage_report_path` 非空 → 推導 usage_confirmed | 前置 2 降級後此推導誤判 phase（且回傳值離開值域，見 4B） | 是 |
| `.claude/hooks/eval_gates.py:414-419` task-decomposer 分支 | 空/skipped → 擋分拆 | §3.2 末移除兩條擋人 | 是 |
| `skills/usage-scenario-analysis/SKILL.md:22-23` | 「未確認前 usage_report_path 維持 null，不可進分拆」 | 改具名問題觸發、答案寫 Spec；此 HITL gate 條文改掛 Spec 裁示 | 是 |
| `skills/task-decomposition/SKILL.md:15` | 「usage_report_path 為 null 代表 usage 未完成，直接中止」 | 中止判定移除 | 是 |
| `skills/eval-flow/references/gates.md:29` | task-decomposer 需 phase>=usage_confirmed 且 usage_report_path 非空 | 條文移除（值域與 gate 均變） | 是 |
| `skills/eval-flow/references/formats.md:54-55` | 定義兩欄「null→不可分拆」語義 | 改為「具名問題觸發，長期 null 屬正常」 | 是 |
| `skills/eval-flow/references/formats.md:41,136` | 「usage_report_path 為 null 時不可分拆」/ 向後相容推導 | 同上；formats.md:41 的推導條文須與 4B manifest_phase 改動一致 | 是 |
| `skills/eval-flow/SKILL.md:52,57-58,60,65,179` | 前置 2/2.5「報告產出→確認→回寫路徑」gate、防跳過檢查 impact_report_path 非 null | 前置 2/2.5 改具名問題觸發（§3.1）；防跳過 gate 移除 | 是 |
| `skills/eval-flow-resume/SKILL.md:24-25,29` | 依 usage/<run_id>.md 是否存在判 HITL 卡點、依 impact_report_path 判前置 2.5、向後相容推導 | Q4：改依 task_file／hitl_confirmed_at 定位 | 是 |
| `.claude/agents/usage-analyzer.md:42,44` | 確認後才寫 usage_report_path、更新 phase=usage_confirmed | 改具名問題觸發、答案寫 Spec、不回寫路徑、phase 不再設 usage_confirmed | 是 |
| `.claude/agents/impact-analyzer.md:3,17,31,74`（本檔）| 讀 usage_report_path、產報告、回寫 impact_report_path | 改具名問題觸發、答案寫 Spec、不回寫 | 是 |
| `.claude/agents/task-decomposer.md:3,22-24` | 讀 usage_report_path、null→中止、讀 impact_report_path 對映 | null→中止判定移除；改條件派工 | 是 |
| `.claude/hooks/devlog.py:87-88` | 印 usage_report_path／impact_report_path | 純顯示，null 有 `_na` 兜底（`:77`），無害 | 否 |
| `tests/test_eval_gates.py:122` | `manifest_phase({"usage_report_path":...})` 期望 usage_confirmed | 隨 4B/4C 改斷言 | 是 |
| `tests/test_devlog.py:46-48` | fixture 填三 report_path | 顯示測試，可保留或改 | 否（建議對齊） |
| `skills/eval-flow/references/rare-paths.md:12,22,25`、`skills/parallel-run/SKILL.md:50`、`skills/eval-flow/SKILL.md:215` | Tier B/hotfix/parallel/Tier 1 固定填 skipped/deferred | 屬 §3.5 排除路徑（Tier 0/B/hotfix/parallel），**不動**——僅列為完整性參考 | 否（排除項） |

**4C 查詢方法**：`grep -rn "usage_report_path\|impact_report_path\|risk_report_path" skills/ .claude/agents/ .claude/hooks/ tests/` → 命中 skills 7 檔、agents 3 檔、hooks 2 檔（eval_gates、devlog）、tests 2 檔（test_eval_gates、test_devlog）。risk_report_path 一併列出以區分（前置 1 刪除另屬 §3.1，非本欄語義變更）。

### 4D. 三個被刪機制的殘留投放路徑（D1、DoD 4）

DoD 4：`grep -rn "mine_log\|批前快照\|review-st"` 於 skills/、.claude/agents/、.claude/hooks/ 僅剩刻意保留的歷史說明。

| 機制 | 檔案:行號 | 屬性（落檔 vs 自驗本體）| 處置 | 是否必改 |
|---|---|---|---|
| mine_log | `.claude/hooks/test_baseline.py:335-365` `_append_mine_log` | **落檔本體**（寫 run/<run_id>.mine_log.json） | 刪函式 | 是 |
| mine_log | `.claude/hooks/test_baseline.py:381-382` `cmd_mine` 內 `seq=_append_mine_log(...)`＋`seq_note` | **落檔呼叫點**（耦合在自驗流程） | 移除呼叫與 seq_note；**保留 `:368-391` cmd_mine 其餘**（git_changed_files→is_test_file→build_mine_argv→run_tests_argv→PASS/BLOCK 判定＝mine 自驗本體，D1 明留） | 是（僅刪 381-382 兩行相關） |
| mine_log | `tests/test_test_baseline.py:513` | 斷言 mine_log.json 內容 | 刪該斷言 | 是 |
| mine_log | `skills/eval-flow/SKILL.md:91,98,107,150` | 交付稽核②、checker 輸入⑥、升級③、收尾清檔 | 刪條文（含收尾清檔清單移除 mine_log 項） | 是 |
| mine_log | `skills/test-strategy/SKILL.md:39` | 「執行留痕（震盪稽核）append run/<run_id>.mine_log.json」 | 刪；保留 mine 模式測試自驗敘述 | 是 |
| mine_log | `.claude/agents/task-verifier.md:22,42,66` | checker 輸入⑤、對照 mine_log 摘要、升級③ | 刪（含輸入清單第 5 項與升級碼③） | 是 |
| mine_log | `.claude/agents/code-writer.md:45,48` | 上限稽核靠 mine_log 指紋、sabotage 自檢的 mine_log 軌跡 | 刪「留痕/稽核」措辭；**保留 mine 執行與 2 次上限自數、sabotage 自檢本體**（D1 留自驗） | 是（區分落檔 vs 自驗，勿誤刪自檢程序） |
| 批前快照 | `skills/eval-flow/SKILL.md:97` | 「批前快照（跨批污染的行數修法）」 | 刪（審查 per-task 後跨批污染成因消失，§3.4） | 是 |
| 批前快照 | `skills/eval-flow/SKILL.md:98,173` | checker 輸入集含批前快照 | 刪輸入項 | 是 |
| 批前快照 | `.claude/agents/task-verifier.md:23,25` | 輸入第 6 項＝批前快照、缺席觸發升級① | 刪第 6 項與對應缺席判定 | 是 |
| 批前快照 | `.claude/agents/task-verifier.md:16,20,32,34,36,48,55,74-96,120` | **常規 `git diff --cached --stat` 輸入（≠批前快照）** | **保留**——§3.4 只刪「批前 `--stat` 快照」，checker 的常規 `--stat` 輸入（輸入第 3 項）不刪 | 否（勿誤刪常規 --stat） |
| 批前快照 | `skills/eval-flow/SKILL.md:93,100,186` | 常規 `--stat` 派 checker/進度憑據 | 保留（常規 --stat） | 否 |
| 審查落檔 | `skills/eval-flow/SKILL.md:112` | 「審查報告 write-ahead（硬性）落檔 review-st<id>-r<N>.md」 | 刪（改記 review_reds/checked_by，§3.4） | 是 |
| 審查落檔 | `skills/eval-flow/SKILL.md:122,135,136` | 駁回/🟡/scope 依據「記入審查落檔的主 flow 處置行」 | 改措辭：處置改記 eval_state/收尾回報，不落檔 | 是 |
| 審查落檔 | `skills/eval-flow/SKILL.md:130,150` | fixing 迴圈落檔、收尾清 review-st*-r*.md | 刪落檔動作與清檔項 | 是 |
| 審查落檔 | `skills/eval-flow/SKILL.md:218,236` | Tier 1 事件留痕點提及「每 item 審查落檔後」 | 改措辭（每 task；不落檔） | 是 |
| 審查落檔 | `skills/eval-flow-resume/SKILL.md:43-45,50` | reviewing/fixing/verifying 恢復靠 review-st 落檔對賬、輪數接續 | Q6：改「一律重跑該輪、重派 checker、輪數讀 review_reds」，明載兩條已知缺陷 | 是 |

**mine_log 落檔 vs 自驗本體的分界（硬性）**：`test_baseline.py` 的 mine 自驗本體＝`cmd_mine`（`:368-391`）除 `:381-382` 落檔呼叫外的全部；`_append_mine_log`（`:335-365`）＝純落檔，整函式刪。code-writer 的 mine 執行、2 次上限自數、sabotage 自檢程序＝自驗，保留；只刪「留痕/稽核」相關措辭。

**4D 查詢方法**：`grep -rn "mine_log" skills/ .claude/agents/ .claude/hooks/ tests/` → eval-flow(4)、test-strategy(1)、task-verifier(3)、code-writer(2)、test_baseline.py(3: 335/338/381)、test_test_baseline.py(1: 513)。`grep -rn "review-st\|write-ahead" skills/ .claude/agents/` → eval-flow(6)、eval-flow-resume(4)。`grep -rn "批前快照\|--stat" skills/ .claude/agents/` → eval-flow(6)、task-verifier(多，含常規 --stat)、parallel-run(1: `git log --stat`，屬排除路徑)。

---

## 5. 跨模組風險點

- **`manifest_phase` 推導分支回傳離域值（4B `:185-186`）** — 即使顯式值分支改對，`usage_report_path` 非空的推導仍會 `return "usage_confirmed"`，該值不在新 PHASES → `:408` index 拋 ValueError → hook exit 非 2 → gate 靜默失效（R-005 同型，usage 假設 2）。建議確認方式：DoD 2 測試除顯式 phase 外，須加「有 usage_report_path 但無 phase 欄」的舊 manifest 案例，斷言映射為 init 不拋例外。
- **`stats.py` 新舊 sub_task 形狀混掃崩潰（4A 末、K 情境）** — 19 份舊歸檔為 flat per-item，新歸檔為 task+items 巢狀；若累計邏輯只認一種，另一種缺鍵時 KeyError 或分母失真。建議確認方式：新增 per-task fixture 測試（test_stats.py），斷言新舊並存時 `sub_tasks`/`rework`/`checked_by` 皆不崩且分母語義正確；收尾回報註明 2026-09-22 統計斷點。
- **`check_task_gate` 的 `risk_analysis.blocking` 遍歷成孤兒（4A `eval_gates.py:424-429`）** — 前置 1 刪除（Q1）後 `risk_analysis` 不再寫入，此遍歷恆 false。逕刪屬 §3.5「commit gate 定位邏輯」邊緣、且動 gate 判定行為 → 列入第 6 節待裁決，勿順手刪。
- **審查落檔刪除後恢復能力下降（Q6，D-err2）** — 中斷在升級 reviewer 輪時恢復誤降回 checker、2 輪上限計數可能歸零。已裁示接受，`eval-flow-resume/SKILL.md` 須明文記兩缺陷。建議確認方式：resume skill 條文審查（非測試可攔），確認兩條缺陷已白紙黑字。
- **循環條文寫在 Tier 1/2 共用段（I 情境）** — per-task 審查/測試若寫在 `eval-flow/SKILL.md` 共用循環段，Tier 1 精簡路徑一併適用，須確認不破壞 Tier 1「單 item task 照舊」（`eval-flow/SKILL.md:73`）與 Tier 1 四欄憑據（`eval_gates.py:169-171`）。建議確認方式：改條文時標明適用 tier；跑 Tier 1 相關 gate 測試。
- **events 節點收斂與 `_events_summary` 對齊（F-err1、Q7）** — Q7 已裁示自動附掛事件保留不動；但若誤把 `set-step` 類事件也收斂，`stats.py:92-97` reentry 恆 0。建議確認方式：確認 `eval_state.py` 各子命令 `append_event` 呼叫（`:139,147,155,...`）不被本次改動移除；D1 收斂只針對「Tier 1 主 flow 手動 event」。
- **`token_usage.py --write` 單一枚舉點（R-007、DoD 7）** — 記帳收斂不得移動收尾 `git add` 枚舉點（`eval-flow/SKILL.md` step 6 ②）。建議確認方式：改收尾條文後 grep 確認 `git add` 處置仍只在該子項；跑 `test_docs_consistency.py`。
- **`test_docs_consistency.py` 引用完整性（DoD 3）** — 刪 mine_log/review-st 條文時若刪到 skill/hook script 引用（`tests/test_docs_consistency.py:23-40` 檢查引用的 hook script 與 skill 存在），會斷。建議確認方式：刪條文後跑 test_docs_consistency；勿刪到 `.claude/hooks/*.py`／`skills/*/SKILL.md` 的存在性引用。

---

## 6. 需使用者裁決的 scope 問題（§3.5 排除項疑觸）

以下項若必動會逾越 Spec §3.5 排除清單，列此供裁決，**不逕自納入**：

1. **`eval_gates.py:424-429` 的 `risk_analysis.blocking` 遍歷**：前置 1 刪除（Q1）後此 gate 判定恆 false，成死碼。刪除會動到 commit/subagent gate 的判定行為，觸 §3.5「不動 commit gate 定位邏輯」邊緣，且屬信任邊界機制本體行。建議：本次**保留不動**（無害的恆 false 分支），或由使用者裁示可否清理。CLAUDE.md「發現孤兒程式碼先提報、不逕刪」亦指向保留。

2. **`set-step`/`set-files`/`add-verification` 的粒度歸屬（item 或 task）**：§5 Q2 只裁示 `sub_tasks` 頂層改 per-task，未明定 writing/testing/verification 這些欄位落 item 層還是 task 層。§3.3 只說審查與測試改 per-task。此為結構改構的實作細節，建議由 task-decomposer 依 Q2 結構定案；若涉及 `--sub-task` CLI 語義（`run_verify.py`）對外契約，須確認。

---

Self-check: 四個被改介面（4A sub_tasks 結構、4B PHASES 值域、4C 兩 report_path 語義、4D 三刪機制）已用 grep -n 現查行號窮舉呼叫端並附可重跑查詢方法，區分 mine_log 落檔(`test_baseline.py:335-365,381-382`)與自驗本體、批前快照與常規 --stat，未逾 §3.5 排除項（疑觸兩項另列第 6 節待裁決）。
