# Task — worktree.baseRef 設為 head  (created: 2026-07-30)

> run_id: `2026-07-30-worktree-baseref`（Tier 1 精簡路徑）。需求原文見 manifest 的 `spec_inline`。
> **判級留痕**：Router 機械判定為 Tier 2（`settings.json` 設定值變更），**由使用者明示裁示降為 Tier 1**，非 agent 自行降級。詳見 manifest 的 `tier_rationale`。
> 現行全套測試基線：`python3 -m unittest discover -s tests` → **162 tests, OK**。

## 背景（自足，不依賴對話）

`Agent` 工具的 `isolation: "worktree"` 會由 harness 建立 `.claude/worktrees/agent-<id>/`。其 base ref 由 `worktree.baseRef` 設定決定：`fresh`（預設）從 `origin/<預設分支>` 切出、`head` 從當前本地 HEAD 切出。

**現況問題**：預設 `fresh` 使 worktree 少掉主線上尚未 push 的 commit。2026-07-30 兩批並行都必須靠 agent 起手 `git merge main` 才能取得正確前提——第一批的 Run A 進場時若未同步，會在「repo 有 13 個 skill」這個前提不成立的情況下開始工作。

## 前置實測（已於本 run 開工前完成，結論可直接引用）

1. **設定位置**：頂層 `"worktree": { "baseRef": "head" }`（`claude-code-guide` 依官方文件 `settings.md` / `worktrees.md` 確認）。
2. **設定層級**：專案 `.claude/settings.json` 為進版控、團隊共享的層級（優先序：Managed > Local > **Project** > User）。
3. **生效時機＝即時，不需重啟 session**（**實測，非推測**）：官方文件未記載此設定的生效時機，故以探測確認——在 `.claude/settings.local.json` 暫設 `baseRef: head`、於 `main` 建一個未 push 的拋棄式 commit（`d599d20`，含 `PROBE_MARKER.tmp`），派 `isolation: "worktree"` 探測 agent 回報其起點：
   ```
   d599d20 PROBE: 拋棄式 commit（worktree.baseRef 探測用，測完立即 reset）
   MARKER 存在
   ```
   即 worktree 從主線本地 HEAD 切出、含未 push 的 commit。探測後已 `git reset --hard` 移除該 commit、還原 `settings.local.json`、`main` 回到 `03a8d79` 與 origin 一致。

## 設計決定：`git merge main` 那步**保留不移除**

`baseRef: head` 生效後，`parallel-run` 起手三步的第②步（`git merge main`）在正常情況下是 no-op（fast-forward 到同一個 commit，零成本）。但**不移除**，理由：

- 設定未套用時（他人 clone 未 pull 到、設定被改、未來 harness 行為變動），該步是**唯一**會攔下「worktree 靜默落後主線」的地方
- 代價不對稱：保留的代價是一次 no-op；移除而設定又沒生效的代價是 agent 帶著錯誤前提做完整個 run

故改寫的是**理由**不是機制：從「必須（因為 worktree 從 origin 切出）」改為「確認同步（`baseRef: head` 下通常已是最新；若設定未套用或未生效，這是唯一攔截點）」。

## 明確不做的事（scope 邊界）

- 不改 `.claude/settings.json` 既有的 `hooks` 設定（新增鍵，不覆寫）
- 不移除 `parallel-run` 起手三步的任何一步
- 不改 `.claude/settings.local.json`（使用者本機層，非版控）
- 不改任何 hook 邏輯、agent 定義、測試
- 不設定 `cleanupPeriodDays` 或其他 worktree 相關設定（超出本需求；locked worktree 的清理是另一件事）

## Task 1: 設定與文件

- [x] 1.1 `.claude/settings.json` 加 `worktree.baseRef: "head"` ＋ `parallel-run` 起手第②步理由改寫 ＋ 部署副本同步  ~15 行  files: `.claude/settings.json`, `skills/parallel-run/SKILL.md`
      DoD（機械可驗）:
        1. `python3 -c "import json;d=json.load(open('.claude/settings.json'));print(d['worktree']['baseRef'])"` → `head`（且檔案為合法 JSON）。
        2. **既有 hooks 完整保留**：同一指令讀 `d['hooks']['PreToolUse'][0]['hooks'][0]['command']` → `$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh`。
        3. **端到端實測（配對對照，設定改在 Project 層後重驗，不沿用前置以 Local 層取得的結論）**——三項方法論要求缺一不可，皆為 code-reviewer 於本 run 指出的假陽性防線：
           - **前置斷言**：探測前確認 `main` == `origin/main`，建立拋棄式 commit 後確認 `git merge-base --is-ancestor <commit> origin/main` 為假（即 `origin/main` 不含該 commit）。否則 `fresh` 也會看到它。
           - **正向組**（`baseRef: head`）：派 `isolation: "worktree"` 探測 agent，其 `git log --oneline -1` **必須是**該拋棄式 commit、marker 檔存在。
           - **負向組（不可省）**（`baseRef: fresh`）：同一拋棄式 commit 存在下，把設定臨時改為 `fresh` 再派一次探測，**必須看不到**該 commit。**理由**：`git worktree add -b <branch> <path>` 不指定 start point 時原生即以當前 HEAD 為基，故只做正向無法區分「`baseRef: head` 生效」與「harness 未讀懂該鍵、fallback 到 git 原生行為」——兩者現象相同。唯有「head 看得到 ∧ fresh 看不到」成對成立，才坐實是這個鍵在起作用。
           - **探測 agent 的指示必須明訂**：`git log` 為**第一條**指令，且**禁止**先執行 `git merge`／任何改變 HEAD 的操作。否則 `parallel-run` 起手三步的第②步 `git merge main` 會把拋棄式 commit fast-forward 進 worktree，即使 `fresh` 也造成假陽性。
           - 測畢以 `git reset HEAD~1`（**mixed，不可用 `--hard`**——工作區有本 run 未提交的變更，`--hard` 會一併銷毀）還原，刪除 marker，並驗證「工作區 == index == `head`」與 `main` == `origin/main`。
        4. `skills/parallel-run/SKILL.md` 起手三步第②步的敘述已改為「確認同步」語義，且**該步仍存在**（`grep -c "git merge main"` 不得減少為 0）。
        5. 部署副本同步：`diff skills/parallel-run/SKILL.md ~/.claude/skills/parallel-run/SKILL.md` 空輸出。
        6. `python3 -m unittest discover -s tests` → `Ran 162 tests ... OK`。
        7. `python3 .claude/hooks/doctor.py` → 健檢通過（其中 `settings.json PreToolUse 含 gate-check` 一項可反向佐證 DoD 2）。
      情境: 並行 worktree 的起點對齊
      備註: DoD 3 是本 item 的核心——前置實測是在 `settings.local.json`（Local 層）取得的，本 item 把設定放在 `.claude/settings.json`（Project 層），**是不同的設定檔與解析路徑**，不可沿用前置結論，必須重驗。此即今日 RETRO 新增約束（跨進程／跨工作區的執行契約，DoD 須含一次真實端到端執行的證據）的直接適用。
