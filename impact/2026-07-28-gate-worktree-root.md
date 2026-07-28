# 影響面盤點報告：2026-07-28-gate-worktree-root

對象 Spec：`spec/2026-07-28-gate-worktree-root.md`（修正 hook gate 在 git worktree 下解析錯工作區）

變更核心：`.claude/hooks/eval_gates.py` 的 `run_hook()`（:300-341，root 解析在 :308-309）從「`CLAUDE_PROJECT_DIR` 優先」改為「僅當 tool call 來自與 `CLAUDE_PROJECT_DIR` 不同的 git 工作區時，才改用該工作區根」；連帶 `tests/check_worktree_isolation.sh`、`skills/parallel-run/SKILL.md`、`skills/eval-flow/SKILL.md`。

> 蒐證方式：所有 `檔案:行號` 與呼叫端命中數由本 agent 自行 Grep／Read／Bash 於 repo 根目錄全掃取得；基線測試數（134 tests, OK）自行執行 `python3 -m unittest discover -s tests` 確認。

---

## 1. 觸及模組清單

- `.claude/hooks/eval_gates.py` — 唯一的邏輯變更檔；`run_hook()` root 解析（:308-309）改寫，連帶影響其下游所有相對路徑消費點。
- `tests/check_worktree_isolation.sh` — 補上經 `run_hook()`（stdin 餵 payload、子進程執行）的端到端案例（Spec 範圍表、DoD 6）。
- `skills/parallel-run/SKILL.md` — 更正「hook 在各 worktree 內獨立生效」敘述（:38）並補成立條件（DoD 8）。
- `skills/eval-flow/SKILL.md` — 更正 fan-out 節的同義敘述（:314、:320）（DoD 8）。
- `~/.claude/skills/parallel-run/SKILL.md`、`~/.claude/skills/eval-flow/SKILL.md`（部署副本，inode 不同）— 手動同步一次（DoD 8、Spec 非目標 3）。
- **不觸及（但受既有約束）**：`tests/test_docs_consistency.py`（一致性檢查，改 SKILL.md 時不得破其格式，見第 6 節）、`tests/test_eval_gates.py`（若在此新增 `run_hook()` 單元覆蓋則觸及，見第 4／5 節建議）、`.claude/settings.json`（hook 註冊，非目標 2 不改）、`.claude/hooks/gate-check.sh`（唯一 `--hook` 呼叫者，非目標，不改）。

---

## 2. 各模組既有慣例

### `.claude/hooks/eval_gates.py`

- **命名慣例**：module-level 常數大寫（`GIT_COMMIT_RE`、`MANIFEST_RE`、`PHASES`、`AGENT_MIN_PHASE`、`SKILL_HINT`，:19-60）；內部 helper 前綴底線（`_validate_credentials` :94、`_find_unique_tier1_inprogress` :224）；gate 檢查函式 `check_*`（`check_manifest` :120、`check_other_runs` :178、`check_task_gate` :241、`check_staged_test_lint` :208）；模式 dispatch `run_hook`/`validate_state`（:300、:108）。
- **錯誤處理慣例**：
  - 攔截統一走 `block(msg)`（:78-83）→ `print("[gate-check] BLOCK: ...", file=sys.stderr)` + `sys.exit(2)`；訊息為中文、含修正指引。
  - 放行走 `sys.exit(0)`（:245、:297、:306、:319、:333、:341）。
  - 外部 I/O 失敗以 fail-open 收斂：`json.load(sys.stdin)` 解析失敗 → `sys.exit(0)`（:305-306）；`git diff --cached` 例外捕捉 `(OSError, subprocess.CalledProcessError)` → `sys.exit(0)`（:332-333）。**本次新增的 `git rev-parse` 子進程須沿此慣例**：以參數 list 呼叫、`try/except` 包覆、失敗退回 `CLAUDE_PROJECT_DIR`，不得向外拋例外（風險報告面向 1／4 硬約束）。
  - `load_json` 失敗 → `block`（:86-91）；`load_json_quiet` 失敗 → 回 `None`（:170-175，掃 `run/*.json` 時用，容忍壞檔）。
  - **無 logging 模組**；遙測走 `log_gate_hit()`（:64-75）append 到 `run/gate_hits.log`，失敗 `except OSError: pass`（:74-75，不影響攔截本身）。
