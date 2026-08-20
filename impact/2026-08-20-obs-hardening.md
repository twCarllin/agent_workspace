# 影響面盤點：2026-08-20-obs-hardening

- Spec：`spec/2026-08-20-obs-hardening.md`
- 使用情境報告：`usage/2026-08-20-obs-hardening.md`
- 風險報告：`risk/2026-08-20-obs-hardening.md`
- 盤點日期：2026-08-20（前置 2.5，impact-analyzer）
- 觸及 codebase：本框架 repo 自身（非全新模組，非無呼叫端 → 不適用跳過條件）

> 本 run 為框架自我改造，四項變更（failure 留痕、事件日誌、死檔清理、SessionStart hook）分散在 hook 腳本、部署腳本、settings、skill 文件、測試。所有 file:line 已於本次盤點親掃核對。

---

## 1. 觸及模組清單

- `.claude/hooks/eval_gates.py` — 項目 1b 防刪除 gate、1d 窄例外放行 gate 落點；重用 `MANIFEST_RE`（:42）與 `check_other_runs`（:184）判定
- `.claude/hooks/eval_state.py` — 項目 2a 事件 append 落點（每個寫入子命令成功後 append 一行到 `run/<run_id>.events.jsonl`）
- `.claude/hooks/stats.py` — 項目 1c（status 分佈計入 aborted）、2c（events 指標＋set-step 重入）消費端
- `.claude/hooks/doctor.py` — 項目 3c（`list_skills` 排除 `_deprecated`）、4b（新增 `--brief` 旗標）
- `.claude/hooks/session_start.py` — 項目 4a 全新檔案（SessionStart hook script）
- `.claude/settings.json` — 項目 4c 新增 SessionStart 事件註冊
- `init.sh` — 項目 4c（第 4 步 settings 合併擴充為兩事件）、3c（第 5 步 skills 同步排除 `_deprecated`）
- `.gitignore` — 項目 2d 移除 `run/gate_hits.log`（:5）納入版控
- `skills/eval-flow/SKILL.md` — 項目 1a（manifest status 枚舉加 aborted、失敗留痕規則）、2b（step 6 ②清單補 events.jsonl）、1b/1d（gate 清單同步）文件同步面
- `skills/eval-flow-resume/SKILL.md` — 項目 1a aborted 語義消費者（不得自動 resume）
- `tests/test_eval_gates.py` — 1b/1d 新 gate 正反向測試落點（既有 711 行全綠為 baseline）
- `tests/test_eval_state.py` — 2a append 行為測試落點
- `tests/test_stats.py` — 1c/2c 新指標與 aborted 分佈測試落點
- `tests/test_doctor.py` — 3c/4b `--brief` 與 `_deprecated` 排除測試落點
- `tests/test_docs_consistency.py` — gate 編號與文件一致性守門（新增 gate 觸發重編號 → 此測試變紅）
- `tests/check_worktree_isolation.sh` — 項目 3b 待刪除檔
- `scout/`、`subagents_record/` — 項目 3a 待刪除目錄
- `skills/_deprecated/` — 項目 3c 排除對象（repo 保留、只排除部署與健檢，不刪除）
- `.claude/agents/session_start` 無此檔（hook script 非 agent，不涉 `.claude/agents/`）

---

## 2. 各模組既有慣例

### `.claude/hooks/eval_gates.py`（1b／1d gate）
- **命名慣例**：模組常數用全大寫 regex（`MANIFEST_RE` :42、`GIT_COMMIT_RE` :19、`TEST_FILE_NAME_RE` :46）；函式用 snake_case 動詞（`check_manifest` :125、`check_other_runs` :184、`load_json` :86）；內部 helper 前綴底線（`_validate_credentials` :94、`_resolve_root` :329、`_git_toplevel` :308）
- **錯誤處理慣例**：擋 commit 一律呼叫 `block(msg)`（:78-83），內部 `print(..., file=sys.stderr)` 後 `sys.exit(2)`；放行走 `sys.exit(0)`；錯誤訊息帶「→ 補救：」指示句（如 :98、:160-161）；gate 命中時 `block` 內自動呼叫 `log_gate_hit`（:80）寫 `run/gate_hits.log`
- **單一判定點鐵律**：`MANIFEST_RE`（:39-41 註解明訂）是「以檔名識別 manifest 身分」的唯一判定點，禁止在呼叫點用 `endswith`／`startswith` 補丁繞過——1b/1d 新 gate 判定「staged 是否為 manifest／恰一個 manifest」必須重用此 pattern（風險報告資料#、usage 正確性假設 4）
- **JSON 讀取**：擋型用 `load_json`（:86，失敗即 block）；靜默型用 `load_json_quiet`（:176，失敗回 None，掃他人 manifest 時用）
- **測試慣例**：`tests/test_eval_gates.py` 用 `unittest.TestCase` 子類分群（`ValidateStateTest` :28、`ManifestRegexTest` :145、`GateHitLogTest` :182、`RunHookWorktreeRootTest` :513 等 11 類）；`RunHookWorktreeRootTest`（:513）以 `subprocess.run([sys.executable, <eval_gates.py>, "--hook"], input=<payload json>)` 跑真實 hook 路徑（端到端）；`GateHitLogTest`（:182-220）示範 `run/gate_hits.log` 讀寫斷言樣板

