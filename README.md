# agent_workspace

Agent 工作環境的設定模板。透過 `init.sh` 一鍵把 `CLAUDE.md`、subagents、hooks、skills 部署到目標位置，讓新 clone 下來的專案能快速接上既有的工作流程（Router 難易度分級、Eval Flow、task 管理、subagent 規範等）。

## 目錄結構

```
agent_workspace/
├── CLAUDE.md            # 常駐規範（部署規則、Router 分級表、防濫用規則、task／subagent 原則）
├── .claude/
│   ├── agents/          # subagent 定義（code-writer / code-reviewer / eval-scorer / retro / task-reviewer / task-verifier / usage-analyzer / task-decomposer）
│   ├── hooks/           # gate 強制腳本（gate-check.sh + eval_gates.py）、測試 gate 判定端（test_baseline.py）、假測試 lint（test_lint.py）、eval_state 操作 helper（eval_state.py）、遙測彙總（stats.py）、部署健檢（doctor.py）、VERSION
│   └── settings.json    # PreToolUse hook 設定
├── skills/              # 共用 skill 模板
│   ├── eval-flow/           # Eval Flow 執行細節（前置、循環、Tier 1/B、hotfix、格式與 gate 清單）
│   ├── eval-flow-resume/    # 中斷恢復的確定性程序
│   ├── parallel-run/        # ≥2 個互不相依的 Tier 1 需求並行（worktree ＋背景 agent）
│   ├── eval-scoring/        # eval-scorer 的五維度評分基準
│   ├── report-format/
│   ├── review-checklist/
│   ├── root-cause-table/
│   ├── task-checklist/
│   ├── task-decomposition/
│   ├── task-risk-analysis/
│   ├── task-verify-checklist/
│   ├── test-strategy/       # step 5 測試 gate：baseline「無新增失敗」、flaky 過濾、豁免窗口
│   └── usage-scenario-analysis/
├── seed/                # 跨專案 seed（RETRO.seed.md 通用約束庫，部署時僅在目標不存在時建立）
├── tests/               # gate script 自己的測試（python3 -m unittest discover -s tests）
└── init.sh              # 安裝腳本
```

## 設計分層

- **CLAUDE.md（常駐）**：每個 session 全文載入，只放必須常駐的內容——部署規則、Router 分級表（Tier 0／1／2／B ＋ bugfix 診斷前判 ＋ hotfix 通道）、防濫用規則、一般性原則。
- **eval-flow skill（按需）**：Router 判為 Tier 1／2／B 時才載入，承載流程執行細節（前置 0–3、循環 1–8、manifest／eval_state 格式、操作規則、gate 清單）。抽離的目的是減少常駐 context；「skill 不在 context 就不可憑印象跑」的錨點規則留在 CLAUDE.md，hook 被擋時的 stderr 也會提示重新載入。
- **hooks（防線）**：文件是流程說明，實際防線是 hook 的確定性攔截（見下）。三者若有出入，以 hook 行為為準。
- **狀態全在檔案**：run manifest（`run/`，冷溯源）＋ `eval_state.json`（熱 scratchpad，含循環步驟 `step` 與檔案歸屬 `files` 的 write-ahead 記錄）。對話隨時可拋，中斷後依 `eval-flow-resume` skill 從檔案還原現場。
- **並行（parallel-run skill）**：並行的單位是 run、隔離的單位是 worktree——`eval_state.json` 與 git staging area 都是單例，同工作區並行必互相污染，故一個 worktree 只跑一個 run。**≥2 個互不相依的 Tier 1** 同時進來才並行：主 session 批次判級＋批次輕量 HITL 後，一需求一 worktree 一背景 agent 各跑 eval-flow（commit 限 feat branch、task 檔加 slug 防衝突），完成後彙整回報、經使用者確認再 merge 回 main。Tier 0 一律序列、單一 Tier 1 走原流程、Tier 2 不進並行（HITL gate 多，不適合背景）。並行省 wall-clock、不省 token（每 run 約 +10–20% 編排開銷）。

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
   - **一律以 repo 版本強制覆蓋**（repo 是 single source of truth，防止 skill 漂移）
   - 只覆蓋同名檔案、不做刪除；repo 中已移除的舊檔需手動清理
6. **seed RETRO** 到上一層的 `retro/RETRO.md`（跨專案通用約束庫）
   - **僅在檔案不存在時建立，絕不覆蓋**——專案累積的教訓是 retro agent 的產出，seed 只負責讓新專案不從零開始

腳本使用 `set -euo pipefail`，任一步驟失敗會立即中止並顯示錯誤。

## Gate 的硬性執行（hooks）

