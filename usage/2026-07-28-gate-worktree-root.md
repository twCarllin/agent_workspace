# 使用情境報告 — 修正 hook gate 在 git worktree 下解析錯工作區  (run_id: 2026-07-28-gate-worktree-root)

> 本報告為框架自身的 hook gate 修正，非一般業務功能。「使用者角色」不是終端使用者，而是**發出 tool call、進而觸發 hook 的執行者**（主 flow、背景 agent、框架 runtime）。gate 的判定對象＝`run_hook()` 內 `os.chdir(root)` 後所有相對路徑讀取的**工作區**（`eval_state.json`、`run/*.json`、`git diff --cached` 的 git index）。
>
> 變更點只有一處：`eval_gates.py:308` 的 `root` 解析。所有情境都是「同一段解析邏輯」在不同輸入組合下的行為，外加它被**兩條 gate 路徑**（commit gate 1–5、subagent 呼叫 gate 6）消費後的可觀察結果。

## 角色

- **主 flow（主工作區）**：人驅動的主 session，tool call 從主 repo 發出。`CLAUDE_PROJECT_DIR` 與 `payload.cwd` 皆指向主 repo 根。
- **主 flow（EnterWorktree 後）**：主 session 切入 worktree 後發 tool call。`CLAUDE_PROJECT_DIR` 仍釘在主 repo，`payload.cwd` 指向 worktree。
- **parallel-run 背景 agent**：`parallel-run` skill 下，各自在獨立 worktree 跑一個獨立 Tier 1 run 的背景 agent（`isolation: "worktree"`）。共用主 session 的 `CLAUDE_PROJECT_DIR`，`payload.cwd` 各自指向自己的 worktree。
- **Tier 2 [P] fan-out 背景 item agent**：`eval-flow` fan-out 節下，各自在 `feat/<父run_id>-item-<id>` worktree 跑迷你 run 的背景 item agent。同上 CPD 共用、cwd 各自獨立。
- **子目錄型專案的 flow 執行者**：session 啟動於某 git repo 的**子目錄**（flow 檔如 `run/`、`eval_state.json` 放在 `<repo>/subproject/` 下），`CLAUDE_PROJECT_DIR` 指向該子目錄。**這是最大 regression 面（Spec DoD 5、風險面向 5）**。
- **非 git 環境的 flow 執行者**：`payload.cwd` 不在 git 儲存庫內，或 `git` 不在 PATH／逾時／儲存庫損毀。
- **Claude Code hook runtime（框架系統角色）**：不主動操作，但每次 `Bash|Task|Agent` tool call 都注入 `CLAUDE_PROJECT_DIR` 環境變數與 `payload.cwd`，並依 hook exit code（0 放行／2 攔截／其他值＝非阻斷性錯誤，工具照常執行）決定是否放行。它是「被副作用影響」的系統角色——本修正若 fail-open（回傳非 0 非 2 的碼）它會靜默放行。
- **本 run 自身（self-hosting 執行者）**：本 run 在主工作區跑；`gate-check.sh` 每次呼叫都重讀 `eval_gates.py`，故本檔一經存檔即**立即**對本 run 後續的 subagent 呼叫與收尾 commit 生效（Spec §9、風險面向 4）。等同「飛行中換自己的安全網」。
- **接手者／維運（讀 SKILL.md 的人或 AI）**：依 `parallel-run` / `eval-flow` SKILL.md 宣稱決定是否採用 worktree 並行。目前文件宣稱「hook 在各 worktree 內獨立生效」為既定事實，實際失效——文件敘述須一併更正（DoD 8），否則落差會再次誤導接手者。

---

## 情境

### 核心：root 解析（餵入 `run_hook()` root 解析 item）

### A — 主工作區、同一工作區根（現行行為必須逐位元不變）  角色: 主 flow（主工作區）／本 run 自身
- 前置: `CLAUDE_PROJECT_DIR` 與 `payload.cwd` 解析出的 git toplevel 相同（皆主 repo 根）
- 操作: 主 flow 發任一 `Bash|Task|Agent` tool call
- 預期: `root` 解析回 `CLAUDE_PROJECT_DIR`，`chdir` 到主 repo 根，gate 對主工作區判定——與修改前**逐位元相同**（DoD 5）
- I/O: input `CLAUDE_PROJECT_DIR=<repo>, payload.cwd=<repo>` / output `root=<repo>` / 副作用: `os.chdir(<repo>)`；後續讀主 repo 的 `eval_state.json`、`run/*.json`、git index；可能寫 `run/gate_hits.log`（若命中攔截）