### `.claude/hooks/eval_state.py`（2a event append）
- **命名慣例**：子命令函式 `cmd_<動詞>_<名詞>`（`cmd_set_step` :87、`cmd_add_verification` :169）；`argparse` 子命令用 kebab-case（`add-subtask`、`set-step`，:218-268）；狀態常數大寫（`STEPS` :32、`STATUSES` :33、`VALID_DIMENSIONS` :127）
- **寫入慣例**：所有寫入子命令走 `save(state)`（:51-54，`json.dump(indent=2, ensure_ascii=False)` ＋尾隨換行）；讀取走 `load()`（:41-49，`FileNotFoundError`／`JSONDecodeError` 各自 `fail`）
- **錯誤處理慣例**：使用錯誤呼叫 `fail(msg, code=1)`（:36-38，stderr 印 `[eval-state]` 前綴）；驗證不過 `code=2`（:138、:199、:202）
- **向後相容慣例**：可選新欄位以 `st.setdefault(...)` 補齊再操作（`cmd_add_verification` :177，示範「舊 eval_state.json 無此鍵」處理）——2a 的 events append 對舊檔缺 run_id 的處置（D-err2）可沿用此防禦風格
- **測試慣例**：`tests/test_eval_state.py`（219 行）以 `run_cli(...)` helper 跑子命令、斷言 state 檔內容（`test_add_verification_appends_in_order` :174、`test_add_verification_backward_compat_missing_key` :204 是 append 累積與相容的樣板）

### `.claude/hooks/stats.py`（1c／2c consumer）
- **命名慣例**：`collect(run_dir)`（:44）回傳單一 `data` dict、`report(data)`（:149）純格式化、`main`（:185）串接；聚合用 `collections.Counter`（:52 `statuses`/`tiers`/`gate_hits`）
- **缺欄慣例**：欄位缺漏一律顯示 n/a／「無記錄」**不猜**（模組 docstring :23、`pct` :136 `d==0 → n/a`、驗證指令數區分「鍵不存在＝無記錄」vs「空陣列＝0 條」:71-73）——2c 的「無 events 檔的舊 run 顯示無記錄」（E-edge1）須遵此
- **status 計數**：`data["statuses"][str(m.get("status"))] += 1`（:63）用 `Counter` 無寫死枚舉 → `aborted` 自動計入（證實 Spec 1c「若寫死則放開」前提不成立，僅需加斷言）
- **測試慣例**：`tests/test_stats.py`（235 行）建臨時 `run_dir`＋寫假 manifest／gate_hits.log 後呼叫 `collect`／`report`（`test_gate_hits_grouped` :79、`test_gate_hits_shown_even_with_zero_runs` :96 為樣板）

### `.claude/hooks/doctor.py`（3c／4b）
- **命名慣例**：檢查常數大寫（`HOOKS` :21、`CORE_SKILLS` :22）；巢狀 helper `list_skills`（:43）、`dirs_equal`（:46）；dotfile 排除集中在 `_non_dotfile`（:25-27）
- **輸出慣例**：`ok`／`issues` 兩個 list 累積，尾端統一印（:151-158）；OK 走 stdout `[doctor] OK:`、ISSUE 走 stderr `[doctor] ISSUE:`；有 issue → `sys.exit(1)`
- **關鍵缺口**：`main()`（:89）目前**無 argparse**、不吃任何參數——4b 的 `--brief` 需新增參數解析（不可假設既有已支援）
- **測試慣例**：`tests/test_doctor.py`（106 行）**只測 `check_skills_sync`（import 函式直呼）**，未測 `main()`／CLI；4b `--brief` 若走 `main()`／CLI 需新建 subprocess 或重構出可測函式

