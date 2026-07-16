# agent_workspace

一套讓 AI agent（Claude Code）寫程式**可控、可審計**的工作流程模板。把規範（CLAUDE.md）、流程（skills）、防線（hooks）、subagent 定義打包在一個 repo，執行 `./init.sh` 就能部署到任何專案，讓 agent 照同一套紀律工作。

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

不是每個需求都值得跑完整流程——改一行文案就開規格書是浪費，但碰金流的改動跳過風險分析是災難。所以每個需求進來的第一步是**判 tier**：

| Tier | 什麼樣的需求 | 走什麼路 |
|---|---|---|
| **0** | 純樣式／文案／小 bugfix，不碰高風險面 | 直接改，不建任何檔 |
| **1** | 明確的小功能：一句話講得清驗收標準、單一使用路徑 | 精簡流程（跳過規格與情境盤點） |
| **2** | 有歧義、偏大、多情境，**或碰到 auth／金流／schema／部署任一項** | 完整流程 |
| **B** | 空專案骨架（目錄、CI、工具鏈），無業務邏輯 | Bootstrap 路徑 |

兩條反濫用規則撐住這個分級：**高風險面是硬性排除**（碰到就強制 Tier 2，agent 無裁量空間），以及**升級不可逆**（Tier 1 跑到一半發現變大、變模糊，只能升 Tier 2 補前置，不能降回來）。判級理由要寫進 manifest，事後可審計 agent 有沒有為了省 token 給自己降級。

### 2. 先收斂認知，再動手寫（Tier 2 的前置）

完整流程在寫任何 code 之前有四個前置步驟，順序是刻意的：

1. **初始化**：建立 run manifest（這次工作的溯源檔）
2. **風險分析**：先看這個需求會碰到什麼——有 blocking 風險就停在這裡，不浪費後面的工
3. **使用情境盤點**：從規格推「會被怎麼用」，把歧義集中成開放問題，**停下來等使用者確認**（HITL gate）——歧義在這裡解決，比寫完 code 才發現便宜一個數量級
4. **分拆 task**：拆成可驗收的小單位（每 task ≤5 item、每 item 約 ≤300 行），拆完經交付前自檢才開工

之後進入實作循環：**寫 → 審查 → 驗證完成度 → 本地測試 → 評分 → commit**。每個環節由不同的 subagent 負責（code-writer 不自己審自己的 code），測試 gate 的標準是「無新增穩定失敗」而不是「全綠」——存量的爛測試不該擋新工作，但你不能留下新的坑。

Bugfix 是例外：**先診斷、後判級**。因為判級需要的資訊（改哪、多大、碰不碰高風險）在找到根因之前都不知道。

### 3. 文件是說明，hook 才是防線

流程寫在文件裡，agent 就可能「忘記」或繞過。所以關鍵 gate 由 PreToolUse hook **確定性攔截**：亂序呼叫 subagent（前置沒跑完就開寫）、不合規的 `git commit`（測試沒過、歸檔沒做、留著欠帳開新工作）都會被硬擋，stderr 告訴 agent 缺什麼、怎麼補。三者有出入時，**以 hook 行為為準**。

同樣的邏輯：**狀態全在檔案，不在對話**。每個 run 的規格、風險報告、task 清單、manifest 都落地成檔，而且要求「不依賴對話上下文即可讀懂」——對話隨時可拋，中斷後照 `eval-flow-resume` 的程序從檔案還原現場，換一個 agent（或換一個人）接手也讀檔就能繼續。

### 4. 流程要能學習，也要能瘦身

- **學習**：每次 review 抓到的問題，由 retro agent 歸因寫進 `retro/RETRO.md`，下一輪直接貼進 code-writer 的硬性約束——同一個坑不踩第二次。
- **瘦身**：每個 run 留下結構化溯源，`stats.py` 彙總成指標（gate 命中率、HITL 打回率、評分的獨立貢獻…）。從不觸發的 gate、打回率趨近零的人工閘門，都是砍掉的候選。**沒有這些數字，流程只會單向長大**——每次出事加一條規則，最後把自己壓死。

## 怎麼套用到你的專案

1. 把本 repo clone 到**工作專案的子目錄**（`init.sh` 會往上一層部署）：

   ```bash
   cd ~/work/my-project
   git clone <this-repo> agent_workspace
   cd agent_workspace && ./init.sh
   ```

2. `init.sh` 做的事：CLAUDE.md／subagents／hooks 覆蓋部署到上一層，hook 設定合併進 `.claude/settings.json`（不動其他鍵、重跑冪等），skills 同步到 `~/.claude/skills/`（repo 為準強制覆蓋），RETRO seed 只在不存在時建立（**專案累積的教訓絕不覆蓋**）。

3. 重新載入 Claude Code session（hook 部署後才生效，首次會請你確認信任）。可跑 `python3 .claude/hooks/doctor.py` 健檢部署是否齊全。

之後的日常使用就是**把需求直接丟給 agent**——判級、走流程、被 gate 擋、補狀態，都是 agent 自己的事。你會被叫到的時機只有幾個：確認使用情境的開放問題（HITL gate）、決定何時 commit（Tier 0）、以及明示豁免本地驗證（agent 不可自行認定）。

後續更新：改本 repo 後重跑 `./init.sh` 即可全量覆蓋部署（skills 只覆蓋不刪除，移除的舊檔需手動清理目標端）。

## 想看細節

| 主題 | 位置 |
|---|---|
| 分級表全文、防濫用規則 | `CLAUDE.md` |
| 完整流程（前置 0–3、循環 1–8、manifest 格式） | `skills/eval-flow/` |
| 測試 gate（baseline、flaky 過濾、豁免窗口） | `skills/test-strategy/` |
| 中斷恢復程序 | `skills/eval-flow-resume/` |
| 多需求並行（worktree 隔離） | `skills/parallel-run/` |
| gate 攔截邏輯本體 | `.claude/hooks/eval_gates.py` |
| 遙測與健檢 | `.claude/hooks/stats.py`、`doctor.py` |
| gate script 的測試 | `tests/`（`python3 -m unittest discover -s tests`） |
