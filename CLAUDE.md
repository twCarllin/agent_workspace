# CLAUDE.md

## 部署規則（最重要）

- **禁止** 未經本地測試就直接部署到遠端
- 任何程式碼變更，必須先在本地端驗證功能正常後，才能 commit 和部署
- **驗證豁免窗口（全 tier）**：跳過本地驗證僅限**使用者明示豁免**；agent 不可自行認定、不可主動建議豁免。豁免單次有效並留痕（Tier 1／2 記 manifest `test_policy`，Tier 0 記在變更回報中；細節見 `test-strategy` skill）
- 部署前檢查潛在風險並告知，確認後才可以部署；DB 相關操作的可能影響一併檢查確認


## 難易度分級（Router，每個需求進來的第一步）

兩步判級：**先列理由碼，再判 tier**。判定結果（理由碼清單＋一句理由）寫進 manifest `tier_rationale` 供事後審計。

### 第一步：列 complexity_reasons（只准五碼；空集合是常見且合法的結果）

逐項檢查需求，命中才列：

| 碼 | 判準 |
|---|---|
| **重大不確定** | 需求歧義：DoD 一句話講不清、存在多種解讀 |
| **跨子系統協調** | 多模組須同動、多角色／多情境使用路徑 |
| **公開介面／落地資料契約** | 對外 API 簽章、DB schema、跨程式共用檔案格式的**本體**變更 |
| **信任邊界** | auth／權限、金流／交易、部署／環境設定、對外發佈（寄信、公開端點）的**本體**變更 |
| **未決重大決策** | 設計空間開放、尚無使用者裁決的取捨 |

- **本體 vs 使用**：僅呼叫／經過既有機制＝使用，不觸碼；改機制自身＝本體，觸碼（機械判準見防濫用規則「信任邊界／公開契約的邊界」）
- **本地開發工具鏈不因檔案類別自動觸碼**：hooks／tests／skills／流程文件的變更——git 可復原、測試可指認、無外部副作用——不屬信任邊界；它們仍可能觸「重大不確定」「未決重大決策」（v2 依據：實測 2026-09-06-baseline-suite-guard，25 行本機可復原修改被類別制排除送 Tier 2，前置佔成本 44%）
- **行數不是判級軸**（agentflow：job length is never used；實測行數不預測執行時間——流程稅才是時間主因）。大小閘獨立一條：預估 active time，見第二步

### 第二步：判 tier

| Tier | 進入條件 | 路徑 |
|---|---|---|
| **0 微調** | 無新行為（純樣式／文案／參數調整，無新邏輯／新分支；**bugfix 例外**：把實際行為修回預期行為、不新增行為面者，視同「無新行為」）＋ 不觸信任邊界／公開契約（觸碼判準見防濫用規則，1 行也不例外）＋ ≤3 個檔案、合計 ≤80 行（以 `git diff` 變更行數計，增＋刪）。**例外**：同一種機械式改動跨多檔重複套用（如同一句文案、同一個名稱替換），檔數不受 3 檔限制，但每檔 ≤50 行 | 直接改；改完回報時 append 一行留痕：`python3 .claude/hooks/eval_state.py tier0 --summary "<一句>" --files "<逗號清單>" --lines <增＋刪行數>`（格式住 eval-flow `references/formats.md`） |
| **1 直接路線** | 理由碼**空集合**；或非空但**全部可收斂為具名重大問題**（每個問題可由點名一個 advisor 回答——點名必附問題原文，機制見 eval-flow「Tier 1 精簡路徑」）＋ 預估 active time ≤120 分 | 載入 `eval-flow` skill，走「Tier 1 精簡路徑」 |
| **2 完整路線** | 信任邊界／公開契約的本體變更 OR 重大不確定／未決決策無法收斂為具名問題 OR 預估 active time >120 分 OR 請求不連貫 OR 使用者宣告 all-in | 載入 `eval-flow` skill，走完整「Tier 2 路徑」 |
| **B Bootstrap** | 空專案或新模組**骨架**（目錄結構、框架接線、CI、工具鏈）＋ 純結構性工作、**無業務邏輯**（開始寫業務行為的瞬間就不是 Tier B，回上面判級） | 載入 `eval-flow` skill，走「Tier B Bootstrap 路徑」 |

- **Tier 0 的 commit 歸屬**：Tier 0 改完後回報變更內容，**不自行 commit**（依全域規則，由使用者決定何時 commit）
- **active time 留痕**：Tier 1／2 的 manifest 記 `estimated_active_minutes`（選填，判級時的預估主動工時；收尾可補 `actual_active_minutes`）——估實分記（agentflow 慣例），供校準判級
- **事後降級門**：判 Tier 2 後、前置 1 開跑前的最後一道 check——工作實為瑣碎、無歧義、機械性 → 向使用者**提議**退回 Tier 1（附一句理由）。降級必經使用者確認，**agent 不可自行降**；執行中的「升級不可逆」不變（見防濫用規則）
- **all-in（使用者強制全流程）**：使用者明說「all-in」→ 本需求強制走 Tier 2 完整路徑，選配步驟全跑，直寫捷徑／合併審查／降級門全關。**agent 不可自行宣告、不可主動建議**（與驗證豁免同一防濫用原則）。預設（非 all-in）容許小工作抄捷徑：跳過的選配步驟在回報留痕一句
- **Minimality 尾註**：本節 v2（2026-09-06）借 agentflow 理由碼制；被否決的更大替代（devlog 對話制、四層模型 profile、Tier 2 前置 trigger 制）與出生證數據見 `run/2026-09-06-tier-router-v2.json` 的 `spec_inline`