- **測試慣例**（`tests/test_eval_gates.py`）：`unittest.TestCase` 子類，一 gate 一 class（`ValidateStateTest` :28、`ImpactAnalyzerGateTest` :239、`Tier1SubagentGateTest` :433 等）；需要相對路徑的測試在 `setUp` 手動 `os.chdir(self.tmp.name)`、`tearDown` 還原（:186-195 等五處：:187、:246、:289、:340、:440）；斷 block 用 `assertRaises(SystemExit)`；「斷言不拋例外」型測試以行尾 `# testlint: allow` 豁免假測試 lint（:32、:53、:307 等）。**新增測試須沿此體例**（tmp 目錄 + chdir + `assertRaises(SystemExit)`）。

### `tests/check_worktree_isolation.sh`

- **命名/結構慣例**：bash `set -euo pipefail`（:5）；`REAL_REPO`／`HOOKS_DIR`／`TMPDIR_X`／`SUB_WT` 大寫變數（:8-18）；每案例 `echo "[Test N] ..."`＋末尾 `echo "PASS/FAIL: ..."`；`trap 'cleanup' EXIT` 清理拋棄式 `mktemp -d` git repo（:20-27）。
- **測試呼叫慣例（既有）**：`( cd "$TMPDIR_X"; python3 -c "sys.path.insert(0, HOOKS_DIR); import eval_gates; eval_gates.check_other_runs('current-run')" ) || EXIT_CODE=$?` 直接呼叫函式（:81-89、:110-119）——**繞過 `run_hook()`**（Spec §4）。新 e2e 案例須改為經 `run_hook()`（`python3 eval_gates.py --hook`、stdin 餵 payload、`CLAUDE_PROJECT_DIR` 環境變數設為與 `payload.cwd` 不同的目錄），並比對 exit code（0/2），沿既有 `EXIT_CODE=$?` 判定體例。
- **安全慣例**：所有操作在 `mktemp -d` 拋棄式 git repo 內，絕不觸碰真實 `run/`（:4、:16-17 註明）——新案例必須沿此，不得對真實 repo 發 payload。

### `skills/parallel-run/SKILL.md`、`skills/eval-flow/SKILL.md`

- **敘述慣例**：條列以 `- **粗體標題**：說明`；skill 互引用寫 `` `name` skill `` 或 `skills/name/SKILL.md`（受 `test_docs_consistency.py` 稽核，見第 6 節）；hook 檔引用寫完整路徑 `.claude/hooks/eval_gates.py`（同受稽核）。

---

## 3. 可重用既有元件

本次為既有函式的行為修正，非新增功能，可重用元件集中在 `eval_gates.py` 內既有樣式：

- `.claude/hooks/eval_gates.py:327-333` `subprocess.run([...], capture_output=True, text=True, check=True)` + `except (OSError, subprocess.CalledProcessError): sys.exit(0)` — **既有的「以參數 list 呼叫 git、失敗 fail-open」樣板**，新增的 `git rev-parse --show-toplevel` 應直接沿用此形（加 `timeout=5`、擴 except 涵蓋 `subprocess.TimeoutExpired`／`subprocess.SubprocessError`）。
- `.claude/hooks/eval_gates.py:213` `os.path.dirname(os.path.abspath(__file__))` — 既有「取 hook 自身所在目錄」樣板（`check_staged_test_lint` 用來定位 `test_lint.py`）；若實作需區分「腳本所在（永遠主 repo）vs 工作區根」可參考。
- `.claude/hooks/eval_gates.py:170-175` `load_json_quiet()` — 容錯讀 JSON（掃 `run/*.json` 用），本變更不新增讀檔，無須新 helper。
- `tests/test_eval_gates.py` setUp/tearDown 的 `tempfile.TemporaryDirectory()` + `os.chdir` 樣板（:184-195）— 新增 `run_hook()` 單元測試可直接複用（若採第 5 節建議在此補覆蓋）。
- `tests/check_worktree_isolation.sh` 的 `mktemp -d` + `git init` + `git worktree add --detach`（:34-43）— 新 e2e 案例建構真實 worktree 的既有樣板，直接複用（含 `cleanup` trap）。

**防重複造輪**：不需自建 git 呼叫封裝、JSON 讀取、worktree 建構 helper——上述樣板已存在。

