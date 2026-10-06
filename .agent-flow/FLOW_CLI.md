<!-- agent-workspace managed -->
# Flow 本地操作

在專案根目錄執行 `python3 .agent-flow/scripts/flow.py`。這個入口使用現有 manifest、事件與驗證腳本；agent 仍負責需求判斷、實作和獨立審查。

## 開始前檢查

```sh
python3 .agent-flow/scripts/flow.py preflight --harness codex --run-id <id> --json
python3 .agent-flow/scripts/flow.py preflight --harness codex --run-id <id> --live --timeout 30
```

首次尚未建立 manifest 時省略 `--run-id`；manifest 已存在時再指定。

靜態檢查涵蓋安裝檔案、模型設定、CLI、登入、工作目錄寫入和測試命令。測試命令只檢查入口，正式驗證由 `finish` 執行。模型來源是 `harnesses/models.json`，Codex 使用 `gpt-6.1-sol`。

`--live` 才啟動有時間上限的 Codex 模型探針。探針會使用模型用量，只驗證模型與登入；無工具呼叫的成功結果不能證明 hooks 已信任或已執行。設定存在與原生執行證據分開回報，未確認項目記為 `unknown`。

Claude 執行 `claude --version` 與 `claude auth status`，只記錄版本與登入是否通過，不輸出帳號資料；`--live` 同樣啟動 Claude 模型探針（每次預算上限 0.10 美元）。Claude 原生 CLI smoke 已於 2026-10-05 以 Claude Code 2.1.285 通過四個案例。退出碼：0 為 ready；1 為 blocked；2 為 unknown 或操作錯誤。靜態檢查有 unknown 時仍可讀取具體檢查結果。

`inputs-v2` 快照檢查內嵌 repository。一般未追蹤的內嵌 repository 只有在 Git 已批准的忽略範圍內才跳過；工具不自行修改 exclude。尚未排除時提前回報具體路徑，排除政策變動會使舊證據失效。已追蹤 gitlink／submodule 目前明確拒絕，須先解決工作目錄支援限制，不能以只記 HEAD 當作已驗證。既有 inputs-v1 與 legacy 紀錄沿用原格式。

## 查看進度

```sh
python3 .agent-flow/scripts/flow.py status --run-id <id>
python3 .agent-flow/scripts/flow.py status --run-id <id> --json
python3 .agent-flow/scripts/flow.py watch --run-id <id> --timeout 30 --interval 1
```

輸出包括紀錄狀態、task 步驟、耗時、失敗原因與下一個動作。省略 run ID 時只能自動選取唯一未完成的 run；有多個 run 時必須指定。紀錄的步驟表示執行意圖，不能當成 agent 仍在執行的證明。

`watch` 只在狀態改變時輸出，達到時間上限或 run 結束時退出。可用 Ctrl+C 停止監看。監看不會暫停工作，也不修改證據。

## worktree 連結

```sh
python3 .agent-flow/scripts/flow.py worktree-link
python3 .agent-flow/scripts/flow.py worktree-link --root <worktree 路徑>
```

工具鏈檔案不進專案 commit，所以新 worktree 一開始沒有 `.agent-flow/`、`.agents/`、`.claude/`、`retro/` 與 `CLAUDE.local.md`。PreToolUse 與 SessionStart hook 解析出 worktree 根之後，會自動補建相對 symlink 指回主工作區；缺哪個補哪個，已存在的路徑不動。`run/` 與 `task/` 是每個 run 的狀態，各 worktree 獨立，不建連結。

手動 `git worktree add` 建立的 worktree，或要在 worktree 內起新 session 恢復 run 之前，先在該 worktree 執行本指令。全部連結已存在時印「無需建立連結」；在主工作區執行不建任何連結。

## 獨立檢核資料

派 checker 前依 [REVIEW_PACKET.md](REVIEW_PACKET.md) 組裝資料包，標準派工使用 `dispatch.py task-verifier --review-packet <檔案>`。必要資料缺漏時先補齊，ready 只表示資料與來源有效，不代表審查通過；checker 保留四類升級判斷。

## 收尾

先完成獨立審查並記錄憑據，再只 stage 本次工作的檔案。

```sh
git add -- src/example.py tests/test_example.py
python3 .agent-flow/scripts/flow.py finish --run-id <id> \
  --message 'Implement example' --files src/example.py tests/test_example.py \
  --verify-command 'python3 -m unittest discover -s tests'
```

`finish` 依序核對範圍與既有憑據、執行 `run_verify.py`、歸檔符合條件的 Tier 2 狀態、執行 `run_commit.py prepare`、Git commit 與 finalize。它不替使用者填入審查通過或測試通過旗標，也不自動 stage 檔案。Tier 1 的驗證命令應選累積相關測試；Tier 2 使用完整測試命令。

有額外 staged 檔、範圍內未 stage 修改、其他 run 的熱狀態、未完成審查或驗證失敗時停止。錯誤保留原始輸出，已有現場與證據保留。提交訊息自動加入唯一的 `Run-Id` trailer。

明確加上 `--reuse` 才嘗試沿用本 run 中命令、輸入與環境相同的本地成功驗證；不符合時重跑。若 commit 已成功而 finalize 中斷，重跑同一指令會核對提交後補 finalize，避免重複 commit。

明確加上 `--push` 才推送至目前分支的 `origin` 遠端；不使用 force。完成後 push 失敗，可重跑帶 `--push` 的指令。同一 Git repository（含 worktree）同時只允許一個 finish；程序中斷留下的鎖須先核對程序已停止再處理。

本版提供 `preflight/status/watch/review-packet/worktree-link/finish`。需求分級與 run 初始化沿用 Router；工作暫停與恢復沿用 eval-flow-resume，尚未提供 `start/pause/resume` 命令。
