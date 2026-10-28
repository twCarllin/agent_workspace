---
name: eval-flow-resume
description: Eval Flow 中斷恢復的確定性程序：從 run manifest 與 eval_state.json 還原「跑到哪、卡在哪」，定位 in_progress 的 sub_task 與循環步驟，還原 staged 工作現場後從正確的步驟續跑。觸發語：「接續上次的 run」、「恢復中斷的工作」、「resume run」、「上次跑到一半」。不適用於：無可恢復的 in_progress／ready_to_commit manifest、全新需求（走 Router 分級）。
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

若 manifest 為 `ready_to_commit`：先讀 `pre_commit_head`，查目前 HEAD 的 commit message。若 HEAD 已變且有唯一匹配的 `Run-Id`，執行 `python3 .agent-flow/scripts/run_commit.py finalize <run_id>`；若 HEAD 未變，檢查 staging 和驗證快照後提交，再 finalize。HEAD 已變但 trailer 不匹配時停止並回報，不推測歸屬。

## adaptive Tier 1 的恢復

`tier1_policy: "adaptive-v1"` 不建 eval_state；先依 manifest 的已授權計畫、
`review_reasons`、完成度與實際驗證核對剩餘項目。`init` 尚未開始時依 eval-flow
的 Tier 1 路徑判斷是否有待裁示問題；已記授權且無問題時可用 `start-run`。
`decomposed` 不等於 HITL 曾確認，不補造確認時間。已有獨立審查原因不可降回自查；
沒有有效自查來源快照、驗證失敗或來源變動時，先重做適用驗證再核對。不因中斷而替 adaptive 預設加派 checker。

## Tier 2 與舊 Tier 1 的恢復

確認不是 adaptive Tier 1 後，必讀 [前置與循環恢復](references/legacy-cycle.md)，依 phase、step 與證據續跑；已知限制與輪數判定同在該文件。

## 恢復守則

- 恢復時需要派工，依 eval-flow `references/dispatch-control.md`「派工上下文」：同任務、同角色優先續用原 agent；無法續用才建立新 agent，Codex 明確給 `fork_turns: "none"`。交接只附規格、允許檔案、驗收與約束、有效證據及剩餘問題，不傳完整對話。此條不改本檔的審查與證據判定。
- **已 `passed` 的 sub_task 一律不重跑**、其 staged 變更不動
- **hook gates 照常生效**：恢復不是繞過 gate 的理由，被擋就依 stderr 訊息補狀態
- **未證明完成的步驟不可跳過**：`step` 只保證「走到了這一步」，不保證完成；先核對實際證據，再重做缺席或失效的部分
- 恢復後的第一件事：把你從檔案讀出的「run 現況摘要」（run_id、phase、各 sub_task 狀態、接下來要做什麼）回報使用者，再開始動作
- `status: "failed"` 與 `status: "aborted"` 的 run 皆不自動恢復——那是等使用者裁決的封存現場（`aborted`＝主動放棄、`failed`＝流程內判定失敗，兩者待遇相同）；使用者明示續跑才依適用恢復路徑接手