---

## 4. 被改介面的呼叫端清單

被改的介面是 **`run_hook()` 內 :308-309 的 root 解析結果（`os.chdir(root)`）**。它不是被外部 import 的 symbol，而是「改變其後所有相對路徑消費點的 CWD」。因此呼叫端＝(A) `eval_gates.py` 的所有進入點；(B) `chdir` 之後所有以相對路徑讀寫的位置；(C) import `eval_gates` 的檔案。逐一列出並附查詢方法。

### (A) `eval_gates.py` 進入點與外部呼叫者

- `.claude/hooks/eval_gates.py:344-353` `main()` — dispatch：`--hook` → `run_hook()`（:346-347）；`--validate <path>` → `validate_state()`（:348-350，人工自檢，**不經 `run_hook()`、不 chdir、不受本變更影響**）。
- `.claude/hooks/gate-check.sh:5` `exec python3 "$(dirname "$0")/eval_gates.py" --hook` — **唯一** `--hook` 呼叫者。
- `.claude/settings.json:9` `"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh"`，matcher `Bash|Task|Agent`（:5）— hook 註冊。**腳本永遠由主 repo 的 `$CLAUDE_PROJECT_DIR` 路徑載入**，故 worktree 內即使無 hook 檔，執行的仍是主 repo 那份 `eval_gates.py`（此為「一份邏輯管所有 worktree」的前提，本變更不改註冊方式）。
- **查詢方法**：`grep -rn "eval_gates\|gate-check\|--hook\|--validate" .`（排除 `__pycache__`）→ 除文件／spec／usage/task 敘述外，實際呼叫者僅 `gate-check.sh:5`（`--hook`）、`main()`（:344）內部 dispatch；`--validate` 無任何 repo 內呼叫者（僅 docstring :8 說明），為人工自檢工具。

### (B) `chdir` 之後依「當前工作目錄」的相對路徑消費點（全數受 root 改變影響）

commit gate 路徑（`run_hook()` :311-341）：
- `.claude/hooks/eval_gates.py:321` `os.path.exists("eval_state.json")` — 歸檔 gate；root 改則檢查對象改為該工作區的 `eval_state.json`。
- `.claude/hooks/eval_gates.py:328-331` `subprocess.run(["git","diff","--cached","--name-only"])` — **無 `-C`，讀 CWD 的 git index**；root 改則讀該工作區（worktree）的 staged 清單。這是 commit gate 靜默失效的根因（主 repo index 通常為空 → 全部憑據不檢查即放行，Spec §3）。
- `.claude/hooks/eval_gates.py:336` `MANIFEST_RE.match(p)` 對 `staged` 內相對路徑 → `check_manifest(path, staged)`（:338）→ 內部 :143 `archive_path = f"run/{run_id}.eval.json"`、:145 `archive_path in staged`、:148/:153 `load_json(archive_path)`（相對）；:340 `check_staged_test_lint(staged)` → :210 `os.path.exists(p)`（對相對 staged 路徑）、:216 跑 `test_lint.py`。全部隨 CWD 走。

subagent 呼叫 gate 路徑（`check_task_gate()` :241-297，由 :314-315 進入）：
- `.claude/hooks/eval_gates.py:249` `os.path.exists("eval_state.json")` — 決定走 Tier 2 常規 vs Tier 1 豁免路徑。
- `.claude/hooks/eval_gates.py:251` `load_json("eval_state.json")`、:254 `manifest_path = f"run/{run_id}.json"`、:255 `os.path.exists(manifest_path)`、:257 `load_json(manifest_path)` — 全相對。
- `.claude/hooks/eval_gates.py:268` `check_other_runs(run_id)` → :180 `glob.glob("run/*.json")` — 欠帳 gate＋單一 run gate，掃 CWD 的 `run/`。誤放行風險（Spec §3）：主 repo 若有無關 tier 1 in_progress manifest 會被當成「當前 run」。
- `.claude/hooks/eval_gates.py:261` `_find_unique_tier1_inprogress()` → :229 `glob.glob("run/*.json")` — Tier 1 豁免路徑，掃 CWD 的 `run/`。

