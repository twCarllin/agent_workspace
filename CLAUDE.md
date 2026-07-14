# CLAUDE.md

## 部署規則（最重要）

- **禁止** 未經本地測試就直接部署到遠端
- 任何程式碼變更，必須先在本地端驗證功能正常後，才能 commit 和部署
- **驗證豁免窗口（全 tier）**：跳過本地驗證僅限**使用者明示豁免**；agent 不可自行認定、不可主動建議豁免。豁免單次有效並留痕（Tier 1／2 記 manifest `test_policy`，Tier 0 記在變更回報中；細節見 `test-strategy` skill）


## 難易度分級（Router，每個需求進來的第一步）

先判 tier，再決定走哪條路。判定的軸不是「行數」，而是三道閘門保護的東西：**風險**（auth／金流／schema／部署）、**歧義**（需求清不清）、**大小**（會不會超過 1 task）。

| Tier | 進入條件（**全部**滿足） | 路徑 |
|---|---|---|
| **0 微調** | 無新行為（純樣式／文案／參數調整，無新邏輯／新分支；**bugfix 例外**：把實際行為修回預期行為、不新增行為面者，視同「無新行為」）＋ 不觸及高風險面（同 Tier 1 的排除清單，1 行也不例外）＋ 1~2 個檔案、每檔 ≤30 行（以 `git diff` 變更行數計，增＋刪）。**例外**：同一種機械式改動跨多檔重複套用（如同一句文案、同一個名稱替換），檔數不受 2 檔限制，但每檔仍 ≤30 行 | 直接改，不建任何檔 |
| **1 明確功能** | 需求無歧義（一句話講得清 DoD）＋ 單一使用路徑（單角色、無分支情境）＋ 預估 ≤1 task（≤5 items／各 ≤300 行）＋ **完全不觸及 auth／權限、金流／交易、DB schema 變更、部署／環境設定** | 載入 `eval-flow` skill，走「Tier 1 精簡路徑」 |
| **2 完整功能** | 以上任一不成立：有歧義 OR 偏大 OR 多角色／多情境 OR 觸及上述任一高風險面 | 載入 `eval-flow` skill，走完整「Tier 2 路徑」 |
| **B Bootstrap** | 空專案或新模組**骨架**（目錄結構、框架接線、CI、工具鏈）＋ 純結構性工作、**無業務邏輯**（開始寫業務行為的瞬間就不是 Tier B，回上面判級） | 載入 `eval-flow` skill，走「Tier B Bootstrap 路徑」 |

- **Tier 0 的 commit 歸屬**：Tier 0 改完後回報變更內容，**不自行 commit**（依全域規則，由使用者決定何時 commit）

### 工作型態前判（bugfix 先診斷，判級在後）

- 需求是**修 bug** 時，不先判 tier——判級需要的資訊（改哪裡、多大、沾不沾高風險面）在診斷前都未知。順序：
  1. **診斷先行**（不需任何前置、不建檔）：重現 → 定位根因 → 產出三行診斷結論（根因、影響面、修法）
  2. **診斷完成後才判 tier**：診斷結論作為 `spec_inline`；改動小＋不沾高風險面 → Tier 0／1；根因牽連廣或沾高風險面 → Tier 2（診斷結論擴寫成 Spec）
- **Hotfix 緊急通道**：僅限**使用者明確宣告**緊急（線上事故／資損進行中），agent 不可自行認定。先止血、後補債，執行細節與欠帳規則見 `eval-flow` skill
- **bugfix 一律輕量 retro**：不論走哪個 tier（含 Tier 0），修完後把根因寫一條進 `retro/RETRO.md`——每個 bug 都是上游流程漏洞的證據，不累積等於白修

### 防濫用規則（避免 agent 為省 token 自我降級）

- **高風險面是硬性排除，不是加權**：只要沾到 auth／權限、金流／交易、schema 變更、部署設定其中任一，**強制 Tier 2**，無裁量空間
- Tier 1／2 的判定必須在 manifest 寫 `tier` 與 `tier_rationale`（為何判這層），供事後審計
- **升級逃生門**：Tier 1 執行中若發生下列任一 → **中止，升級 Tier 2**，補跑缺的前置（產 Spec、跑 usage、正式風險分析）：
  - 分拆後超過 5 items（硬上限）
  - 出現預估遠超 300 行且無法在 ≤5 item 內合理消化的 item（在 Tier 1 情境下，代表這功能其實不小，應改走完整流程；非要求硬拆）
  - 冒出需求歧義（DoD 講不清、發現多條使用路徑）
  - 風險上冒出 🔴
- 升級不可逆：一旦升 Tier 2，不可再降回 Tier 1


## Eval Flow 執行（Tier 1／2）

- Router 判為 **Tier 1 或 Tier 2** 時，**必須先載入 `eval-flow` skill**，依其內容執行（前置 0–3、循環 1–8、Tier 1 精簡路徑、manifest／eval_state 格式與操作規則都住在該 skill，本文件不重述）
- **skill 內容不在 context 就不可憑印象跑**：執行中若對流程細節不確定（例如 context 被 compact 後、或接手他人的 run）→ **重新載入 `eval-flow` skill**（檔案在 `skills/eval-flow/SKILL.md`），並以 manifest／`eval_state.json` 的檔案狀態為準，不靠記憶
- 各 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`）強制攔截：擋亂序的 subagent 呼叫與不合規的 `git commit`。被擋時依 stderr 訊息補齊狀態後重試；實際防線以 hook 為準
- **中斷恢復**：先前的 run 被中斷要續跑時，依 `eval-flow-resume` skill 的確定性程序恢復，不靠記憶或猜測

## Task Principle

- 任務檔案放在 `task/` 資料夾，以日期命名：`task/YYYY-MM-DD.md`
- 使用情境報告放在 `usage/` 資料夾，以 run_id 命名：`usage/<run_id>.md`（比照 task 的專屬資料夾慣例）
- 風險分析報告放在 `risk/` 資料夾：`risk/<run_id>.md`（前置 1 產出即存檔）
- run manifest 放在 `run/` 資料夾：`run/<run_id>.json`（冷溯源，隨 commit 進 git）
- **產出物自足性（換手的前提）**：Spec、usage 報告、task 檔、風險報告必須**不依賴對話上下文**即可讀懂——不得出現「如上所述」「依先前討論」等指涉對話的內容；task item 必須寫明確檔案路徑與 DoD。標準是：任何未參與對話的 AI／工程師讀檔即可接手
- 每次新增或讀取任務時，使用**當天日期**的檔案（例如 `task/2026-04-18.md`）
- 舊的 `task.md` 僅作為歷史紀錄保留，不再新增任務到該檔案
- 呼叫 subagent 完成任務
- 標記任務創建時間
- 可以平行化的任務，標註為可以 [P] 代表可以平行化執行
- task 完成後，標記為 [x] 代表任務完成
- **task 檔案有新增任務後，必須呼叫 `task-reviewer` subagent 審查**，確認描述清楚、拆分合理、技術限制已標註，才可以開始執行任務
  - 拆分合理性依 **task-decomposition** skill 的上限審查（≤5 item 硬、≤300 行/item 軟等，細節見 skill），不在此重述
- **task 所有子任務完成後，必須呼叫 `task-verifier` subagent 驗證**，確認實作與描述一致，才可以 commit

## Subagent Principle

- 工作完成後，如果是從 task 檔案獲取任務，在 eval-score 完成後，要到對應的 task 檔案將任務標記為完成

## 部署準備

- 部署前檢查潛在風險並告知，確認後才可以部署
- 部署前檢查 DB 相關操作可能影響，確認後才可以部署