### B — 跨 worktree（唯一改變行為的分支）  角色: 主 flow（EnterWorktree 後）／parallel-run 背景 agent／fan-out item agent
- 前置: `CLAUDE_PROJECT_DIR` 釘在主 repo，`payload.cwd` 在某 git worktree 內；兩者 git toplevel **不同**
- 操作: 該執行者在自己 worktree 發 tool call
- 預期: `root` 解析回 **`payload.cwd` 所屬 worktree 根**（`git rev-parse --show-toplevel`），`chdir` 到 worktree，gate 對該 worktree 的狀態檔與 git index 判定（DoD 1）
- I/O: input `CLAUDE_PROJECT_DIR=<repo>, payload.cwd=<worktree>` / output `root=<worktree_top>` / 副作用: `os.chdir(<worktree_top>)`；一次 `git rev-parse` 子進程（帶 timeout）；後續讀 worktree 的狀態檔與 git index

### B-edge1 — cwd 位於 worktree 子目錄（DoD 2）  角色: 同 B
- 觸發: `payload.cwd` 指向 worktree 內的子目錄（非 worktree 根）
- 預期: 仍解析到該 **worktree 根**（`git rev-parse --show-toplevel` 天然回根，非子目錄）
- I/O: input `payload.cwd=<worktree>/sub/dir` / output `root=<worktree_top>` / 副作用: 同 B

### C — 子目錄型主工作區（regression 面，行為必須不變）  角色: 子目錄型專案的 flow 執行者
- 前置: `CLAUDE_PROJECT_DIR=<repo>/subproject`（flow 檔在子目錄下），`payload.cwd` 在同一 repo 內；`git_toplevel(CPD)` 與 `git_toplevel(cwd)` **相同**（皆 `<repo>` 根）
- 操作: 該執行者在主工作區發 tool call
- 預期: 因兩者 toplevel 相等 → 走「否則」分支 → 回傳 `CLAUDE_PROJECT_DIR`（= 子目錄本身，**非 git 根**），`chdir` 到子目錄，gate 對子目錄的狀態檔判定——與修改前完全一致（DoD 5）
- I/O: input `CLAUDE_PROJECT_DIR=<repo>/subproject, payload.cwd=<repo>/subproject（或 repo 內他處）` / output `root=<repo>/subproject` / 副作用: `os.chdir(<repo>/subproject)`
- **關鍵**: 若實作改成「一律解析到 git 根」，此情境會突然改看 `<repo>/run/`（不存在）→ 子目錄型專案 flow 全面誤擋。此為風險面向 5 的最大 regression，實作須採「最小偏離設計」（僅 `cwd_top != cpd_top` 時才改變行為）

### D — 非 git / git 不可用 / git 逾時（DoD 3）  角色: 非 git 環境的 flow 執行者
- 觸發: `payload.cwd` 不在 git 儲存庫內，或 `git` 不在 PATH、儲存庫損毀、`git rev-parse` 逾時
- 預期: `git_toplevel` 失敗（`subprocess` 例外或 timeout，被 `try/except` 捕捉）→ 退回 `CLAUDE_PROJECT_DIR`，行為與現行一致；**不得**讓解析失敗向外拋例外（否則 hook fail-open）
- I/O: input `payload.cwd=<非git路徑>` 或 `git` 不可用 / output `root=CLAUDE_PROJECT_DIR` / 副作用: `os.chdir(CLAUDE_PROJECT_DIR)`；一次失敗的 `git` 子進程（帶 timeout，5 秒內返回）

### E — payload 缺 cwd 欄位（DoD 4）  角色: 框架 runtime（舊版／非預期輸入）
- 觸發: `payload` 無 `cwd` 鍵（`payload.get("cwd")` 回 `None`）
- 預期: 不拋例外，退回現行行為（回傳 `CLAUDE_PROJECT_DIR`）——**行為細節有歧義，見開放問題 2**
- I/O: input `payload` 無 cwd / output `root=CLAUDE_PROJECT_DIR`（預設傾向） / 副作用: `os.chdir(...)`；視實作可能省略 `git` 呼叫