遙測（跨兩條路徑，被 `block()` 呼叫）：
- `.claude/hooks/eval_gates.py:67` `os.path.isdir("run")`、:72 `open("run/gate_hits.log", "a")` — **`log_gate_hit()` 也是相對路徑寫檔**（`block()` :80 在 `_hint_enabled` 時呼叫）。root 改後，跨 worktree 命中的遙測寫入該 worktree 的 `run/gate_hits.log`，非主 repo。**屬預期副作用非回歸**（usage 互動點已載明），但拆分時須知悉：新 e2e 測試若在拋棄式 repo 觸發 `block()`，會在該 tmp repo 寫 `run/gate_hits.log`（tmp 內，無污染）。
- **查詢方法**：`grep -n "os.path.exists\|glob.glob\|os.path.isdir\|open(\"run\|git.*diff.*cached\|load_json(" .claude/hooks/eval_gates.py` → 命中上列各行；人工核對每處確為「相對路徑 / 無 `-C` / 無絕對前綴」，全部隨 `os.chdir(root)`（:309）走。`git diff --cached`（:328-331）確認無 `-C` 參數。

### (C) import `eval_gates` 的檔案（測試）

- `tests/check_worktree_isolation.sh:86`、`:116` `import eval_gates` → `eval_gates.check_other_runs('current-run')`（:87、:117）— **繞過 `run_hook()`**，直接呼叫函式（先 `cd "$TMPDIR_X"`）。對本 bug 零訊號（Spec §4）；本變更不改 `check_other_runs`，既有 4 案例修正後仍應通過。
- `tests/test_eval_gates.py` — `import eval_gates`（檔頭），測試個別函式（`check_other_runs`、`check_task_gate`、`check_manifest`、`validate_state`、`manifest_phase` 等），**setUp 手動 `os.chdir(tmp)`（:187-188 等）→ 完全繞過 `run_hook()` 的 root 解析**。無任一測試呼叫 `run_hook()`。
- **查詢方法**：`grep -rn "import eval_gates\|eval_gates\." tests/ --include=*.py --include=*.sh` → 呼叫端僅 `check_worktree_isolation.sh`（`check_other_runs`）與 `test_eval_gates.py`（多函式）；`grep -n "run_hook\|--hook\|CLAUDE_PROJECT_DIR\|json.load(sys.stdin)\|stdin" tests/*.py` → **0 命中** → 現有 unittest 對 `run_hook()`／root 解析零覆蓋（見第 5 節缺口）。

---

## 5. 跨模組風險點

1. **`run_hook()` root 解析（:308-309）現況零單元覆蓋** — `tests/test_eval_gates.py` 全部繞過 `run_hook()`（setUp 手動 chdir，:187 等），無任一測試餵 stdin payload 或設 `CLAUDE_PROJECT_DIR` 跑 `run_hook()`。**建議確認方式**：DoD 6 的 e2e 案例在 `.sh`；若要讓 `python3 -m unittest discover -s tests`（=DoD 7 的「全套測試」）真正覆蓋到 root 解析，需在 `test_eval_gates.py` 新增經 `subprocess.run([sys.executable, eval_gates.py, "--hook"], input=payload_json, env={CLAUDE_PROJECT_DIR:...})` 的整合測試（比照 `test_test_baseline.py:243` 的 subprocess 整合體例）——否則 root 解析永無 unittest 訊號。task-decomposer 須明確決定「單元覆蓋放 `.sh` 還是 `test_eval_gates.py`」，並在 item DoD 寫死。

2. **`tests/check_worktree_isolation.sh` 不在 `unittest discover` 範圍** — 全掃確認：無 `.github`（無 CI）、無 `Makefile`、無任何 python 測試以 subprocess 包裝呼叫此 `.sh`（`grep -rn check_worktree_isolation` 僅命中 spec/usage/task/該檔自身與 eval.json 證據）。既有 run 的 `local_test_evidence` 已明載「此 .sh 不入 unittest discover」（`run/2026-07-25-tier2-p-worktree.eval.json:170`）。它目前**僅由主 flow 手動重跑**、以輸出摘要記入 `local_test_evidence`（durable artifact 模式）。**後果**：DoD 6 若把 e2e 案例只加進 `.sh`，`python3 -m unittest discover -s tests`（DoD 7 基線 = 134 tests）**不會執行它**——「修正前失敗、修正後通過」的驗證必須在 step 5 額外手動 `bash tests/check_worktree_isolation.sh` 並記入證據，或另外在 `test_eval_gates.py` 建 subprocess 整合案例讓 discover 跑到。**建議確認方式**：task-decomposer 在 DoD 明列 e2e 案例的執行載體與「如何在 step 5 被真的跑到」，勿讓綠燈 134 掩蓋新案例未跑。

