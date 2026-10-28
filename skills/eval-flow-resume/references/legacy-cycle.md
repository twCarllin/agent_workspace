## Step 2：依 manifest `phase` 定位前置進度

`phase` 值域為 `init` → `decomposed` → `completed`。前置進度依 **`task_file`**（已建＝分拆完成）與 **`hitl_confirmed_at`**（已記＝HITL 已過）兩個欄位定位：

| phase | 代表已完成 | 恢復動作 |
|---|---|---|
| `init` | 前置 0（manifest + eval_state 已建） | 檢查 `task_file`：非空 → 分拆已完成但 `phase` 未更新，核對 task 檔內容後補設 `"decomposed"`；為 `null` → 檢查 `hitl_confirmed_at`：已記 → HITL 已過但分拆未完成或未觸發，回報現況請使用者決定重新分拆（直建或派 task-decomposer）；未記 → 尚未進入分拆，從前置 1（分拆 task）開始，依 eval-flow skill「Tier 2 完整路徑」的條件派工門檻（**≤2 tasks 且 ≤8 items，含界**）判斷主 flow 直建或派 task-decomposer |
| `decomposed` | 前置 1（分拆完成，HITL 已確認） | 進 Step 3（循環內恢復） |
| `completed` | 全部完成 | 無事可做；若 `eval_state.json` 竟仍存在 → 收尾被中斷，補歸檔流程（step 6 收尾順序） |

- **舊 manifest 的 `phase` 為 `risk_done`／`usage_confirmed`** → hook 的 `manifest_phase()` 已將其映射為 `"init"`，本表按 `init` 列的恢復動作處置——`risk/<run_id>.md`、`usage/<run_id>.md` 即使存在也不用於判斷卡點，只看 `task_file`／`hitl_confirmed_at`
- 舊 manifest 無 `phase` 欄 → 依 `task_file` 是否非空推導（與 hook 的向後相容邏輯一致）
- 舊 Tier 1 的 run（`tier: 1` 且缺 `tier1_policy`）：`phase` 只會是 `init` 或 `decomposed`；`init` 代表卡在輕量 HITL 確認前，重新回報「N tasks／M items」計畫請使用者確認（**≤2 tasks 且 ≤8 items 含界**為主 flow 直建門檻，與 Tier 2 前置 1 條件派工一致）

## Step 3：循環內恢復（phase = decomposed）

續跑前先依 eval-flow skill「效率與驗證重用」入口的剩餘工作規則核對剩餘 DoD、未解失敗與有效證據，再選下表的恢復動作；中斷本身不是重跑已完成驗證的理由。

1. 讀 `eval_state.json`，找 `status: "in_progress"` 的 sub_task（**頂層 task id**——一個 task 一筆；正常只有一個 in_progress task）
   - 一個都沒有且尚有未開始的 task → 從下一個未開始的 task 的步驟 1（code-writer）開跑
   - 全部 `passed` → 收尾被中斷，執行 eval-flow skill 循環 step 6 的完整收尾程序（執行前必讀，含冷溯源檔處置）
2. 讀該 task 的 `step` 與 `files`，用 `git diff --cached -- <files>` 還原工作現場（確認 staged 內容與 `step` 相符：例如 `step: "reviewing"` 但 staging 是空的 → 狀態不一致，回報使用者）
3. 依 `step` 從對應步驟續跑：

| step | 含義 | 從哪續跑 |
|---|---|---|
| `writing` | code-writer 執行中被斷 | 重跑循環步驟 1（code-writer；prompt 附上已 staged 的部分成果供其接續） |
| `reviewing` | 審查中被斷 | **審查結論不落檔**：不追究上一輪發生過什麼，重跑該輪；Tier 2 重派 reviewer，Tier 1 預設重派 checker，邊界理由直接 reviewer，從循環步驟 3 開始（兩節報告） |
| `fixing` | review 有 🔴、修正中被斷 | 同 `reviewing`：依 Tier 重派審查（Tier 2 reviewer；Tier 1 checker 或邊界 reviewer），無結論時不猜修正進度 |
| `verifying` | （舊版 run 的相容值）審查階段 | 同 `reviewing`：依 Tier 重派審查 |
| `testing` | 本地驗證中被斷 | 回到循環步驟 5，依有效證據完成剩餘驗證；失敗、缺席或失效的項目重驗，不採信中斷前的口頭結果。重用仍須符合 eval-flow skill「效率與驗證重用」的條件 |
| `scoring` | （舊版 run 的相容值）無對應現行步驟 | 視同 testing 完成，直接進 eval-flow skill 循環 step 6 的完整收尾程序（執行前必讀，含冷溯源檔處置） |
| `done` | 該 task 已收完 | 狀態應為 `passed`；不是 → 修正狀態後進下一個 task |

恢復時若有有效 review checkpoint 與前次結論，可依 eval-flow skill「效率與驗證重用」重派獨立 reviewer 做增量重審；前次結論缺失仍按本表重審，不以 checkpoint 代替審查結果。

4. **輪數判定**：讀該 task 的 `review_reds`——**無值＝首輪**（依 Tier 重派審查，視為首輪執行）；**有值＝已跑過至少一輪**（Tier 2 保持 reviewer；Tier 1 checker 有升級觸發時改派 reviewer）
5. **已知缺陷（使用者已知情接受，不另設補償機制）**：
   1. Tier 1 中斷發生在「升級 reviewer 輪」時，恢復會誤降回 checker——`review_reds` 有無值只能判斷「跑過至少一輪」，讀不出上一輪究竟是 checker 輪還是已升級的 reviewer 輪
   2. 2 輪修正上限的計數可能歸零——同樣因為只知「有無跑過」不知精確輪數，理論上某次恢復可能讓已修正過的輪被重新算為首輪，使該 task 突破 2 輪上限而不被攔下
   3. 在 `reviewing` 恢復時，Tier 2 直接重派 code-reviewer；Tier 1 checker 若缺 writer 報告等必要輸入，依①③升級。這是不落檔的代價、不是失敗；恢復者不要為了避免升級去補造 writer 報告

   此三者為審查結論與 writer 報告不落檔（換取記帳收斂）的直接代價，接手者續跑後**輪數可能被低估、reviewing 恢復可能多付一輪 reviewer**，須知情；不自行發明補償機制。