### `init.sh`（3c／4c）
- **慣例**：分 6 步、各步 `echo "[N/6] ..."`；`set -euo pipefail`（:2）→ 任何非零中斷（cp 撞目錄會炸，故 step 3 用 `-type f` 過濾 :43）；settings 合併用 heredoc 內嵌 Python（`PYEOF` :58-75）「無則複製、有則合併、冪等（`if entry not in entries`）不動其他鍵」
- **skills 同步**：step 5（:86）`for skill_path in "$SRC_SKILLS"/*/` 單層迴圈、`cp -Rf`「只覆蓋不刪除」（:91）——3c 排除 `_deprecated` 須在此迴圈加判斷，維持「不刪除目標端既有」語義

### skill 文件
- **manifest 格式節**：`skills/eval-flow/SKILL.md` status 枚舉 doc 在 :144（`"in_progress | completed | failed"`）、`failed_reason` 說明 :166、`scout_report_path` 已廢止註 :161；1a 須在 :144 加 `aborted`、在 failed_reason 說明擴及 aborted、明文「aborted／failed 永不清除」
- **step 6 ②清單**：`skills/eval-flow/SKILL.md:94`（收尾 `git add` 檔案枚舉，是單一枚舉點，Tier 1／fan-out 皆指向它）——2b 補 events.jsonl 須改此處
- **gate 清單**：`skills/eval-flow/SKILL.md:234-243`（gate 1–5 commit ＋ gate 6 subagent，編號連續）

---

## 3. 可重用既有元件（防重複造輪）