3. **本 run 自身即時受修改後 hook 管轄（fail-open 風險）** — `gate-check.sh:5` 每次呼叫都重讀 `eval_gates.py`，不快取；本檔一存檔即對本 run 後續 gate 生效。hook exit code 語義「非 0 非 2 = 非阻斷性錯誤、工具照常執行」→ 若引入未捕捉例外會**靜默 fail-open**（比鎖死更危險）。**建議確認方式**：修改後、依賴新行為前，以構造 payload 直接跑 `python3 .claude/hooks/eval_gates.py --hook`（三情境：同工作區、跨 worktree、非 git）確認皆回預期 exit code，且 `python3 -c "import eval_gates"` 可匯入（usage 情境 H、風險面向 4 硬性驗證）。

4. **最小偏離設計是硬約束（子目錄型專案 regression）** — 若實作改成「一律解析到 git 根」，`CLAUDE_PROJECT_DIR` 為 git repo 子目錄的專案會突然改看 `<repo>/run/`（不存在）→ 全面誤擋（風險面向 5、usage 情境 C）。**建議確認方式**：實作採「僅 `git_toplevel(cwd) != git_toplevel(CPD)` 時才改行為，否則回 CPD」；以 usage 情境 A/C（含子目錄 CPD）測試守住逐位元不變。

5. **`git rev-parse` 熱路徑延遲＋外部相依** — matcher `Bash|Task|Agent` 每次 tool call 觸發，新增子進程有固定延遲。**建議確認方式**：原始字串 `CLAUDE_PROJECT_DIR == payload.cwd` 相等時短路跳過 git（覆蓋主工作區最熱路徑，開放問題 3 裁示）；`timeout=5`；不引入跨進程快取。

6. **`git rev-parse --show-toplevel` 在 worktree 回不同根的基石假設** — 若 git 對 worktree 與主 repo 回相同 toplevel，`!=` 恆 false → bug 未修（usage 正確性假設 2）。**建議確認方式**：實作時以真實 worktree（`git worktree add`）實測 `git rev-parse --show-toplevel` 在 worktree 與主 repo 分別回不同路徑；e2e 測試沿 `check_worktree_isolation.sh:43` 的 `git worktree add --detach` 樣板建真實 worktree，不用推定。

7. **SKILL.md 敘述更正的目標句與部署副本同步** — 三處 load-bearing 錯誤敘述（第 6 節前段列出）；`~/.claude/skills/` 副本 inode 不同（`skills/parallel-run/SKILL.md` inode 66177810 vs 部署 63500111，已 Bash 確認），只改 repo 版執行期讀到舊版。**建議確認方式**：DoD 8 收尾前 `cp` 同步兩份副本並留痕；改文字時跑 `python3 -m unittest tests.test_docs_consistency` 確認未破一致性（見第 6 節）。

---

## 附錄 A：兩份 SKILL.md 的實際錯誤敘述位置（回應指定盤點 5）

三處把「hook 在各 worktree 內獨立生效」寫成既定事實的 load-bearing 句：

- `skills/parallel-run/SKILL.md:38`：原文「`- 跑循環 1–7，全部 gate 照常（hook 在各 worktree 內獨立生效）。`」（背景 agent 指示的一條）。
- `skills/eval-flow/SKILL.md:314`：原文「`- **hook gate 在各 worktree 內獨立生效**：每個 worktree 有自己的 staging area 與 `eval_state.json`，所有現行 gate 照常運作、零後門。`」——**最完整的錯誤斷言**（「每個 worktree 有自己的 eval_state.json、gate 照常」正是修正前不成立的前提）。
- `skills/eval-flow/SKILL.md:320`：原文（角色確認句，同義）「`... 背景 agent 在隔離 worktree 內具 Bash／Write／Edit、hook gate 照常生效且能 commit 自己 branch（成立）...`」——把「hook gate 照常生效」斷為「成立」，同屬須更正。

