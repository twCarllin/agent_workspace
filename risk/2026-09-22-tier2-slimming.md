# 風險分析報告 — 2026-09-22-tier2-slimming

- **Spec**：`spec/2026-09-22-tier2-slimming.md`
- **執行條件**：理由碼含「公開介面／落地資料契約」（manifest `phase` 值域與兩個 path 欄位語義變更）→ 依 eval-flow 前置 1 執行條件，本步必跑
- **分析時間**：2026-09-22

**不適用：安全、資料、效能**

三者的不適用理由（依規則須列名，不得只是略過）：

- **安全**：本 run 不處理使用者輸入、不碰驗證／授權判定、不接觸密碼／token／PII、不新增環境變數或 API key。變更標的全為本機開發工具鏈（skill 散文、agent 定義、hook gate script、測試）。註：Spec §5 Q1 討論的「security pass」是**流程步驟的安置位置**問題，屬業務與維護面，不是本專案自身的安全漏洞面。
- **資料**：無 DB、無 migration、無 schema。本 run 觸及的「資料契約」是 JSON manifest 的欄位語義，屬本機檔案格式，已列入業務與維護面的向後相容評估，不在本面向重複計。
- **效能**：無查詢、無迴圈熱路徑、無資料規模成長假設。hook script 在每次 `git commit` 與 subagent 呼叫時執行一次，本次變更只減少判定分支、不增加；`stats.py` 掃描量不變。

---

## 1. 技術風險

### 🟡 mid-flight 自我修改：本 run 改的正是管轄本 run 的 gate

本 run 會修改 `.claude/hooks/eval_gates.py` 的 `PHASES` 與 `AGENT_MIN_PHASE`，而同一份 script 正在以 PreToolUse hook 攔截本 run 自己的 subagent 呼叫與 commit。改完即生效，後續步驟會落在新舊混合的判定下。

**對策**：
- 實作順序硬性規定為「文件 → agent 定義 → 測試 → hook script **最後**」。hook 改完後本 run 只剩 step 6 收尾，暴露面最小
- hook 改動落地後，立刻以 `--validate` 模式與單元測試確認判定正確，再進收尾
- 本 run 的 manifest `phase` 在 hook 改動前就會推進到 `decomposed`（新舊值域共有），不受值域收斂影響

### 🟡 三個被刪機制的投放路徑散佈多檔，漏刪即成孤兒條文

`mine_log`、批前快照、審查落檔各自橫跨 skill 條文、agent 定義、hook、測試。R-007 的實測教訓是「為修枚舉缺口而開的 run 自己重演漏改」。

**對策**：每個被刪機制先 `grep -rn` 全 repo 出清單，逐條核銷；DoD 4 明列此驗收（`grep` 後僅剩刻意保留的歷史說明）。

### 🟢 無新技術、無新相依

純 Python 標準庫與既有 markdown，無第三方套件變更。

---

## 5. 部署風險

### 🟡 框架須重新部署到 10 個下游專案才會生效

`init.sh` 把 `CLAUDE.md`、`.claude/agents/*`、`.claude/hooks/*` 複製到各專案。本 run 改完後，未重跑 `init.sh` 的專案仍跑舊流程。更麻煩的是**混合狀態**：某專案的 hook 是舊版（phase 值域含 `risk_done`），但操作者手上的 skill 是新版（不再產生該 phase）。

**對策**：
- 向後相容做成雙向：新 hook 讀舊 phase 值可用（Spec §3.2 已列為硬性），且新流程不產生舊 phase 值，故舊 hook 讀新 manifest 時看到的 `init`／`decomposed`／`completed` 也都在舊值域內——雙向相容成立
- 收尾回報明列「需重跑 `init.sh`」，並以 `doctor.py` 作為部署健檢（DoD 6）

### 🟢 無 downtime、可 rollback

全部是 git 追蹤的文字檔，`git revert` 即可回退。本機測試 gate（`test_baseline.py check`）照常把關，符合「禁止未經本地測試直接部署」。

---

## 6. 業務與維護風險

### 🔴→🟡 降級：55 個既有 run 的 manifest 相容性