### 消費：兩條 gate 路徑（驗證兩個互動點皆被涵蓋）

### F — subagent 呼叫 gate（gate 6）於 worktree（修復兩個相反的誤判方向）  角色: parallel-run 背景 agent／fan-out item agent
- 觸發: worktree 內的背景 agent 呼叫流程管制 subagent（`usage-analyzer`／`impact-analyzer`／`task-decomposer`／`code-writer`），走 `check_task_gate()`
- 修復前（bug）:
  - **誤擋**: `chdir` 回主 repo → worktree 內備妥的 `eval_state.json`／manifest 不被看見 → 以「run 未初始化」等理由誤擋
  - **誤放行**: `eval_state.json` 在主 repo 不存在時走 Tier 1 豁免路徑，`_find_unique_tier1_inprogress()` 掃**主 repo** 的 `run/*.json`；若主 repo 恰有另一個唯一 tier 1 in_progress manifest → 回傳**無關 run** 的 manifest 並據以核准呼叫（Spec §3）
- 修復後預期: `chdir` 到發出呼叫的 worktree → `check_task_gate()`、`check_other_runs()`、`_find_unique_tier1_inprogress()` 全部掃該 worktree 的 `run/`，判定對象正確
- I/O: input `tool=Task/Agent, subagent_type=<...>, payload.cwd=<worktree>` / output `exit 0 放行 / exit 2 攔截`（依 worktree 真實狀態） / 副作用: `os.chdir(<worktree>)`；glob `run/*.json`；讀 `eval_state.json`、manifest；可能寫 `<worktree>/run/gate_hits.log`

### G — commit gate（gate 1–5）於 worktree（修復靜默失效）  角色: parallel-run 背景 agent／fan-out item agent
- 觸發: worktree 內執行者發 `git commit`，走 `run_hook()` 的 commit 分支
- 修復前（bug）: `git diff --cached --name-only` 讀**主 repo** 的 index（通常為空，因變更 staged 在 worktree 的獨立 index）→ `staged` 為空 → 無 manifest 命中 → intent/status/tier 憑據/eval 歸檔/假測試 lint **一項都不檢查**，直接放行（Spec §3）
- 修復後預期: `chdir` 到 worktree → `eval_state.json` 存在性檢查、`git diff --cached` 讀 worktree 的 index、`check_manifest()`（含四項憑據）、`check_staged_test_lint()` 全部對 worktree 生效
- I/O: input `tool=Bash, command 含 git commit, payload.cwd=<worktree>` / output `exit 0 放行 / exit 2 攔截`（依 worktree staged 內容與 manifest） / 副作用: `os.chdir(<worktree>)`；`git diff --cached`（worktree index）；可能 `subprocess` 跑 `test_lint.py`

### H — 本 run 自身即時受修改後 hook 管轄（fail-open 硬性驗證）  角色: 本 run 自身（主工作區）
- 觸發: 修改 `eval_gates.py` 存檔後，本 run（在主工作區）後續的任一 `Bash|Task|Agent` tool call 與收尾 `git commit`
- 預期: 走情境 A／C 路徑（主工作區）→ 行為與修改前一致，本 run 不被自己的修改鎖死、也不 fail-open。因 hook exit code「非 0 非 2 = 非阻斷性錯誤，工具照常執行」，若修正引入未捕捉例外 → gate **靜默停止攔截**（比鎖死更危險）
- I/O: input `payload.cwd=<主repo>` / output `exit 0/2`（絕不可因例外變成其他碼） / 副作用: 同 A
- **硬性驗證（風險面向 4）**: 修改後、依賴新行為前，須以構造 payload 直接執行 `eval_gates.py --hook` 實測三情境（同工作區、跨 worktree、非 git）皆回**預期 exit code**，確認未 fail-open，且 `python3 -c "import eval_gates"` 可正常匯入

### 測試與文件（各對映獨立 item）

