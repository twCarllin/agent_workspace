# Spec：修正 hook gate 在 git worktree 下解析錯工作區

run_id：`2026-07-28-gate-worktree-root`

## 1. 問題陳述

`.claude/hooks/eval_gates.py` 的 `run_hook()` 以下列優先序決定「要對哪個工作區套用 gate」：

```python
root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
os.chdir(root)
```

`CLAUDE_PROJECT_DIR` 由 Claude Code 在 **session 啟動時**決定並釘死於啟動目錄，**不隨 git worktree 切換而移動**。因此當 flow 在 worktree 內執行時，hook 會 `chdir` 回主工作區，並以主工作區的狀態檔套用 gate。

所有 gate 的狀態來源都是 `chdir` 之後的相對路徑，全數受影響：

- `eval_state.json`（`run_hook()`、`check_task_gate()`）
- `run/*.json` glob（`check_other_runs()`、`_find_unique_tier1_inprogress()`）
- `git diff --cached --name-only`（commit gate 的 staged 檔案清單；主工作區與 worktree 的 git index 是各自獨立的）

## 2. 實測證據

以暫時性探針攔截 PreToolUse hook 的 stdin payload 與環境變數，在同一個 session 內量測三種情境：

| 情境 | `CLAUDE_PROJECT_DIR` | `payload.cwd` | hook 進程 PWD |
|---|---|---|---|
| A 主工作區 | 主 repo | 主 repo | 主 repo |
| B 以 `EnterWorktree` 切入 worktree | **主 repo（未變）** | worktree | worktree |
| C 背景 subagent（`isolation: "worktree"`） | **主 repo（未變）** | worktree | worktree |

情境 C 的 `session_id` 與主 session 相同，證實背景 subagent 共用同一份 hook 設定與同一個 `CLAUDE_PROJECT_DIR`，但**每次 tool call 的 `payload.cwd` 各自獨立且正確**。

補充實測：構造 `CLAUDE_PROJECT_DIR` 指向空目錄、`payload.cwd` 指向含合法 tier 1 in_progress manifest 的目錄，呼叫 `code-writer` gate，結果為

```
[gate-check] BLOCK: 呼叫 code-writer 前須完成前置 0：eval_state.json 不存在（run 未初始化）
```

即 gate 未讀取 `payload.cwd` 指向的正確狀態。

## 3. 影響

兩種方向相反的失效，皆為靜默：

- **subagent 呼叫 gate（gate 6）誤判**：worktree 內備妥的 manifest 不被看見 → 誤擋；若主工作區恰有另一個唯一的 tier 1 in_progress manifest，`_find_unique_tier1_inprogress()` 會回傳**無關 run 的 manifest** 並據以核准呼叫 → 誤放行。
- **commit gate（gate 1–5）失效**：`git diff --cached` 讀主工作區的 index（通常為空）→ `staged` 為空 → 無 manifest 命中 → 四項憑據、eval 歸檔檔、假測試 lint **一項都不檢查**，直接放行。

受影響的既有機制：`skills/parallel-run/SKILL.md`（背景 agent 於各 worktree 跑 Tier 1）與 `skills/eval-flow/SKILL.md` 的「Tier 2 [P] fan-out」節，兩者都以「hook 在各 worktree 內獨立生效」為前提，該前提不成立。

## 4. 既有測試為何沒抓到

`tests/check_worktree_isolation.sh` 已存在且 4/4 通過，但它以

```
cd "$TMPDIR_X" && python3 -c "import eval_gates; eval_gates.check_other_runs('current-run')"
```

直接呼叫函式，**繞過 `run_hook()` 的 root 解析與 `chdir`**。它驗證的是「函式在給定 CWD 下只掃該 CWD」，而 bug 出在「`run_hook()` 會把 CWD 換掉」。因此該腳本對本 bug 零訊號，屬假保證。

## 5. 目標

