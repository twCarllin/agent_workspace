---
name: eval-flow-resume
description: Eval Flow 中斷恢復的確定性程序：從 run manifest 與 eval_state.json 還原「跑到哪、卡在哪」，定位 in_progress 的 sub_task 與循環步驟，還原 staged 工作現場後從正確的步驟續跑。觸發語：「接續上次的 run」、「恢復中斷的工作」、「resume run」、「上次跑到一半」。不適用於：無任何 in_progress 的 manifest（沒有可恢復的 run）、全新需求（走 Router 分級）。
---

# Eval Flow 中斷恢復程序

> 原則：**恢復只讀檔案狀態，不讀對話記憶**。所有判斷以 `run/<run_id>.json`（manifest）、`eval_state.json`、staging area 為準。若檔案狀態與你對這個 run 的任何印象衝突，以檔案為準。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Step 1：定位要恢復的 run

1. 掃 `run/*.json`，列出所有 `status: "in_progress"` 或 `"ready_to_commit"` 的 manifest（`"aborted"`／`"failed"` 不列入——那是等使用者裁決的封存現場，見本檔末「恢復守則」）
2. 同時檢查 `eval_state.json` 是否存在——存在時其 `run_id` 就是進行中的 run（與 manifest 互相印證；`run_id` 對不上任何 manifest → 回報異常，請使用者裁決）
3. 找到多個 in_progress 的 run → 列給使用者選，不自行挑
4. 一個都沒有 → 無可恢復，回報後結束

若 manifest 為 `ready_to_commit`：先讀 `pre_commit_head`，查目前 HEAD 的 commit message。若 HEAD 已變且有唯一匹配的 `Run-Id`，執行 `python3 .claude/hooks/run_commit.py finalize <run_id>`；若 HEAD 未變，檢查 staging 和驗證快照後提交，再 finalize。HEAD 已變但 trailer 不匹配時停止並回報，不推測歸屬。

## Step 2：依 manifest `phase` 定位前置進度

**2026-09-22 起（Q4）**：`phase` 值域收斂為 `init` → `decomposed` → `completed`；risk_done／usage_confirmed 兩個舊值與依 `usage/<run_id>.md`、`impact_report_path` 判斷卡點的舊邏輯已移除（前置 1 風險分析已刪除、usage／impact 改具名問題觸發，兩者都不再是必經的前置 gate）。改依 **`task_file`**（已建＝分拆完成）與 **`hitl_confirmed_at`**（已記＝HITL 已過）兩個欄位定位前置進度：

| phase | 代表已完成 | 恢復動作 |
|---|---|---|
| `init` | 前置 0（manifest + eval_state 已建） | 檢查 `task_file`：非空 → 分拆已完成但 `phase` 未更新，核對 task 檔內容後補設 `"decomposed"`；為 `null` → 檢查 `hitl_confirmed_at`：已記 → HITL 已過但分拆未完成或未觸發，回報現況請使用者決定重新分拆（直建或派 task-decomposer）；未記 → 尚未進入分拆，從前置 1（分拆 task）開始，依 SKILL.md 條件派工門檻（**≤2 tasks 且 ≤8 items，含界**）判斷主 flow 直建或派 task-decomposer |
| `decomposed` | 前置 1（分拆完成，HITL 已確認） | 進 Step 3（循環內恢復） |
| `completed` | 全部完成 | 無事可做；若 `eval_state.json` 竟仍存在 → 收尾被中斷，補歸檔流程（step 6 收尾順序） |

- **舊 manifest 的 `phase` 為 `risk_done`／`usage_confirmed`**（2026-09-22 前寫入的既有 run）→ hook 的 `manifest_phase()` 已將其映射為 `"init"`，本表按 `init` 列的恢復動作處置——`risk/<run_id>.md`、`usage/<run_id>.md` 即使存在，新流程不再讀它們判斷卡點，只看 `task_file`／`hitl_confirmed_at`
- 舊 manifest 無 `phase` 欄 → 依 `task_file` 是否非空推導（與 hook 的向後相容邏輯一致；原本可用 `usage_report_path` 推導出 `usage_confirmed` 的分支已隨值域收斂移除）
- Tier 1 的 run（`tier: 1`）：`phase` 只會是 `init` 或 `decomposed`；`init` 代表卡在輕量 HITL 確認前，重新回報「N tasks／M items」計畫請使用者確認（**≤2 tasks 且 ≤8 items 含界**為主 flow 直建門檻，與 Tier 2 前置 1 條件派工一致）

