# agent_workspace

Agent 工作環境的設定模板。透過 `init.sh` 一鍵把 `CLAUDE.md`、subagents、skills 部署到目標位置，讓新 clone 下來的專案能快速接上既有的工作流程（包含 Eval Flow、task 管理、subagent 規範等）。

## 目錄結構

```
agent_workspace/
├── CLAUDE.md            # 專案規範（部署、DB、Eval Flow、task、subagent 原則）
├── .claude/
│   └── agents/          # subagent 定義（code-writer / code-reviewer / eval-scorer / retro / task-reviewer / task-verifier）
├── skills/              # 共用 skill 模板
│   ├── report-format/
│   ├── review-checklist/
│   ├── root-cause-table/
│   ├── task-checklist/
│   └── task-verify-checklist/
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
3. **同步 `skills/*`** 到 `~/.claude/skills/`
   - 同名資料夾**已存在 → 略過**（不覆蓋使用者既有的 skill）
   - 不存在 → 複製過去

腳本使用 `set -euo pipefail`，任一步驟失敗會立即中止並顯示錯誤。

## 部署位置對照表

| 來源（本 repo）            | 目標                                 | 既有檔案行為 |
| -------------------------- | ------------------------------------ | ------------ |
| `CLAUDE.md`                | `../CLAUDE.md`                       | 覆蓋         |
| `.claude/agents/*`         | `../.claude/agents/*`                | 覆蓋         |
| `skills/<name>/`           | `~/.claude/skills/<name>/`           | 略過         |

## 後續更新

- **更新 subagent 或 CLAUDE.md**：修改本 repo 後重跑 `./init.sh` 即可。
- **更新 skill**：因為 `init.sh` 對既有 skill 採「略過」策略，要更新 `~/.claude/skills/<name>/` 必須手動刪除目標資料夾後再執行 `./init.sh`，避免不小心覆蓋使用者本地的客製化內容。