### 工作型態前判（bugfix 先診斷，判級在後）

- 需求是**修 bug** 時，不先判 tier——判級需要的資訊（改哪裡、多大、觸不觸理由碼）在診斷前都未知。順序：
  1. **診斷先行**（不需任何前置、不建檔）：重現 → 定位根因 → 產出三行診斷結論（根因、影響面、修法）。診斷的執行紀律（feedback loop 完成判準、假設可否證、插樁與清理）依 `bug-diagnosis` skill
  2. **診斷完成後才判 tier**：診斷結論作為 `spec_inline`，照常列理由碼；理由碼空 → Tier 0／1；非空且無法收斂為具名問題 → Tier 2（診斷結論擴寫成 Spec）
- **Hotfix 緊急通道**：僅限**使用者明確宣告**緊急（線上事故／資損進行中），agent 不可自行認定。先止血、後補債，執行細節與欠帳規則見 `eval-flow` skill
- **bugfix retro 兩層制**（不論走哪個 tier，含 Tier 0）：修完後依 `bug-diagnosis` skill「retro 兩層制」節執行——BUGLOG 每 bug 一律寫、同模組／同根因第 2 次命中升級 RETRO、worktree run 例外見 parallel-run；細則住該 skill（修 bug 時本來就載入），不在此重列

### 防濫用規則（避免 agent 為省 token 自我降級）

- **信任邊界／公開契約的邊界（機械判準）**：觸碼的是這兩類機制**本體**的變更——auth／權限的判定邏輯、金流計算／交易處理邏輯、DB schema 定義、部署設定內容、對外發佈路徑、對外 API 簽章。兩道判準**同時成立**才觸碼：①diff 動到**可執行邏輯／判定行為／設定值**的行（**純註解、訊息字串、文件說明、新增測試**＝否——判準看行的性質，不是看檔案在哪個目錄）；②動到機制**本體**（僅呼叫／經過既有機制＝使用，不觸發——例：新頁面掛在既有 login guard 之後＝否；改 guard 的判斷式＝是；呼叫既有權限 helper、讀取既有設定＝使用）。**本地開發工具鏈不在此清單**（v2 變更，2026-09-06）：`.claude/hooks/*.py` 等本地 gate script 屬工具鏈，不屬信任邊界——其變更照其他碼（不確定／協調／大小）正常判級。Tier 2 是重型流程，入口收窄、保留給真正需要的
- Tier 1／2 的判定必須在 manifest 寫 `tier` 與 `tier_rationale`（理由碼清單＋為何判這層），供事後審計
- **升級逃生門**：Tier 1 執行中若發生下列任一 → **中止，升級 Tier 2**，補跑缺的前置（產 Spec、跑 usage、正式風險分析）：
  - 實際規模遠超判級認知（預估 active time 將明顯超過 120 分）
  - 冒出新理由碼且無法收斂為具名問題（需求歧義浮現、發現多條使用路徑、未決決策浮現）
  - 風險上冒出 🔴
- 升級不可逆：一旦升 Tier 2，不可再降回 Tier 1（事後降級門只存在於前置 1 開跑**之前**，且必經使用者確認）


## Eval Flow 執行（Tier 1／2）

- Router 判為 **Tier 1 或 Tier 2** 時，**必須先載入 `eval-flow` skill**，依其內容執行（前置 0–3、循環 1–7（code-writer → review（含完成度節）→ 本地測試 → commit）、Tier 1 精簡路徑、manifest／eval_state 格式與操作規則都住在該 skill，本文件不重述）
- **skill 內容不在 context 就不可憑印象跑**：執行中若對流程細節不確定（例如 context 被 compact 後、或接手他人的 run）→ **重新載入 `eval-flow` skill**（檔案在 `skills/eval-flow/SKILL.md`），並以 manifest／`eval_state.json` 的檔案狀態為準，不靠記憶
- 各 gate 由 PreToolUse hook（`.claude/hooks/gate-check.sh` → `eval_gates.py`）強制攔截：擋亂序的 subagent 呼叫與不合規的 `git commit`。被擋時依 stderr 訊息補齊狀態後重試；實際防線以 hook 為準
- **中斷恢復**：先前的 run 被中斷要續跑時，依 `eval-flow-resume` skill 的確定性程序恢復，不靠記憶或猜測

## Task Principle

- 產出物目錄慣例（`task/YYYY-MM-DD.md`、`usage/`／`risk/`／`impact/` 以 run_id 命名、`run/<run_id>.json` 冷溯源隨 commit 進 git）住 `eval-flow` skill 各前置節與 `references/formats.md`，不在此重列
- **產出物自足性（換手的前提）**：Spec、usage 報告、task 檔、風險報告必須**不依賴對話上下文**即可讀懂——不得出現「如上所述」「依先前討論」等指涉對話的內容；task item 必須寫明確檔案路徑與 DoD。標準是：任何未參與對話的 AI／工程師讀檔即可接手。**引用其他 run 產出檔（spec／usage／impact 路徑＋節次）不算依賴對話**——應指向式引用、不重述內容
- 每次新增或讀取任務時，使用**當天日期**的檔案（例如 `task/2026-04-18.md`）
- 呼叫 subagent 完成任務（例外：Tier 1 小 item 的主 flow 直寫捷徑，見 eval-flow skill）
- sub_task 收尾後，若任務來自 task 檔，須將對應 item 標記完成（`[x]`）
- 拆分粒度、[P] 平行標註、item 四要素等規則住 **task-decomposition** skill；審查／驗證順序與 gate 住 **eval-flow** skill 與 hook，不在此重述