三處皆須改為「補上其成立條件」（即：需 hook 依 `payload.cwd` 解析所屬 worktree 根；此前提由本 run 修正建立），並依開放問題 1 裁示註明「子目錄型專案 ＋ worktree 目前不支援」。

相鄰但**非**本次目標句（描述 diff 乾淨／mine 模式，與 hook root 無關、修正前後皆真，不必改）：`skills/eval-flow/SKILL.md:287`（「git diff --cached 天生乾淨」）、`:313`（mine 模式在隔離樹下復活）。

其他文件確認**無**相同錯誤敘述：
- `README.md` — 僅 `:82` 表格指向 `skills/parallel-run/` 目錄、無 worktree 獨立性斷言。
- `CLAUDE.md` — 僅 `:50` 描述 hook 機制（`gate-check.sh → eval_gates.py`），無 worktree 獨立性斷言。
- 其他 skill／`.claude/agents/*.md` — `grep -rn "獨立生效"` 全掃僅命中上述 `parallel-run/SKILL.md` 與 `eval-flow/SKILL.md` 兩檔。
- **查詢方法**：`grep -rn "各 worktree 內獨立\|獨立生效\|hook.*worktree\|worktree.*gate" skills/ README.md CLAUDE.md .claude/agents/` → load-bearing 命中僅 :38/:314/:320 三處。

---

## 附錄 B：`tests/test_docs_consistency.py` 對 SKILL.md 的約束（回應指定盤點 6）

`MD_FILES`（:11-15）= `skills/*/SKILL.md` + `.claude/agents/*.md` + `CLAUDE.md` + `README.md`——**兩份要改的 SKILL.md 都在稽核範圍**。改文字時不可破以下格式：

1. **`HookScriptReferencesTest`（:22-30）**：pattern `\.claude/hooks/([\w.-]+\.(?:py|sh))`——文中任何 `.claude/hooks/xxx.py|sh` 引用對應檔案必須存在。更正敘述時若提到 `eval_gates.py`／`gate-check.sh`／`test_baseline.py`，**路徑不可打錯**（例：`eval-flow/SKILL.md:313` 已引用 `.claude/hooks/test_baseline.py`）。
2. **`SkillReferencesTest`（:33-61）**：pattern `` [`*]name[`*]+ skill `` 與 `skills/name/SKILL.md`——引用其他 skill 必須用既有 skill 目錄名（`eval-flow`／`parallel-run`／`test-strategy`／`task-decomposition` 等）。更正句若新增 skill 互引，**寫法須維持** `` `name` skill `` 或 `skills/name/SKILL.md`，且 name 須存在於 `skills/` 目錄。
3. **`HelperSubcommandDocsTest`（:64-75）**：只檢 `eval-flow/SKILL.md` 中 `eval_state.py`（`cmd／cmd`）子命令清單須存在於 `eval_state.py`——本次不動該清單，維持即可。
4. **`GateListConsistencyTest`（:78-94）**：regex `gate 1–(\d+)）.*?（gate (\d+)–(\d+)）`——檢查 gate 編號區間與清單條數一致。現況 `eval-flow/SKILL.md:220` 為「（gate 1–5），…（gate 6）」，第二段是**單一編號非區間**故 regex `not m → continue`（本測試對現行文字實質 skip）；`README.md` 無 `gate 1–N` 句。**更正 worktree 敘述（:38/:314/:320）遠離 gate 編號段，風險低**——但切勿在更正句中新造「gate 1–N … gate X–Y」樣式而觸發此檢查不一致。

**建議**：改完兩份 SKILL.md 後跑 `python3 -m unittest tests.test_docs_consistency`（屬 134 tests 的一部分，會被 `discover` 跑到）確認 0 失敗。

---

## 附錄 C：基線與範圍事實核對

- `python3 -m unittest discover -s tests` 現況：**Ran 134 tests … OK**（本 agent 實跑確認，對應 DoD 7 基線）。
- `tests/check_worktree_isolation.sh` 現況 4/4 pass，**不在** `unittest discover` 內（第 5 節風險 2）。
- `.claude/settings.json:9` hook 以 `$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh` 註冊，matcher `Bash|Task|Agent`（:5）——腳本永遠由主 repo 路徑載入，本變更不改此註冊（Spec 非目標 2）。