### I — 端到端測試新案例（DoD 6）  角色: 測試執行者（CI／本地）
- 觸發: 執行 `tests/check_worktree_isolation.sh`
- 現況缺口: 既有 4 案例以 `cd <tmp> && python3 -c "...check_other_runs(...)"` 直接呼叫函式，**繞過 `run_hook()` 的 root 解析與 `chdir`**（Spec §4）——對本 bug 零訊號，屬假保證
- 預期: 新增案例經 `run_hook()`（stdin 餵 payload、子進程執行），涵蓋「`CLAUDE_PROJECT_DIR` 與 `payload.cwd` 不一致」；套用修正前失敗、套用後通過（DoD 6）；全套 `python3 -m unittest discover -s tests` 相對基線（134 tests, OK）無新增失敗（DoD 7）
- I/O: input `構造 CLAUDE_PROJECT_DIR≠payload.cwd 的 payload` / output `修正前 exit 非預期 / 修正後 exit 預期` / 副作用: 在 `mktemp` 拋棄式 git repo 內操作，絕不觸碰真實 `run/`

### J — SKILL.md 敘述更正 ＋ 部署副本同步（DoD 8）  角色: 接手者／維運
- 觸發: 接手者讀 SKILL.md 決定是否用 worktree 並行
- 現況: `skills/parallel-run/SKILL.md:38`（「全部 gate 照常（hook 在各 worktree 內獨立生效）」）與 `skills/eval-flow/SKILL.md:314`（「hook gate 在各 worktree 內獨立生效」，另 :320 角色確認句同義）把「hook 在各 worktree 內獨立生效」寫成既定事實——該前提在修正前不成立
- 預期: 兩處敘述更正，補上其成立條件（即：需 hook 依 `payload.cwd` 解析所屬 worktree）；且 `~/.claude/skills/` 的部署副本（非 symlink、inode 不同）一併同步，否則執行期讀到舊版
- I/O: input `兩份 repo SKILL.md` / output `更正後 SKILL.md ＋ 已同步的部署副本` / 副作用: 覆寫 `~/.claude/skills/parallel-run/SKILL.md`、`~/.claude/skills/eval-flow/SKILL.md`

---

## 與現有功能互動點

- **commit gate（gate 1–5）＝ `run_hook()` 的 `git commit` 分支（eval_gates.py:321–341）**：`eval_state.json` 存在檢查、`git diff --cached`、`check_manifest`（intent／status／tier 憑據／eval 歸檔）、`check_staged_test_lint`——全數以 `chdir` 後相對路徑運作，受 root 解析影響。回歸風險：主工作區與子目錄型專案（情境 A／C）行為必須不變。
- **subagent 呼叫 gate（gate 6）＝ `check_task_gate()`**：內含 `check_other_runs()`（欠帳 gate ＋ 單一 run gate）、`_find_unique_tier1_inprogress()`（Tier 1 豁免路徑）、phase 狀態機、`task_file`／`usage_report_path` 檢查——皆 glob `run/*.json` 或讀相對路徑，受 root 解析影響。
- **`run/gate_hits.log` 遙測（`log_gate_hit()`）**：以 `os.path.isdir("run")` 判斷並 append，路徑隨 `chdir` 後 CWD 走——修正後跨 worktree 命中的遙測會寫入該 worktree 的 `run/`，非主 repo。屬預期副作用，非回歸。
- **`tests/check_worktree_isolation.sh`（既有 4 案例）**：繞過 `run_hook()`，對本 bug 零訊號；新增 e2e 案例後既有案例仍應通過（不得破壞既有隔離語意）。
- **`.claude/settings.json` hook 註冊**：hook 以 `$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh` 呼叫——**腳本本身永遠由主 repo 的 CLAUDE_PROJECT_DIR 路徑載入**，故即使 worktree 內無 hook 檔，執行的仍是主 repo 那份 `eval_gates.py`。此為本修正得以「一份邏輯管所有 worktree」的前提，非目標範圍（Spec 非目標 2 不改註冊方式）。
- **`skills/parallel-run/SKILL.md`、`skills/eval-flow/SKILL.md`**：兩者以「hook 在各 worktree 內獨立生效」為前提描述並行機制，前提在修正前不成立；須一併更正（情境 J）。回歸風險：文件與行為落差會誤導接手者。
- **若這個修正上線，哪個現有功能可能壞掉？** 答：子目錄型專案的 flow（情境 C）——若實作偏離「最小偏離設計」，主工作區在 git repo 子目錄的既有專案會全面誤擋。這是必須以情境 C ＋ H 守住的回歸面。