hook 的 gate 一律套用在**發出該次 tool call 的工作區**（主工作區或任一 worktree），使 `parallel-run` 與 `[P]` fan-out 的 worktree 隔離前提成立。

## 6. 範圍

| 檔案 | 變更 |
|---|---|
| `.claude/hooks/eval_gates.py` | `run_hook()` 的 root 解析改以 `payload.cwd` 為準，經 `git rev-parse --show-toplevel` 解出所屬 worktree 根；非 git 環境退回 `CLAUDE_PROJECT_DIR` |
| `tests/test_eval_gates.py` | **新增**經 `run_hook()` 的端到端案例（以 `subprocess` 執行 `eval_gates.py --hook`、stdin 餵構造 payload、對真實 `git worktree` 驗證），涵蓋「`CLAUDE_PROJECT_DIR` 與 `payload.cwd` 不一致」。選此檔為載體的理由見下 |
| `tests/check_worktree_isolation.sh` | 於檔頭補一行範圍註記，說明本腳本直接呼叫 `check_other_runs()`、**不經 `run_hook()`**，故不涵蓋 root 解析。既有 4 個案例不改動 |
| `skills/parallel-run/SKILL.md` | 修正「hook 在各 worktree 內獨立生效」的敘述，補上其成立條件 |
| `skills/eval-flow/SKILL.md` | 同上，fan-out 節的相同敘述 |

**部署同步**：`skills/` 於 `~/.claude/skills/` 另有一份內容相同的部署副本（非 symlink、inode 不同）。skill 文件變更後須同步該副本，否則執行期讀到的是舊版。

## 7. DoD

1. 給定 `CLAUDE_PROJECT_DIR` 指向 A 目錄、`payload.cwd` 指向 B 工作區（B 為 A 的 git worktree），`run_hook()` 對 B 的 `run/`、`eval_state.json`、git index 套用 gate。
2. `payload.cwd` 位於工作區的**子目錄**時，仍解析到該工作區根（非子目錄）。
3. `payload.cwd` 不在 git 儲存庫內（或 `git` 不可用）時，退回 `CLAUDE_PROJECT_DIR`，行為與現行一致。
4. `payload` 無 `cwd` 欄位時（舊版／非預期輸入）不拋例外，退回現行行為。
5. 主工作區情境（`CLAUDE_PROJECT_DIR` == `payload.cwd`）行為與修改前完全一致。
6. 新增的端到端案例**必須被 `python3 -m unittest discover -s tests` 執行到**（即載體為 `tests/` 下的 Python 測試，非 shell script），且在套用修正前會失敗、套用後通過。

   **載體選擇的依據（前置 2.5 影響面盤點查證結果）**：`tests/check_worktree_isolation.sh` 全 repo 零執行呼叫者——無 `.github`／CI、無 `Makefile`、無任何 Python 測試以 subprocess 包裝它，僅由主 flow 手動重跑。若把新案例只加進該 `.sh`，DoD 7 的全套綠燈將**掩蓋新案例根本沒被執行**的事實。
7. 全套測試 `python3 -m unittest discover -s tests` 相對修改前基線（134 tests, OK）無新增失敗。
8. `skills/parallel-run/SKILL.md` 與 `skills/eval-flow/SKILL.md` 中「hook 在各 worktree 內獨立生效」的敘述已更正，且 `~/.claude/skills/` 副本已同步。

## 8. 非目標

- 不改變任何 gate 的**判定內容**（擋什麼、放行什麼的規則不動），只改「對哪個工作區判定」。
- 不改 `.claude/settings.json` 的 hook 註冊方式。
- 不處理 `~/.claude/skills/` 與 repo `skills/` 的副本機制本身（本 run 僅手動同步一次）。

## 9. 已知風險（詳見 risk/2026-07-28-gate-worktree-root.md）

`gate-check.sh` 每次呼叫都重新讀取 `eval_gates.py`，故本檔一經修改**立即對本 run 自身的後續 gate 生效**。修改若引入例外，將導致本 session 的 Bash／Agent 呼叫全面被擋。
