---
name: test-strategy
description: Eval Flow step 5 本地測試 gate 的執行細節：baseline「無新增穩定失敗」機制（script 判定）、flaky 過濾、失敗四分類決策樹、兩次舉手上限、相關測試選擇、commit 前全套檢查與重開 passed sub_task 的路徑、零測試專案處置、全 tier 驗證豁免窗口。觸發語：Eval Flow 循環進入 step 5 時、「測試失敗怎麼辦」、「建測試 baseline」。不適用於：測試框架選型（Tier B bootstrap 的 HITL 決定）、eval 評分（走 eval-scoring）。
---

# Test Strategy（本地測試 gate 執行細節）

> 核心原則：**測試是 pipeline 的護欄，不是路障**——gate 擋的是「你新弄壞的東西」，不是「專案裡所有壞掉的東西」。gate 條件不是「全綠」，而是「**無新增穩定失敗**」。
> 判定一律由 script `.claude/hooks/test_baseline.py` 執行（baseline 比對、flaky 過濾、失敗計數都是確定性邏輯，**不留給模型憑感覺判**）；本文件規範何時跑、結果怎麼處置。

## Baseline（run 的測試基準，第一次 step 5 前建立）

```
python3 .claude/hooks/test_baseline.py baseline
```

- **全套測試指令從 manifest 的 `test_command` 讀**（single source of truth；`--cmd` 僅供覆寫）。manifest 尚無此欄時，先確認指令並寫入 manifest 再跑——不要每個 run 各猜一套，baseline 與 check 範圍不一致就會出現「無關的既有失敗」
- 預設**跑兩次**：兩次都失敗 → `stable_failures`（既有壞測試）；只失敗一次 → `flaky`。兩者之後都不擋 gate——用兩次交集換 baseline 不被 flaky 汙染
- 寫入 `run/<run_id>.test_baseline.json`（`run_id` 自動讀 `eval_state.json`）。此檔隨 commit 進 git，`stable_failures` 就是本 run 進場時的**既有欠帳快照**
- **既有壞測試 = 記錄級欠帳，不是攔截級**：與 hotfix `debt` 不同——不擋新 run、本 run 不修（修它是 scope 偏移），但 retro 時彙報數量與清單，讓債看得見
- 無任何測試框架的專案不建 baseline，改走「零測試專案」節

## Step 5 執行順序（每個 sub_task）

1. **選相關測試**（範圍分層：逐 sub_task 只跑相關的，快、歸因清楚）：
   ```
   python3 .claude/hooks/test_baseline.py related --files <本 sub_task 的 files 清單>
   ```
   script 用「測試檔命名慣例 + grep 引用」找；**輸出只是候選起點**，agent 要補上：本 sub_task 新寫的測試 item、以及改到 shared module 時自己判斷的追加範圍。寧可多選不可少選
2. **跑 gate 判定**：
   ```
   python3 .claude/hooks/test_baseline.py check --cmd "<相關測試指令>" --strike-key sub_task_<id>
   ```
   - exit 0（無新增穩定失敗）→ gate 通過：`local_test_passed: true`，`local_test_evidence` 填 script 輸出摘要（指令＋PASS 行＋略過的 baseline 失敗數）
   - exit 2 → 有真的新增失敗，進下方分類決策樹
3. **flaky 由 script 自動處置**：非 baseline 的失敗會自動重跑一次，重跑通過 → 判定 flaky、併入名單放行（不為它空轉）。flaky 名單累積在 baseline 檔裡，retro 時一併彙報

## 失敗分類決策樹（script 過濾後剩下的真新失敗才進這裡）

| 分類 | 判定 | 處置 |
|---|---|---|
| **code 錯** | 測試斷言的是 Spec 要的行為，diff 沒做到 | 修 code，回循環步驟 3 |
| **測試過時** | 測試斷言的是被 Spec **有意**改掉的舊行為 | 可更新測試，但必須在 `local_test_evidence` 註明：改了哪個測試、舊斷言為何不再成立、對應的 Spec／task 依據。**無依據的放寬斷言／刪 case／加 skip 視同 🔴**（code-reviewer 審查重點） |
| **無關的既有失敗** | 理論上不會出現（baseline 已濾）；出現代表 baseline 漏建或測試指令範圍不一致 | 檢查 baseline 是否涵蓋該測試範圍，必要時重建 baseline |
| **flaky** | script 已自動重跑過濾 | 不需人工處置；若懷疑 script 誤判（例如依時間才觸發的失敗），記錄後照「code 錯」保守處理 |