---

## 正確性假設清單（使用者已於 2026-07-28 全數確認採納）

1. **`payload.cwd` 準確反映「發出此次 tool call 的工作區」**（含背景 subagent）。消費點 `eval_gates.py:308`（`payload.get("cwd")`）→ `:309 os.chdir`。被破壞時可觀察差異: gate 會 `chdir` 到錯誤工作區 → 讀錯 `run/`／git index → 誤擋或誤放行。**已由 Spec §2 實測證據表佐證**（背景 subagent 的 `payload.cwd` 各自獨立且正確，即使 `session_id` 與 `CLAUDE_PROJECT_DIR` 共用）——load-bearing 已驗證。

2. 【基石假設｜實作時必須以真實 worktree 實測，不可只靠推定】**`git rev-parse --show-toplevel` 在 worktree 內回傳的是「該 worktree 的根」，且與主 repo 根字串不相等。** 消費點: 修正後 `cwd_top != cpd_top` 的比較（新增於 `run_hook()`，比較兩個 git-resolved toplevel）。被破壞時可觀察差異: 若 git 對 worktree 與主 repo 回相同 toplevel，`!=` 恆為 false → 跨 worktree 分支永不觸發 → bug 未修（仍誤擋／誤放行）。這是修正正確性的**基石假設**，須於實作時以真實 worktree 實測確認 `git rev-parse --show-toplevel` 在 worktree 與主 repo 分別回不同路徑。

3. **比較用的是「兩個 git-resolved toplevel」而非「原始字串」，以吸收 symlink／尾斜線差異。** 消費點: 同上比較點。被破壞時可觀察差異: 若拿原始 `CLAUDE_PROJECT_DIR` 與 `payload.cwd` 直接字串比對（如 macOS `/tmp` vs `/private/tmp` symlink、尾斜線），可能主工作區被誤判為「跨 worktree」→ 情境 A/C 行為改變 → DoD 5 破。設計須對 CPD 與 cwd **各跑一次** `git_toplevel` 再比對（此即風險面向 5 的 `cpd_top = git_toplevel(CLAUDE_PROJECT_DIR)`）。注意此與開放問題 3 的字串短路相容：原始字串**相等**才短路跳過 git；原始字串**不等**時仍各跑一次 `git_toplevel` 比對，故 symlink／尾斜線情形不會被短路掩蓋。

4. 【實作時必須以構造 payload 實測 exit code，不可只靠單元測試推定】**hook exit code 語義：0 放行、2 攔截、其他值＝非阻斷性錯誤（工具照常執行）。** 消費點: 框架 runtime 對 `gate-check.sh` 回傳碼的處理（外部於本 repo）。被破壞時可觀察差異: 若修正引入未捕捉例外，`eval_gates.py` 以非 2 的碼結束 → gate **靜默 fail-open**（不再攔截），而非鎖死。此語義使「解析失敗一律退回現行行為、絕不拋例外」成為硬性正確性需求（情境 D／H），須於情境 H 以構造 payload 實測 exit code 確認，不可只靠單元測試推定。

（順序性／原子性等無涉本變更，不列。）

---

## 開放問題（使用者已於 2026-07-28 逐條裁示，全數採預設傾向）

1. **子目錄型專案 ＋ worktree 的組合，應解析到 worktree 根還是 worktree 內的對應子目錄？**
   本框架 flow 檔在 repo 根，不受影響；但若某子目錄型專案（`CLAUDE_PROJECT_DIR=<repo>/subproject`）開了 worktree，情境 B 會解析到 `<worktree_top>`（worktree 根），而該專案的 flow 檔其實在 `<worktree_top>/subproject/`。此時 gate 會找不到狀態檔。
   預設傾向: **接受此限制**（解析到 worktree 根），文件註明「子目錄型專案 ＋ worktree 目前不支援」——本框架不觸發，複雜度不值得。
   若改「保留 CPD 相對子路徑並套用到 worktree 根」（`<worktree_top>/subproject/`）: 需為此加專屬情境與測試案例，`run_hook()` 解析邏輯多一個「計算 CPD 相對 git 根的子路徑並拼接」分支，拆分多一個 item。
   → **裁示（2026-07-28）：採預設。接受限制，解析到 worktree 根；不加拼接子路徑的分支。文件（情境 J 的 SKILL.md 更正）須註明「子目錄型專案 ＋ worktree 目前不支援」。**