**初判 🔴**：`PHASES` 由 5 值收斂為 3 值後，`manifest_phase()` 與 `check_task_gate()` 內的 `PHASES.index(phase)` 對舊值 `risk_done`／`usage_confirmed` 會拋 `ValueError`。hook 拋例外時 **exit code 非 2**，等同 gate 靜默不套用——這正是 R-005 記載過的「失敗是靜默的」同型事故。55 個既有 run 全部受影響，且 `eval-flow-resume` 依賴這條路徑。

**降級依據**：此風險**可由 Spec 內修正**，不需縮小範圍或補前置條件——Spec §3.2 已把「舊值映射」列為硬性要求，DoD 2 已列為必須有測試坐實的驗收條件。依前置 1 判斷規則，🔴 的定義是「須先修改 Spec 才可往下」；Spec 已含對策，故降為 🟡 並帶入分拆備註。

**對策（帶入 item 備註）**：
- `manifest_phase()` 增加舊值映射表，`risk_done`／`usage_confirmed` → `init`
- 映射必須在 `PHASES.index()` **之前**發生，不可靠 try/except 兜底（吞例外會讓判定靜默走偏）
- 測試須以真實舊 manifest 形狀（取自既有 5 個 Tier 2 run 之一的欄位組合）驗證 `check_task_gate` 不拋例外

### 🟡 刪除前置 1 後，非邊界類 Tier 2 run 失去安全檢查點

現行邊界類理由碼會觸發「reviewer 直派全 diff 審」，但純「跨子系統協調」而入 Tier 2 者，刪掉前置 1 後就沒有任何安全面檢查。

**對策**：列為 Spec §5 Q1 交使用者裁決，不由 agent 自行選邊。裁決結果寫回 Spec 再進循環。

### 🟡 審查改 per-task 後，`review_reds` 的歸屬與既有統計不連續

`stats.py` 的 rework 率、升級率以 sub_task 為分母。粒度改變後，新舊 run 的分母定義不同，趨勢圖會有斷點。

**對策**：列為 Spec §5 Q2 交使用者裁決（改 `sub_tasks` 結構 vs 只改觸發粒度）。無論選哪個，`stats.py` 須能同時處理新舊兩種形狀，且收尾回報須註明統計斷點日期。

### 🟡 刪掉的防線有各自的出生證，刪除即是接受重開該失敗的風險

- 批前快照源自「外部專案實測誤升級 1 次」
- `mine_log` 稽核針對「改測試湊綠」的機器指紋
- 審查落檔源自 write-ahead 原則（中斷在 fixing 時整輪作廢）

**對策**：
- 批前快照：審查改 per-task 後 staging 以 task 為界，跨批污染的**成因**消失，屬「前提已變」而非「放棄防線」——此推論須在 skill 留一句依據
- `mine_log`：writer 的 mine 模式測試自驗**保留**，只停落檔與稽核；退路是 checker 仍核對「契約 row 逐條有對應測試斷言」，改測試湊綠仍會在該處露餡
- 審查落檔：中斷恢復能力下降是**已接受的代價**（D1 使用者裁示）。收尾回報須明說這一條，並在 `eval-flow-resume` skill 註明「審查輪中斷需重跑該輪」

### 🟢 對終端使用者無可見影響

本框架的「使用者」即開發者自己，變更以 CLAUDE.md 與 skill 文件溝通，無 UI、無對外 API。

---

## 結論

**無 🔴**（唯一的 🔴 候選已依 Spec 既有對策降為 🟡，降級依據見上）。可進入下一步。

🟡 清單（須帶入分拆時的 item 備註）：
1. 舊 manifest phase 值映射，映射須先於 `PHASES.index()`
2. 實作順序：文件 → agent → 測試 → hook script 最後
3. 三個被刪機制各自 `grep` 全 repo 核銷
4. Q1／Q2 交使用者裁決後才進循環
5. `stats.py` 須同時吃新舊 sub_task 形狀
6. 收尾回報須含：需重跑 `init.sh`、統計斷點日期、中斷恢復能力下降一條