關鍵 gate 不只靠文字約束，由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`，matcher `Bash|Task|Agent`）硬性攔截。攔截點有二：`git commit`（gate 1–5）與 subagent 呼叫（gate 6–8）：

1. **歸檔 gate**：`eval_state.json` 尚存在 → 擋 commit（防跳過歸檔）
2. **intent gate**：staged 的 `run/<run_id>.json` 中 `spec_path` 與 `spec_inline` 皆空、或 `status` 非 `completed` → 擋
3. **測試 gate**：對應的 `run/<run_id>.eval.json` 未同批 staged、或任一 sub_task 非 `passed`／`local_test_passed` 非 `true` → 擋
   - **tier 豁免**：`tier: "hotfix"` 免歸檔檔但必須帶 `debt` 欠帳清單；`tier: "B"`（bootstrap）免歸檔檔但 `bootstrap_verified` 非 `true` 擋
4. **假測試 lint gate**：staged 有 manifest（flow 收尾 commit）時，staged 的 Python 測試檔跑 `test_lint.py`——if-guard 藏斷言／無斷言／恆真斷言 → 擋（誤報以行尾 `# testlint: allow` 豁免）
5. **不變量驗證**：扣分總和 ≠ `10 − quality_score`、或歸檔檔 `run_id` 與 manifest 不一致 → 擋
6. **phase 狀態機**：manifest 的 `phase`（`init → risk_done → usage_confirmed → decomposed → completed`）未達該 agent 的最低要求 → 擋 subagent 呼叫。usage-analyzer 需 `risk_done`、task-decomposer 需 `usage_confirmed`、code-writer / eval-scorer 需 `decomposed`；另附帶欄位檢查（`usage_report_path`／`task_file` 非空、無 blocking 風險、in_progress sub_task 的 `local_test_passed`）
7. **欠帳 gate**：任一 manifest 的 `debt` 非空（hotfix 遺留）→ 擋新 run 的 subagent 呼叫，直到補完 risk 分析／回歸測試／retro
8. **單一 run gate**：本工作區存在其他 in_progress 的 manifest → 擋（一個 worktree 同時只跑一個 run；並行開 `git worktree`）

被擋時 hook 以 stderr 回報原因（exit 2），並附「重新載入 eval-flow skill」的自癒提示。也可獨立自檢：`python3 .claude/hooks/eval_gates.py --validate eval_state.json`。hook 只攔 Claude 的 Bash 工具，不影響使用者自己終端的 git 操作；部署後需重新載入 Claude Code session 才生效（首次會請使用者確認信任 hook）。

## 遙測與健檢（讓系統看得見自己）

流程的每個 run 都在 `run/` 留下結構化溯源檔，`stats.py` 彙總成健康指標；gate 被攔截時 `eval_gates.py` 順手記一行到 `run/gate_hits.log`：

```
python3 .claude/hooks/stats.py     # tier 分佈、waive 率、HITL 打回率、rework 率、scorer 獨立貢獻、gate 命中
python3 .claude/hooks/doctor.py    # 部署健檢：hooks 齊全、settings 接上 gate、核心 skill 已部署、版本
```

指標的用法是**修剪**，不只是觀察：從不觸發的 gate、打回率趨近 0% 的人閘門、獨立貢獻趨近 0% 的 eval-scorer，都是降級或砍掉的候選——沒有這些數字，流程只會單向長大。`framework_version`（`.claude/hooks/VERSION`）隨 manifest 記錄，事後可鑑識「這個 run 在哪一版規則下跑」。

## 部署位置對照表

| 來源（本 repo）            | 目標                                 | 既有檔案行為 |
| -------------------------- | ------------------------------------ | ------------ |
| `CLAUDE.md`                | `../CLAUDE.md`                       | 覆蓋         |
| `.claude/agents/*`         | `../.claude/agents/*`                | 覆蓋         |
| `.claude/hooks/*`          | `../.claude/hooks/*`                 | 覆蓋         |
| `.claude/settings.json`    | `../.claude/settings.json`           | 合併（只加 hooks.PreToolUse） |
| `skills/<name>/`           | `~/.claude/skills/<name>/`           | 強制覆蓋（repo 為準） |
| `seed/RETRO.seed.md`       | `../retro/RETRO.md`                  | 僅不存在時建立（絕不覆蓋） |

## 後續更新

- **更新 subagent、CLAUDE.md 或 skill**：修改本 repo 後重跑 `./init.sh` 即可，全部以 repo 版本覆蓋部署。
- 注意：skills 的覆蓋不做刪除——若某 skill 資料夾內移除了檔案，目標端的殘留舊檔需手動刪除。