2. **`payload` 缺 `cwd` 欄位時，嚴格回傳 `CLAUDE_PROJECT_DIR`，還是退回 `os.getcwd()`？**
   DoD 4 字面要求「退回現行行為」（現行無 cwd 時回 `CLAUDE_PROJECT_DIR`）。但 Spec §2 證據表顯示 hook 進程 PWD（`os.getcwd()`）在 worktree 情境下 == worktree，故退回 `os.getcwd()` 可能**更正確**地抓到 worktree。兩份文件（DoD 4 vs 風險面向 5 的 pseudo-code「退回 os.getcwd() 後同上」）措辭略有出入。
   預設傾向: **嚴格回傳 `CLAUDE_PROJECT_DIR`**（最小偏離、DoD 4 字面、行為可預測）。
   若改用 `os.getcwd()`: 引入「hook PWD 可信度」新假設，需為缺 cwd 情境加測試，且情境 E 的預期輸出改變——拆分時 item 需明列此分支。
   → **裁示（2026-07-28）：採預設。缺 cwd 時嚴格回傳 `CLAUDE_PROJECT_DIR`，不採 `os.getcwd()`。文件衝突正式敉平：風險報告面向 5 的 pseudo-code 寫「退回 os.getcwd() 後同上」與 DoD 4 措辭不一致，一律以本裁示（嚴格回 CPD）為準；實作時以此為唯一依據，不得依風險報告 pseudo-code 的 `os.getcwd()` 措辭。情境 E 預期輸出即 `root=CLAUDE_PROJECT_DIR`。**

3. **效能設計：主工作區常見情境是否以「原始字串 `CLAUDE_PROJECT_DIR == payload.cwd` 相等」短路，跳過兩次 `git rev-parse`？**
   風險面向 3 要求「僅在必要時呼叫 git」，但面向 5 的比較需對 CPD 與 cwd 各跑一次 `git_toplevel`（每次 tool call 多兩次子進程）。最常見的主工作區 case（A）兩者原始字串本就相等。
   預設傾向: **cwd 與 CPD 原始字串相等時直接回 CPD、跳過 git**（覆蓋主工作區最熱路徑，省兩次子進程）；不等時才各跑一次 `git_toplevel` 比對。
   影響拆分: 影響 `run_hook()` 解析分支結構（早退短路 ＋ git 比對兩層），須在對應 item 備註；但須注意此短路不可掩蓋假設 3 的 symlink 情形（原始字串不等但 git 根相同的主工作區變體，仍走 git 比對正確回落到 CPD）。
   → **裁示（2026-07-28）：採預設。cwd 與 CPD 原始字串相等時直接回 CPD、跳過 git；字串不等時仍各跑一次 `git_toplevel` 比對（確保 symlink／尾斜線情形不被短路掩蓋，見正確性假設 3）。**

4. **`git rev-parse` 的 timeout 值採 5 秒（風險面向 3 建議）是否可接受？**
   逾時即退回 CPD（fail-safe，情境 D）。5 秒是「git 卡住時工具呼叫最多被拖 5 秒」與「慢磁碟/大 repo 誤觸逾時」的權衡。
   預設傾向: **5 秒**。此為單一常數，不影響情境數，僅需確認。
   → **裁示（2026-07-28）：採預設。timeout = 5 秒，逾時退回 CPD。**

5. **混合情境（`git_toplevel(CLAUDE_PROJECT_DIR)` 成功但 `git_toplevel(payload.cwd)` 失敗，或反之）是否需特殊處理？**
   例: CPD 在 git、cwd 不在 git（罕見）。
   預設傾向: **任一 `git_toplevel` 失敗即回 `CLAUDE_PROJECT_DIR`**（DoD 3 已涵蓋「非 git／git 不可用一律退回」），不加特殊分支。確認無需額外情境即可。
   → **裁示（2026-07-28）：採預設。任一 `git_toplevel` 失敗即回 CPD，不加特殊分支。**