- `.claude/hooks/eval_gates.py:42` `MANIFEST_RE` — 1b 防刪除 gate 判定「刪除的是不是 manifest」、1d 窄例外判定「staged 恰一個 manifest」、4a SessionStart 掃殘留 in_progress manifest 皆須重用（含 `.eval`／`.test_baseline` 負向排除）；**注意**：此版錨定 `^run/...\.json$`（含 `run/` 前綴）
- `.claude/hooks/stats.py:33` `MANIFEST_RE` — 同 pattern 的**第二份**，但錨定 basename（`^<run_id>...\.json$`，無 `run/` 前綴）；4a session_start.py 若掃 `run/*.json` 取 basename 比對可仿此版——兩份差在前綴錨定，跨檔重用時須選對（見第 5 節風險）
- `.claude/hooks/eval_gates.py:64` `log_gate_hit(msg)` — 1b/1d 新 gate 被擋時，`block()`（:78）已自動記 `run/gate_hits.log`，新 gate 走 `block` 即免費獲得遙測
- `.claude/hooks/eval_gates.py:78` `block(msg)` — 統一擋 commit 出口（印 stderr＋log＋exit 2），新 gate 直接呼叫
- `.claude/hooks/eval_gates.py:176` `load_json_quiet(path)` — 掃他人 manifest（4a 殘留偵測、遍歷 run/*.json）用的靜默讀取，失敗回 None 不炸
- `.claude/hooks/eval_gates.py:184` `check_other_runs` — 既有「掃 run/*.json 判 in_progress」樣板，4a 殘留偵測邏輯可參考其 glob＋MANIFEST_RE 過濾寫法（:186-187）
- `.claude/hooks/eval_gates.py:385-392` `git diff --cached --name-only` 取 staged 集合 — 1d 窄例外判定「staged 檔案集合」直接複用既有 subprocess 呼叫；1b 另需 `--diff-filter=D`（Spec 1b 指定，codebase 尚無此用法，屬新增）
- `.claude/hooks/eval_state.py:51` `save(state, path)` — 2a append 前的主寫入已走此函式，append 掛在其成功之後（旁路）
- `.claude/hooks/eval_state.py:177` `st.setdefault(...)` 相容樣板 — 2a 對舊檔／缺鍵的防禦寫法可仿
- `.claude/hooks/stats.py:136` `pct(n, d)` — 2c 若要輸出比率型指標可複用（`d==0 → n/a`）
- `.claude/hooks/doctor.py:25` `_non_dotfile` / `:43` `list_skills` — 3c 排除 `_deprecated` 直接改 `list_skills` 的集合推導；此為 repo↔部署比對的唯一 skill 列舉點
- `tests/test_eval_gates.py:513` `RunHookWorktreeRootTest` — 3b 刪除 `check_worktree_isolation.sh` 的等價端到端覆蓋（DoD 斷言前提，已確認存在）；亦是 1b/1d 新 gate 端到端測試（subprocess 跑 `--hook`）的樣板
- `tests/test_eval_gates.py:182` `GateHitLogTest` — 新 gate 的 gate_hits 斷言樣板
- `tests/test_stats.py:79`／`:96` gate_hits 測試 — 1c/2c 新指標測試樣板
- `tests/test_eval_state.py:174` `test_add_verification_appends_in_order` — 2a events append 累積／保序測試樣板

---

## 4. 被改介面的呼叫端清單

> Grep 全從 repo 根目錄執行，排除 `.claude/worktrees/` 與歷史產出目錄（run/spec/usage/risk/impact/task/scout/subagents_record）的非程式碼命中。

### 介面 A：manifest `status` 枚舉新增 `aborted`（項目 1a）
消費「status 值」的所有落點（風險報告業務#2、usage 正確性假設 3 的三消費點＋額外第四點）：
- `.claude/hooks/eval_gates.py:131` — `check_manifest`：`status != "completed" → block`（commit gate；aborted 走 1d 窄例外放行）
- `.claude/hooks/eval_gates.py:198` — `check_other_runs`：`status == "in_progress"` 才擋新 run；aborted **必須非 in_progress**（不擋新 run）【風險業務#2 消費點一】
- `.claude/hooks/eval_gates.py:242` — `_find_unique_tier1_inprogress`：`tier==1 and status=="in_progress"`；aborted 的 tier-1 run 不得被選為當前 run（**風險報告未點名的第四消費點，須一併斷言**）
- `.claude/hooks/stats.py:63` — `data["statuses"][str(m.get("status"))]`：`Counter` 自動計入 aborted（1c，加斷言即可）【消費點二】
- `skills/eval-flow-resume/SKILL.md:12` — Step 1「掃 in_progress 的 manifest」恢復；aborted 不得被列入自動恢復候選【消費點三】
- `skills/eval-flow-resume/SKILL.md:56` — 「`status: failed` 不自動恢復」規則；aborted 須加入同待遇（明文擴充）
- `skills/eval-flow/SKILL.md:144` — status 枚舉文件（加 aborted）
- `skills/eval-flow/SKILL.md:165`／`:166` — status／failed_reason 說明（擴及 aborted）
- `skills/eval-flow/SKILL.md:226` — 「有任一 failed → manifest status: failed＋failed_reason」既有規則（與 aborted 區分語義）
- `.claude/hooks/doctor.py` — **不消費 manifest.status**（:141 只檢查 `eval_state.json` 檔案存在，不讀 run/*.json 的 status）；故無須改，但 4a SessionStart 補的正是 doctor 不做的「掃 run/*.json 找 in_progress manifest」（開放問題 4 分工）
- **查詢方法**：`grep -rn "in_progress\|== \"completed\"\|get(\"status\")\|\"status\"" .claude/hooks/*.py skills/*/SKILL.md` → 命中上列；`grep -rn "aborted" .claude/hooks/ skills/ tests/ init.sh` → **0 命中**（aborted 為全新枚舉值，尚無任何消費端，故上列為需新增／確認的完整落點）

### 介面 B：`eval_state.py` 寫入子命令（項目 2a event append）
2a 要求每個寫入子命令成功後 append 事件。被橫切的子命令與其分派點（回歸面最廣）：
- `.claude/hooks/eval_state.py:64/71/87/94/101/117/130/162/169/195` — `cmd_init`／`cmd_add_subtask`／`cmd_set_step`／`cmd_set_files`／`cmd_set_test`／`cmd_set_status`／`cmd_set_review`／`cmd_set_verify`／`cmd_add_verification`／`cmd_archive`（10 個寫入命令，皆呼叫 `save()`）
- `.claude/hooks/eval_state.py:185` — `cmd_list_files`（唯讀，**不 append**，D-edge2）
- `.claude/hooks/eval_state.py:210-271` — `main()` 的 `add_parser` 分派（append 若集中在 dispatch 層 vs 各 cmd 內，是實作決策點）
- `skills/eval-flow/SKILL.md:215` — 子命令清單文件（`tests/test_docs_consistency.py:64` `HelperSubcommandDocsTest` 斷言此清單與 `add_parser` 一致；2a 不新增子命令 → 此測試不受影響，但若順帶改清單須同步）
- 呼叫 helper 的實際來源是主 flow 的 Bash（散在對話／SKILL 指示），非程式碼靜態呼叫
- **查詢方法**：`grep -n "def cmd_\|add_parser" .claude/hooks/eval_state.py` → 上列 10 寫入＋1 唯讀＋分派；`grep -rn "events.jsonl" . --include=*.py --include=*.md --include=*.sh | grep -v worktrees` → 僅 spec/usage 命中，程式碼／測試 **0 命中**（全新產物，無既有消費端）

### 介面 C：gate 編號文件（項目 1b／1d 新增 gate）
新增 commit-phase gate 會改動 gate 清單編號，被文件一致性測試機械稽核：
- `tests/test_docs_consistency.py:78` `GateListConsistencyTest.test_gate_numbering_ranges_match_list`（:79-96）— 用 regex `gate 1–(\d+)）.*?（gate (\d+)–(\d+)）` 抓區間、`^(\d+)\. \*\*` 抓清單最大編號，兩者須相等且連續
- `skills/eval-flow/SKILL.md:234` — 「gate 1–5」宣稱＋:234-243 的 1.-6. 編號清單（新增 gate → 須重編號，subagent gate 從 6 位移）
- `README.md` — 亦被 `GateListConsistencyTest` 掃（:81 迴圈含 `README.md`）；當前 `grep -n "gate 1–" README.md` **0 命中**（README 無此區間宣稱，regex `if not m: continue` :83 跳過 → 不擋），但 SKILL.md 命中 → 改 SKILL 編號時此測試會驗
- **查詢方法**：`grep -rn "gate 1–\|^[0-9]\. \*\*.*gate" skills/eval-flow/SKILL.md README.md`；`grep -n "GateListConsistency\|gate 1–" tests/test_docs_consistency.py`

### 介面 D：`.gitignore` 移除 `run/gate_hits.log`（項目 2d）
- `.gitignore:5` — `run/gate_hits.log`（待移除）
- `.claude/hooks/eval_gates.py:72` — `log_gate_hit` 寫入端（不變）
- `.claude/hooks/stats.py:122` — `gate_hits.log` 讀取端（不變）
- **查詢方法**：`grep -rn "gate_hits" .gitignore .claude/hooks/ tests/` → 上列＋測試（`test_eval_gates.py:202/:220`、`test_stats.py:57/:98`）皆用臨時目錄，不受 .gitignore 改動影響

### 介面 E：`.claude/settings.json` 新增 SessionStart（項目 4c）
- `.claude/settings.json:6-16` — 既有 PreToolUse 區塊（matcher `Bash|Task|Agent` :8 指向 `gate-check.sh` :12）；新增 SessionStart 平行區塊
- `init.sh:63` — 合併 Python 目前**只讀 `src["hooks"]["PreToolUse"]`**（:65 迴圈），須擴充為同時合併 SessionStart（L）；不得破壞既有 PreToolUse（L-err1，破壞＝gate 防線靜默消失）
- `.claude/hooks/doctor.py:116` — `settings.get("hooks", {}).get("PreToolUse", [])` 檢查含 `gate-check`（既有健檢，是 L-err1 的守門，DoD 綁定跑 doctor）
- **查詢方法**：`grep -rn "PreToolUse\|SessionStart\|settings.json\|hooks\[" init.sh .claude/hooks/doctor.py .claude/settings.json` → 上列；`grep -rn "SessionStart" . --include=*.py --include=*.sh --include=*.json | grep -v worktrees` → **0 命中**（全新事件，無既有接線）

### 介面 F：`doctor.py` 新增 `--brief`（項目 4b）
- `.claude/hooks/doctor.py:89` `main()` — **無 argparse**，須新增參數解析
- `.claude/hooks/session_start.py`（新檔）— 4a 內嵌呼叫 `doctor.py --brief`（唯一新消費者）
- `README.md:68`／`:84`、`skills/eval-flow/SKILL.md:154` — 提及 `doctor.py`（純無旗標用法，`--brief` 為新增，不影響既有描述）
- `tests/test_doctor.py` — 只 import `check_skills_sync`（:12），未跑 CLI；`--brief` 測試為新增
- **查詢方法**：`grep -rn "doctor" . --include=*.py --include=*.sh --include=*.md | grep -v worktrees | grep -v "已部署\|CORE_SKILL"` → 上列；`grep -n "brief\|argparse\|sys.argv" .claude/hooks/doctor.py` → **0 命中**（確認須新增）

### 介面 G：死檔刪除的引用面（項目 3a／3b）
- `scout/` — 全 repo 唯一存活引用：`skills/eval-flow/SKILL.md:161`（`scout_report_path` 已廢止相容註，**明文不動**）；其餘命中皆在歷史 run/spec/usage/task/eval.json（冷溯源，不算引用）。目錄實存 `scout/2026-07-25-tier2-p-worktree.md`
- `subagents_record/` — 唯一存活引用：`.claude/agents/task-verifier.md:74`（「完成後寫一句到 subagents_record/」）；task-verifier 已退役（`skills/eval-flow/SKILL.md:75`），此為死引用。目錄實存 `subagents_record/2026-07-16.md`、`2026-07-17.md`
- `tests/check_worktree_isolation.sh` — **無任何程式碼／CI/Makefile 呼叫**（無 `.github`、無 `Makefile`、無 python subprocess 包裝）；存活引用僅 spec/usage/task/eval.json/retro 等文件（BUGLOG :9 記其假綠燈前科、RETRO :9 記約束）。等價覆蓋 `RunHookWorktreeRootTest` 已存在（`tests/test_eval_gates.py:513`）
- **查詢方法**：`grep -rn "scout\|subagents_record\|check_worktree_isolation" . --include=*.py --include=*.sh --include=*.md --include=*.json --include=*.yml --include=*.yaml | grep -v worktrees` → 存活程式碼引用僅 `.claude/agents/task-verifier.md:74`（subagents_record）；scout 與 check_worktree_isolation 在程式碼／CI 端 **0 命中**（僅文件與冷溯源）

### 介面 H：`_deprecated` 排除（項目 3c）
- `.claude/hooks/doctor.py:43` `list_skills` / `:67-71` `repo_only`／`deploy_only`／`common` 比對 — 未排除 `_deprecated` 時，repo 有 `skills/_deprecated/` 而部署層排除後 → `repo_only` 誤報（I 情境）
- `init.sh:86` skills 同步迴圈 — 須排除 `_deprecated`，與 doctor 同步（否則兩端不一致）
- `tests/test_agent_refs.py:16` `SCAN_FILES = glob("skills/*/SKILL.md")` — 單層 glob，`skills/_deprecated/<sub>/SKILL.md` 為**兩層**故本就掃不到（:31 註解確認）；3c 不影響此測試
- `tests/test_doctor.py` — `check_skills_sync` 測試（:42 起），3c 改 `list_skills` 須加/改對應斷言
- `skills/_deprecated/` 實存子目錄：`eval-scoring`、`report-format`、`review-checklist`、`task-checklist`、`task-verify-checklist`（5 個，皆須被排除）
- **查詢方法**：`grep -rn "_deprecated\|list_skills\|repo_only" .claude/hooks/doctor.py init.sh tests/` → 上列；`ls skills/_deprecated/`

---

## 5. 跨模組風險點

- **`MANIFEST_RE` 有兩份、錨定不同** — `eval_gates.py:42` 錨 `^run/...\.json$`（含前綴），`stats.py:33` 錨 basename `^<id>...\.json$`（無前綴）。4a session_start.py 掃殘留 manifest 時須選對版本（掃 `glob("run/*.json")` 取全路徑 → 仿 eval_gates 版；取 basename → 仿 stats 版）。建議確認方式：session_start.py 直接 `import` 重用其一（避免第三份漂移），並在測試斷言歸檔檔（`.eval.json`／`.test_baseline.json`）被負向排除
- **1b/1d 新 gate 與既有 commit gate 共存** — 既有攔截點密集：歸檔 gate（`eval_gates.py:377`）、intent gate（`:129-132`）、測試 gate（`check_manifest`）、check_other_runs（`:184`）。1d 窄例外須「豁免 gate 1（eval_state.json 存在擋 :377）」但不得放寬其他判定；改壞任一 → 擋住所有正常收尾（風險業務#1）。建議確認方式：`tests/test_eval_gates.py` 既有 711 行全綠為 baseline，新 gate 加正反向（刪 manifest 被擋／刪歸檔檔放行 B-edge1／窄例外三條件全滿足放行／混入其他檔不放行 N-err1／status=completed 走原路）
- **事件 append 是最廣回歸面** — 橫切 10 個寫入子命令（介面 B），append 若在主寫入**前**或未包 try/except，`run/` 不可寫時會連帶弄壞所有 helper（風險技術#1）。建議確認方式：append 必在 `save()` 成功後、整段 try/except、失敗僅 warning 不改 exit code；測試斷言「events 檔不可寫時主命令仍成功回傳」（D-err1）＋「缺 run_id 時 skip append」（D-err2）
- **gate 編號重排導致文件測試連鎖變紅** — 新增 commit gate 使 `skills/eval-flow/SKILL.md:234` 的「gate 1–5／gate 6」區間與 1.-6. 清單須同步重編號，否則 `tests/test_docs_consistency.py:78` `GateListConsistencyTest` 變紅（介面 C）。建議確認方式：改 gate 清單時同步改區間宣稱句，跑 `python3 -m unittest tests.test_docs_consistency`
- **`aborted` 語義的四個隱性消費點須全覆蓋** — check_other_runs（`eval_gates.py:198`）、`_find_unique_tier1_inprogress`（`:242`，風險報告漏列的第四點）、stats.py（`:63`）、eval-flow-resume（`SKILL.md:12`/`:56`）。任一把 aborted 誤判為 in_progress → 擋住所有新 run 或自動 resume 已放棄的 run（usage 正確性假設 3）。建議確認方式：四點各加斷言測試（aborted 不擋新 run、不被選為當前 tier-1 run、計入 stats 分佈、不自動 resume）
- **init.sh settings 合併擴充的靜默失效** — 合併邏輯（`init.sh:63-68`）誤刪/覆寫既有 PreToolUse → 整條 gate 防線靜默消失（比新 hook 沒接上嚴重）。建議確認方式：合併後 `doctor.py:116` 既有檢查（PreToolUse 含 gate-check）為守門，DoD 綁定跑 doctor；合併函式加冪等單元測試（跑兩次結果相同、兩事件皆在、其他鍵 `env`/`worktree` 不動，L-err1）
- **doctor.py `--brief` 缺 argparse 基礎** — `main()`（:89）目前不吃參數，4b 須新增解析且「預設模式行為不變」（K-brief）。建議確認方式：新增 `--brief` 後跑既有 `test_doctor.py` 確認 `check_skills_sync` 行為不變；`--brief` 全綠時無輸出、有異常僅印異常行的測試為新增（現有測試不覆蓋 main/CLI）
- **SessionStart 接線本 session 不可端到端驗證** — settings.json 改動需下次 session 載入才生效（風險部署#1）。建議確認方式：script 層以假 payload 直跑（`echo '<payload>' | python3 .claude/hooks/session_start.py`）驗 stdout≤10 行、殘留偵測、解析失敗靜默 exit 0（K-err1）；接線層由 doctor 檢查 settings 內容；收尾回報明告使用者「需重載 session 生效，首次載入請驗證 hook 有跑」
- **doctor HOOKS 清單是否納入 session_start.py** — `doctor.py:21` `HOOKS`（5 個 script）是「hooks 檔案齊全」健檢；新增 `session_start.py` 若不加入此清單，doctor 不會驗證其部署。建議確認方式：task-decomposer 明示 4a 是否將 `session_start.py` 加入 `HOOKS`（加入則 doctor 守其存在；不加則屬已知不健檢）——Spec 未明述，屬待決策點
- **測試分流：check_worktree_isolation.sh 刪除** — 3b 刪除前提是等價覆蓋存在（`RunHookWorktreeRootTest` `tests/test_eval_gates.py:513`，已確認）。建議確認方式：刪除前 grep 確認無程式碼/CI 呼叫（介面 G 已確認 0 命中）、DoD 斷言 `RunHookWorktreeRootTest` 存在且通過
- **events.jsonl 行序 vs ts 欄位（消費端保序假設）** — 2c 的時距與重入計算若依物理行序而非 `ts` 欄位，行序被打亂即失準（usage 正確性假設 1，裁決為消費端一律讀 `ts` 欄位）。建議確認方式：stats.py 新指標以 `ts` 取極值／依 cmd+step 計數，不依賴檔內物理行序，不為行序寫保序測試
