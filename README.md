# agent_workspace

Agent 工作環境的設定模板。透過 `init.sh` 一鍵把 `CLAUDE.md`、subagents、skills 部署到目標位置，讓新 clone 下來的專案能快速接上既有的工作流程（包含 Eval Flow、task 管理、subagent 規範等）。

## 目錄結構

```
agent_workspace/
├── CLAUDE.md            # 專案規範（部署、DB、Eval Flow、task、subagent 原則）
├── .claude/
│   ├── agents/          # subagent 定義（code-writer / code-reviewer / eval-scorer / retro / task-reviewer / task-verifier / usage-analyzer / task-decomposer）
│   ├── hooks/           # gate 強制腳本（gate-check.sh + eval_gates.py）
│   └── settings.json    # PreToolUse hook 設定
├── skills/              # 共用 skill 模板
│   ├── report-format/
│   ├── review-checklist/
│   ├── root-cause-table/
│   ├── task-checklist/
│   ├── task-decomposer/
│   ├── task-risk-analysis/
│   ├── task-verify-checklist/
│   └── usage-scenario-analysis/
└── init.sh              # 安裝腳本
```

## 使用方式

把這個 repo clone 到 **真正工作目錄的子目錄**（因為 `init.sh` 會把檔案部署到「上一層」），然後執行：

```bash
./init.sh
```

例如，如果你的工作專案在 `~/work/my-project/`，把 `agent_workspace` clone 到 `~/work/my-project/agent_workspace/`，再執行 `./init.sh`，檔案就會被部署到 `~/work/my-project/`。

## init.sh 做什麼

1. **複製 `CLAUDE.md`** 到上一層目錄（覆蓋既有檔案）
2. **複製 `.claude/agents/*`** 到上一層的 `.claude/agents/`（目錄不存在會自動建立）
3. **複製 `.claude/hooks/*`** 到上一層的 `.claude/hooks/`（gate 強制腳本，覆蓋既有檔案）
4. **部署 hook 設定** 到上一層的 `.claude/settings.json`
   - 不存在 → 直接複製
   - 已存在 → 只合併寫入 `hooks.PreToolUse`（其他鍵不動；已有相同 entry 則跳過，重跑冪等）
5. **同步 `skills/*`** 到 `~/.claude/skills/`
   - 同名資料夾**已存在 → 略過**（不覆蓋使用者既有的 skill）
   - 不存在 → 複製過去

腳本使用 `set -euo pipefail`，任一步驟失敗會立即中止並顯示錯誤。

## Gate 的硬性執行（hooks）

CLAUDE.md 裡的關鍵 gate 不只靠文字約束，由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，matcher `Bash|Task|Agent`）硬性攔截。攔截點有二：`git commit`（gate 1–4）與 subagent 呼叫（gate 5）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔）
2. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `completed` → 擋
3. **測試 gate**：對應的 `run/<run_id>.eval.json` 未同批 staged、或任一 sub_task 非 `passed`／`local_test_passed` 非 `true` → 擋
4. **不變量驗證**：扣分總和 ≠ `10 − quality_score`、或歸檔檔 `run_id` 與 manifest 不一致 → 擋
5. **phase 狀態機**：manifest 的 `phase`（`init → risk_done → usage_confirmed → decomposed → completed`）未達該 agent 的最低要求 → 擋 subagent 呼叫。usage-analyzer 需 `risk_done`、task-decomposer 需 `usage_confirmed`、code-writer / eval-scorer 需 `decomposed`；另附帶欄位檢查（`usage_report_path`／`task_file` 非空、無 blocking 風險、in_progress sub_task 的 `local_test_passed`）

被擋時 hook 以 stderr 回報原因（exit 2）。也可獨立自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。hook 只攔 Claude 的 Bash 工具，不影響使用者自己終端的 git 操作；部署後需重新載入 Claude Code session 才生效（首次會請使用者確認信任 hook）。

## 部署位置對照表

| 來源（本 repo）            | 目標                                 | 既有檔案行為 |
| -------------------------- | ------------------------------------ | ------------ |
| `CLAUDE.md`                | `../CLAUDE.md`                       | 覆蓋         |
| `.claude/agents/*`         | `../.claude/agents/*`                | 覆蓋         |
| `.claude/hooks/*`          | `../.claude/hooks/*`                 | 覆蓋         |
| `.claude/settings.json`    | `../.claude/settings.json`           | 合併（只加 hooks.PreToolUse） |
| `skills/<name>/`           | `~/.claude/skills/<name>/`           | 略過         |

## 後續更新

- **更新 subagent 或 CLAUDE.md**：修改本 repo 後重跑 `./init.sh` 即可。
- **更新 skill**：因為 `init.sh` 對既有 skill 採「略過」策略，要更新 `~/.claude/skills/<name>/` 必須手動刪除目標資料夾後再執行 `./init.sh`，避免不小心覆蓋使用者本地的客製化內容。