## Step 3：循環內恢復（phase = decomposed）

1. 讀 `eval_state.json`，找 `status: "in_progress"` 的 sub_task（**頂層 task id**，Q2——一個 task 一筆，item 降為該筆內的 `items` 清單；正常只有一個 in_progress task）
   - 一個都沒有且尚有未開始的 task → 從下一個未開始的 task 的步驟 1（code-writer）開跑
   - 全部 `passed` → 收尾被中斷，執行 step 6 收尾順序（歸檔 → 清除 eval_state → 回寫 token 用量 → commit；溯源檔不 `git add`，見 eval-flow SKILL.md step 6 子項②）
2. 讀該 task 的 `step` 與 `files`，用 `git diff --cached -- <files>` 還原工作現場（確認 staged 內容與 `step` 相符：例如 `step: "reviewing"` 但 staging 是空的 → 狀態不一致，回報使用者）
3. 依 `step` 從對應步驟續跑：

| step | 含義 | 從哪續跑 |
|---|---|---|
| `writing` | code-writer 執行中被斷 | 重跑循環步驟 1（code-writer；prompt 附上已 staged 的部分成果供其接續） |
| `reviewing` | 審查中被斷 | **審查落檔已刪除（D1），Q6 裁決**：不追究上一輪發生過什麼，**一律重跑該輪、重派 checker**（`task-verifier`），從循環步驟 3 開始（兩節報告） |
| `fixing` | review 有 🔴、修正中被斷 | 同 `reviewing`：**一律重跑該輪、重派 checker**（Q6，無落檔可讀、不試圖還原修正進度） |
| `verifying` | （舊版 run 的現場）task-verifier 曾一度退役（2026-07-25），**現已復活為 checker——審查層預設位（2026-09-05 起，退役敘述作廢）** | 同 `reviewing`：一律重跑該輪、重派 checker |
| `testing` | 本地測試中被斷 | 重跑循環步驟 5（`local_test_passed` 為 `false` 一律重測，不採信中斷前的口頭結果） |
| `scoring` | （舊版 run 的相容值）評分階段已移除 | 視同 testing 完成，直接進 step 6 收尾順序（歸檔 → 清除 eval_state → 回寫 token 用量 → commit；溯源檔不 `git add`，見 eval-flow SKILL.md step 6 子項②） |
| `done` | 該 task 已收完 | 狀態應為 `passed`；不是 → 修正狀態後進下一個 task |

4. **輪數判定（取代原落檔 `<N>` 接續，Q6）**：讀該 task 的 `review_reds`——**無值＝首輪**（重派 checker 視為首輪執行）；**有值＝已跑過至少一輪**（重派 checker 後若再有 🔴，依循環 step 3／4 的四類升級觸發改派 code-reviewer）
5. **Q6 已知缺陷（使用者已知情裁決接受，不另設補償機制）**：
   1. 中斷發生在「升級 reviewer 輪」時，恢復會誤降回 checker——`review_reds` 有無值只能判斷「跑過至少一輪」，讀不出上一輪究竟是 checker 輪還是已升級的 reviewer 輪
   2. 2 輪修正上限的計數可能歸零——同樣因為只知「有無跑過」不知精確輪數，理論上某次恢復可能讓已修正過的輪被重新算為首輪，使該 task 突破 2 輪上限而不被攔下

   此二者為刪除審查落檔（D1）換取記帳收斂的直接代價，接手者續跑後**輪數可能被低估**，須知情；不自行發明補償機制。

## 恢復守則

- **已 `passed` 的 sub_task 一律不重跑**、其 staged 變更不動
- **hook gates 照常生效**：恢復不是繞過 gate 的理由，被擋就依 stderr 訊息補狀態
- **寧可重跑一步，不可跳過一步**：`step` 只保證「走到了這一步」，不保證這一步完成；有疑義就從該步重做
- 恢復後的第一件事：把你從檔案讀出的「run 現況摘要」（run_id、phase、各 sub_task 狀態、接下來要做什麼）回報使用者，再開始動作
- `status: "failed"` 與 `status: "aborted"` 的 run 皆不自動恢復——那是等使用者裁決的封存現場（`aborted`＝主動放棄、`failed`＝流程內判定失敗，兩者待遇相同）；使用者明示續跑才依上表接手