## 兩次舉手上限（防無限迴圈）

- 定義：**同一 sub_task 的 `check` 真失敗累計 2 次，不論失敗的是不是同一個測試**（最不可鑽的版本；乒乓修壞 A/B 也會被計到）。計數由 script 的 `strikes` 記錄（通過即歸零），不靠 agent 自己數
- 達 2 次 → **停止自行修復**，把「卡在哪些測試、每次試了什麼修法、為什麼沒用」回報使用者裁決。塞住時的正確行為是舉手，不是空轉

## Commit 前全套檢查與重開路徑（跨 sub_task 破壞的最後防線）

step 7 收尾**之前**（歸檔 eval_state 前）跑一次全套：

```
python3 .claude/hooks/test_baseline.py check --strike-key full_suite
```

（省略 `--cmd` → 讀 manifest 的 `test_command`，與 baseline 同源同範圍）

- exit 0 → 照常收尾
- exit 2 → 相關測試沒抓到的跨 sub_task 破壞。處置：
  1. 用 `git diff --cached -- <各 sub_task 的 files>` 定位是哪個 sub_task 的變更弄壞的
  2. **重開該 sub_task**（即使已 `passed`）：`status` 改回 `"in_progress"`、`local_test_passed` 改回 `false`、`step` 設 `"fixing"`
  3. 修正後從循環**步驟 3** 重走（review → verify → test → score 照常，不可只補測試就標回 passed）
  4. hook 的歸檔 gate 自然擋住未重過的 commit（任一 sub_task 非 passed 即擋），順序不可能被跳過

## 零測試專案

| 情況 | 處置 |
|---|---|
| 新專案 | 不會發生——Tier B bootstrap 的 DoD 硬性含測試框架＋示範測試 |
| legacy、Tier 1 | 實際運行功能驗證＋`local_test_evidence` 照填（現行規則），不強制建測試 |
| legacy、Tier 2 | **第一個 Tier 2 run 順路建框架**：分拆時第一個 task 加「建立最小測試框架＋本功能的測試」item（比照共用基礎抽前置 task 的慣例）。「最小」＝能跑單元測試＋覆蓋本次新行為，不要求 e2e、不補歷史覆蓋。建完立刻跑 `baseline`（此時 baseline 天然乾淨） |
| 連最小框架都建不起來 | 這本身就是舉手訊號：停下回報，由使用者裁決走運行驗證＋manifest 記 `debt: ["test-framework"]`（攔截級，還清前 hook 擋新 run——防「建不起來」變永久後門） |

## 驗證豁免窗口（全 tier 通則，總則住在 CLAUDE.md）

- 跳過本地驗證**僅限使用者明示豁免**；agent 不可自行認定、**不可主動建議豁免**（與 hotfix 宣告緊急同一防濫用原則）
- **豁免單次有效**：只管當次需求，不延續、不存在口頭的專案級常態豁免
- 留痕方式按 tier：
  - **Tier 1／2**：manifest 記 `test_policy: "waived_by_user"` ＋一句豁免範圍與使用者原話，隨 commit 進 git。waive 率可統計（比照 tier 分佈統計）——豁免比例異常升高是制度失效的警報
  - **Tier 0**：不為豁免建檔（維持零建檔哲學）。豁免記在 Tier 0 本來就要交付的**變更回報**裡：驗證欄寫「使用者豁免（引用原話）」。此為**弱留痕，屬有意取捨**（Tier 0 已排除高風險面，稽核價值低）
- 豁免不改變 Tier 準入條件：高風險面照樣進不了 Tier 0／1

## 硬 gate 與誠實回報的邊界（明寫取捨）

- **script 判定可稽核**：baseline 檔、strike 計數、check 結果都落在 `run/<run_id>.test_baseline.json`，事後可驗
- **hook 不重跑測試**：`eval_gates.py` 於 commit 時強制的是 `local_test_passed`／`local_test_evidence` 欄位與歸檔順序，無法驗證「失敗清單是真的」。「跑了 check 且如實記錄」這一段靠 agent 誠實＋baseline 檔留痕的事後稽核——這是已知且接受的邊界，不假裝它是硬 gate

## 適用範圍

用於 Eval Flow 循環 step 5、step 7 收尾前的全套檢查、以及任何「測試失敗怎麼處置」的判斷。不適用：
- 測試框架**選型**——Tier B bootstrap 的 HITL 由使用者決定
- 評分——`quality_score` 的 Testability 維度住在 `eval-scoring` skill（本 skill 管「過不過」，那邊管「好不好」）
