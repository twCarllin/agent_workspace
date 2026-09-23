# agent_workspace

一套讓 Claude Code 與 Codex 寫程式**可控、可審計**的工作流程模板。Router、skills、gate 與角色職責由這個 repo 維護；Claude Code 用 `./init.sh` 部署，Codex 用 `./init.sh --p codex --target <專案路徑>` 部署。

## 要解決什麼問題

讓 agent 直接寫 code，常見的失敗模式是：

- **拿到需求就開寫**——需求有歧義沒先釐清，寫完才發現方向錯了
- **沒測試就說完成**——「應該可以動」和「驗證過可以動」被混為一談
- **為了省事自我降級**——該走完整流程的高風險改動，被 agent 自己判定成「小改」跳過檢查
- **狀態活在對話裡**——對話一被壓縮或中斷，做到哪、為什麼這樣做，全部蒸發
- **同樣的錯一犯再犯**——這次 review 抓到的問題，下次換個地方又出現

這個 repo 的做法：把「先想再寫、寫完要驗、驗完留痕、錯了要學」變成**結構性的強制**，而不是靠提示詞裡的一句「請仔細」。

## 四個設計原則

### 1. 投入跟風險成比例（Router 分級）

不是每個需求都值得跑完整流程——改一行文案就開規格書是浪費，碰金流機制本身的改動則需要完整審查。所以每個需求進來的第一步是**判 tier**：

| Tier | 什麼樣的需求 | 走什麼路 |
|---|---|---|
| **0** | 純樣式／文案／小 bugfix，不碰高風險面 | 直接改；收尾 append 一行 tier0 留痕（`eval_state.py tier0`） |
| **1** | 明確的小功能：一句話講得清驗收標準、單一使用路徑 | 精簡流程（跳過規格與情境盤點） |
| **2** | 理由碼含**信任邊界／公開契約的本體變更**、重大不確定或未決決策無法收斂、或預估 active time >120 分 | 完整流程 |
| **B** | 空專案骨架（目錄、CI、工具鏈），無業務邏輯 | Bootstrap 路徑 |

兩條反濫用規則撐住這個分級：**本體變更觸碼是硬性判準**（改 auth／金流／schema／部署機制本身就強制 Tier 2，agent 無裁量空間；只是呼叫既有機制、或改本地開發工具鏈，不因檔案類別自動觸碼），以及**升級不可逆**（Tier 1 跑到一半發現變大、變模糊，只能升 Tier 2 補前置，不能降回來）。判級理由要寫進 manifest，事後可審計 agent 有沒有為了省 token 給自己降級。

### 2. 先收斂認知，再動手寫（Tier 2 的前置）

完整流程在寫 code 前先完成：

1. **初始化**：建立 run manifest（這次工作的溯源檔）
2. **具名問題盤點**：需要情境或影響面資料時，提出具體問題並派 advisor；答案寫回 Spec
3. **分拆 task**：拆成可驗收的小單位；小範圍由主 flow 直接建立，較大範圍派 task-decomposer
4. **確認計畫**：提報 Spec 的開放問題與 task 計畫，留存使用者裁示

之後進入實作循環：**寫 → checker 核對憑據（必要時 reviewer 審 diff）→ 本地測試 → commit**。邊界類變更直接派 reviewer。測試 gate 的標準是「無新增穩定失敗」；新 run 的最後驗證另綁定程式樹快照，提交前若程式碼改變就重驗。

Bugfix 是例外：**先診斷、後判級**。因為判級需要的資訊（改哪、多大、碰不碰高風險）在找到根因之前都不知道。

### 3. 文件是說明，hook 才是防線

關鍵 gate 由工具 hook 攔截亂序派工與不合規的提交；Git `commit-msg` hook 再核對實際提交訊息。提交前 manifest 是 `ready_to_commit`，成功後才記 SHA 與 `completed`。三者有出入時，以 gate 行為為準。

**狀態全在檔案。** 每個 run 的規格、task 清單與 manifest 都可從檔案還原；中斷後依 `eval-flow-resume` 接手。

### 4. 流程要能學習，也要能瘦身

- **學習**：每次 review 抓到的問題，由 retro agent 歸因寫進 `retro/RETRO.md`，下一輪直接貼進 code-writer 的硬性約束——同一個坑不踩第二次。
- **瘦身**：每個 run 留下結構化溯源，`stats.py` 彙總 tier 分佈、gate 命中、HITL 裁示與執行成本，用實際資料審查流程步驟。

## 怎麼套用到你的專案

1. 把本 repo clone 到**工作專案的子目錄**（`init.sh` 會往上一層部署）：

   ```bash
   cd ~/work/my-project
   git clone <this-repo> agent_workspace
   cd agent_workspace && ./init.sh
   ```

2. `init.sh` 會部署 Claude 規則、subagents、hooks，並將 skills 同步到 `~/.claude/skills/`；RETRO seed 只在不存在時建立。

3. 重新載入 Claude Code session（hook 部署後才生效，首次會請你確認信任）。可跑 `python3 .claude/hooks/doctor.py` 健檢部署是否齊全。

Codex 安裝：在本 repo 目錄執行 `./init.sh --p codex --target /path/to/my-project`。安裝器將 Router 複製到 `.agent-flow/ROUTER.md`、skills 複製到 `.agents/skills/`、角色設到 `.codex/agents/`，並合併 `AGENTS.md` 與 `.codex/hooks.json`；Git 沒有既有 `commit-msg` hook 時安裝提交訊息 gate。重新開啟 Codex 後，在 `/hooks` 檢查並信任專案 hook 定義。

日常使用就是把需求交給 agent，依 Router 判級並走對應流程。Tier 1／2 提交前執行 `python3 .claude/hooks/run_commit.py prepare <run_id>`；成功 commit 後執行 `python3 .claude/hooks/run_commit.py finalize <run_id>`。

後續更新：改本 repo 後重跑 `./init.sh` 即可全量覆蓋部署（skills 只覆蓋不刪除，移除的舊檔需手動清理目標端）。

## 想看細節

| 主題 | 位置 |
|---|---|
| 分級表全文、防濫用規則 | `CLAUDE.md` |
| 完整流程與 manifest 格式 | `skills/eval-flow/` |
| 測試 gate（baseline、flaky 過濾、豁免窗口） | `skills/test-strategy/` |
| 中斷恢復程序 | `skills/eval-flow-resume/` |
| 多需求並行（worktree 隔離） | `skills/parallel-run/` |
| gate 攔截邏輯本體 | `.claude/hooks/eval_gates.py` |
| 遙測與健檢 | `.claude/hooks/stats.py`、`doctor.py` |
| gate script 的測試 | `tests/`（`python3 -m unittest discover -s tests`） |
