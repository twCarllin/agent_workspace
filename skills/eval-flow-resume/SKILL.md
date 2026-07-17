---
name: eval-flow-resume
description: Eval Flow 中斷恢復的確定性程序：從 run manifest 與 eval_state.json 還原「跑到哪、卡在哪」，定位 in_progress 的 sub_task 與循環步驟，還原 staged 工作現場後從正確的步驟續跑。觸發語：「接續上次的 run」、「恢復中斷的工作」、「resume run」、「上次跑到一半」。不適用於：無任何 in_progress 的 manifest（沒有可恢復的 run）、全新需求（走 Router 分級）。
---

# Eval Flow 中斷恢復程序

> 原則：**恢復只讀檔案狀態，不讀對話記憶**。所有判斷以 `run/<run_id>.json`（manifest）、`eval_state.json`、staging area 為準。若檔案狀態與你對這個 run 的任何印象衝突，以檔案為準。

## Step 1：定位要恢復的 run

1. 掃 `run/*.json`，列出所有 `status: "in_progress"` 的 manifest
2. 同時檢查 `eval_state.json` 是否存在——存在時其 `run_id` 就是進行中的 run（與 manifest 互相印證；`run_id` 對不上任何 manifest → 回報異常，請使用者裁決）
3. 找到多個 in_progress 的 run → 列給使用者選，不自行挑
4. 一個都沒有 → 無可恢復，回報後結束

## Step 2：依 manifest `phase` 定位前置進度

| phase | 代表已完成 | 恢復動作 |
|---|---|---|
| `init` | 前置 0（manifest + eval_state 已建） | 檢查 `risk_report_path`：非空 → 風險分析做了一半但未過門檻，讀 `risk/<run_id>.md` 續跑前置 1；為 `null` → 從前置 1 開頭跑 |
| `risk_done` | 前置 1（無 🔴） | 檢查 `usage/<run_id>.md` 是否已存在：存在但 `usage_report_path` 為 `null` → 報告已產出、卡在 HITL 確認，把報告摘要與開放問題重新呈給使用者裁示；不存在 → 呼叫 usage-analyzer 跑前置 2 |
| `usage_confirmed` | 前置 2（使用者已確認） | 先檢查 `impact_report_path`：為 `null` → 先呼叫 `impact-analyzer` 跑前置 2.5，產出後再繼續（Tier 1 不會停在此 phase，且其值固定 `"skipped"` 非 `null`）；非 `null` → 檢查 `task_file`：為 `null` → 呼叫 task-decomposer 跑前置 3；非空但 `phase` 未達 `decomposed` → task 檔已產出但 phase 未設，主 flow 核對 task-decomposer 自檢結論後設 phase |
| `decomposed` | 前置 3（可進循環） | 進 Step 3（循環內恢復） |
| `completed` | 全部完成 | 無事可做；若 `eval_state.json` 竟仍存在 → 收尾被中斷，補歸檔流程（step 6 收尾順序） |

- 舊 manifest 無 `phase` 欄 → 依 `task_file`／`usage_report_path` 是否非空推導（與 hook 的向後相容邏輯一致）
- Tier 1 的 run（`tier: 1`）：`phase` 只會是 `init` 或 `decomposed`；`init` 代表卡在輕量 HITL 確認前，重新回報「1 task／N items」計畫請使用者確認

## Step 3：循環內恢復（phase = decomposed）

1. 讀 `eval_state.json`，找 `status: "in_progress"` 的 sub_task（正常只有一個）
   - 一個都沒有且尚有未開始的 sub_task → 從下一個未開始的 sub_task 的步驟 1（code-writer）開跑
   - 全部 `passed` → 收尾被中斷，執行 step 6 收尾順序（歸檔 → 清除 eval_state → git add → commit）
2. 讀該 sub_task 的 `step` 與 `files`，用 `git diff --cached -- <files>` 還原工作現場（確認 staged 內容與 `step` 相符：例如 `step: "reviewing"` 但 staging 是空的 → 狀態不一致，回報使用者）
3. 依 `step` 從對應步驟續跑：

| step | 含義 | 從哪續跑 |
|---|---|---|
| `writing` | code-writer 執行中被斷 | 重跑循環步驟 1（code-writer；prompt 附上已 staged 的部分成果供其接續） |
| `reviewing` | 並行審查／驗證中被斷 | 重跑循環步驟 3（並發呼叫 code-reviewer 與 task-verifier） |
| `fixing` | review 有 🔴、修正中被斷 | 讀 `run/<run_id>.review-st<id>-r<N>.md` 的落檔審查報告續修（`<id>`＝該 in_progress sub_task 的 id，`<N>` 取現存檔名中最大者＝最新一輪；無落檔報告＝舊版 run 的現場，重跑步驟 3）；回步驟 3 時 verifier 隨 reviewer 一併重跑（該輪 verify 結果已作廢） → 回步驟 3 |
| `verifying` | （舊版序列 run 的現場）task-verifier 執行中被斷 | 重跑循環步驟 4 |
| `testing` | 本地測試中被斷 | 重跑循環步驟 5（`local_test_passed` 為 `false` 一律重測，不採信中斷前的口頭結果） |
| `scoring` | （舊版 run 的相容值）評分階段已移除 | 視同 testing 完成，直接進 step 6 收尾順序（歸檔 → 清除 eval_state → git add → commit） |
| `done` | 該 sub_task 已收完 | 狀態應為 `passed`；不是 → 修正狀態後進下一個 sub_task |

4. 續跑的修正輪數以審查落檔 `run/<run_id>.review-st<id>-r<N>.md` 的最大 `<N>` 接續計算（2 輪上限照算，不歸零）

## 恢復守則

- **已 `passed` 的 sub_task 一律不重跑**、其 staged 變更不動
- **hook gates 照常生效**：恢復不是繞過 gate 的理由，被擋就依 stderr 訊息補狀態
- **寧可重跑一步，不可跳過一步**：`step` 只保證「走到了這一步」，不保證這一步完成；有疑義就從該步重做
- 恢復後的第一件事：把你從檔案讀出的「run 現況摘要」（run_id、phase、各 sub_task 狀態、接下來要做什麼）回報使用者，再開始動作
- `status: "failed"` 的 run 不自動恢復——那是等使用者裁決的封存現場；使用者明示續跑才依上表接手
