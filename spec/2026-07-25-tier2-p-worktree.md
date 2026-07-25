# Spec：Tier 2 [P] item worktree 並行

> run_id: `2026-07-25-tier2-p-worktree`
> 本 Spec 為 Eval Flow 的輸入，須自足可讀——不依賴任何對話上下文。

## 1. 背景與問題

現行 Eval Flow 的污染源有二，同一個病（**staging area 與 `eval_state.json` 都是單例**）的兩種發作：

1. **循序 sub_task 累積污染**：一個 run 的 commit 延到 step 6 收尾才發生一次，但每個 sub_task 各自 `git add`。因此 staging area **跨 sub_task 累積**——驗第 N 個 sub_task 時，`git diff --cached` 裝的是 sub_task 1..N 的全部變更。task-verifier（step 1 寫死「固定使用 `git diff --cached`」，不按當前 sub_task 收斂）與 code-reviewer 都會撈到前面 sub_task 的內容，最直接的傷害在 Scope 偏移檢查誤判（前面 sub_task 改的檔案不在當前 item 的「涉及檔案」清單 → 誤報過度擴展）。

2. **`[P]` 共用樹污染（放大版）**：現行「單一 run 內 `[P]` 平行寫作」是**併發 code-writer 共用同一棵樹**（`eval-flow/SKILL.md` 末節）。多個 writer 的未提交變更混在同一個 staging area，diff 交錯、mine 模式失效。文件自己承認要靠「派工 prompt 指定測試檔清單，或各開 worktree」補救，但「各開 worktree」只是逃生門、非預設。

**根因**：污染來自共用單例 staging；`[P]` 併發是最壞情況。

## 2. 目標

讓 **Tier 2 run 內符合門檻的 `[P]` item 各開 git worktree 並行執行**，取得真正的 worktree 隔離——順帶徹底解決上述兩種污染（每個 item 在自己的樹裡，`git diff --cached` 天生乾淨、mine 模式復活）。並行省的是 wall-clock。

## 3. 已定案的設計決策（使用者已拍板，不再開放）

| 編號 | 決策 | 內容 |
|---|---|---|
| **D1 commit 語義** | N 個 commit，整套重用 parallel-run | 每個 `[P]` item 在自己的 feat branch 各自 commit（共享同一 Run-Id），rolling merge 回 main。**放棄「一個 Tier 2 功能＝一個原子 commit」**；使用者接受一個 run 出多個 commit，日後自行 squash 整理。 |
| **D2 觸發門檻** | 只在划算時 fan-out | fan-out 條件：`[P]` item **≥2 個且各自預估 ≥150 行**。不滿足 → 該批 `[P]` 退回主 worktree 循序做（配下述 file-scoped diff 修法）。 |
| **D3 建構順序** | 一起上 | 與 parallel-run 的 worktree+merge 機制**共同設計、共同硬化**（parallel-run 本身尚未實戰，兩層 merge 邏輯一起驗證）。 |
| **D4 狀態持有** | 各自持有（A′：全部都是迷你 run） | 每個 `[P]` item 是獨立的 sibling 迷你 run：自己的 manifest `run/<run_id>-item-<id>.json`（`spec_path` 指回父 Spec、新欄 `parent_run_id` 串溯源）、自己的 eval_state、自己歸檔、自己 commit。**prep 段也自成一個 run**（父 run 的 eval_state 只裝依賴型 item，照現行 step 6 正常歸檔＋commit，父 manifest 標 `completed` 後才 fan-out）——否則 prep commit 會被歸檔 gate（gate 1：eval_state 尚存在擋 commit）攔死，且父 manifest 保持 in_progress 會讓 item worktree 的 hook 因「存在其他 in_progress manifest」擋掉 subagent 呼叫。不做「聚合成父 run 單一歸檔檔」——D1 已否決集體原子 commit，聚合無對象。代價：「一個功能一個 run」變成「一個功能一族 run」，溯源靠 `parent_run_id`＋共同 spec_path 維持。 |

## 4. 詳細設計

### 4.1 三段式 run 執行（分解完成後）

一個觸發 fan-out 的 Tier 2 run，循環階段切成三段：

1. **循序前置段（prep run）**：依賴型 item（標 `depends`、不可 `[P]`——如 DB schema、共用型別）在主 worktree 循序做完，**照現行 step 6 正常歸檔＋commit、父 manifest 標 `completed`**（見 D4：prep 自成一個 run，gate 全程照規則走、零後門）。它們是 `[P]` item branch 出去時的共同基礎，必須先落地。
2. **Fan-out 段**：每個符合門檻的 `[P]` item 各開一個 worktree（從當前 run HEAD 切 `feat/<run_id>-item-<id>`），背景 agent 以**獨立 sibling 迷你 run**（D4）跑完整 Tier 2 循環（code-writer → review∥verify → step5 本地測試 → 自己歸檔、自己 branch commit，trailer 帶自己的 Run-Id；`parent_run_id` 由 manifest 串溯源）。完全隔離：乾淨 diff、mine 復活、hook gate 在各 worktree 內獨立生效。
3. **Rolling merge 段**：直接套 parallel-run 收尾序列（機械檢查①測試只增不改、②實際檔案交集重驗、③後合者先 `git merge main` 同步、④全套測試 baseline gate、⑤BUGLOG 帶回統一 append＋兩層制升級判定）。誰先完成先收，不等全批。

### 4.2 門檻與退回路徑

- fan-out 只在「`[P]` item ≥2 且各 ≥150 行」時啟動。
- 不滿足門檻 → 該批 `[P]` item 退回主 worktree **循序**執行（不開 worktree）。
- 退回路徑須配 **file-scoped diff 修法**（見 4.3），否則循序累積污染仍在。

### 4.3 file-scoped diff 修法（底層必需，與 fan-out 無關）

循序 sub_task 的累積污染，即使沒有並行也存在。修法：

- 派 code-reviewer / task-verifier 時，prompt 指示改用 **`git diff --cached -- <該 sub_task 的 files>`**（檔案清單取自 `eval_state.json` 的 `files`，主 flow 已有 `list-files` helper；與 resume 還原工作現場用的收斂方式一致）。
- 動兩處 agent 定義（task-verifier step 1、code-reviewer 對應段）＋ eval-flow 循環 step 3 派工描述。
- **已知邊界**：兩個 sub_task 改到同一檔案時，`-- <file>` 仍會把兩者對該檔的變更一起帶出。這種情況少（[P] 本就 disjoint、循序 item 也傾向分檔），prompt 註一句「同檔跨 sub_task 時以 task 描述判歸屬」，不上更重機制。

### 4.4 與 parallel-run 的關係（重用 vs 分岔）

D4 定案後，Tier 2 fan-out 在機械層面＝「拆解產出 prep run ＋ N 個 item 迷你 run，對後者跑一次 parallel-run」——每個 item worktree 就是 parallel-run 的一個 run，worktree 開設、背景 agent spawn、rolling merge 收尾序列、機械檢查、BUGLOG 帶回全數重用，hook 接近零改動。仍需新寫的分岔點：

- **run 家族的溯源**：manifest 新欄 `parent_run_id`（子 run 指回父 run；hook 對舊 manifest 無此欄須向後相容）；父 Spec／usage／task 檔由家族共用，不重複產出。
- **fan-out 編排**：主 session 判門檻（D2）、切分 prep／fan-out 兩批、為各 item 產生子 manifest 與派工（parallel-run 的前置判級／批次 HITL 在此換成「已過父 run 的前置 0–3」）。
- **既有測試只增不改前提沿用**：含「有意行為變更、需更新既有測試」的 item 不可進 fan-out 批（會破 merge gate 的裁判前提），改留循序段——與 parallel-run 同規則。

## 5. 涉及的元件（供後續影響面盤點細化，非最終清單）

- `skills/eval-flow/SKILL.md`：三段式執行、fan-out 門檻、file-scoped diff 派工、`[P]` 共用樹舊節改寫。
- `skills/parallel-run/SKILL.md`：抽出可共用的 worktree+merge 機制，或標明 Tier 2 [P] 的重用點。
- `skills/task-decomposition/SKILL.md`：`[P]` 標註規則可能需補「≥150 行才觸發 worktree」的註記與 item 大小估計欄位。
- `.claude/agents/task-verifier.md`、`.claude/agents/code-reviewer.md`：file-scoped diff。
- `.claude/hooks/`（`eval_gates.py` 等）：可能需支援「一個 run 多 commit／多 branch」的 gate 調整與聚合歸檔驗證。**觸及 hook gate 邏輯＝高風險面，強制 Tier 2**。

## 6. 不做的事（Non-goals）

- **不做原子 squash commit**（D1 已否決）——一個 run 多 commit 是接受的結果。
- **不把 Tier 1 或 Tier 0 拉進 fan-out**：跨獨立需求的並行仍走 parallel-run；Tier 0 一律主 session 序列。
- **不改 `[P]` 的 disjoint 檔案前提**（task-decomposition Step 4 既有規則不動）。
- **不降低任何既有 hook gate 的效力**：merge gate 的「既有測試只增不改」前提不鬆動。
- **不為門檻以下的小 item 開 worktree**（省不到 wall-clock、反虧編排稅）。
- **不改 `stats.py`**：子 manifest 被計為獨立 run（一族顯示 N+1 筆）是可接受的——D4 下 `[P]` item 本就是迷你 run，各自有 review_reds／HITL 記錄，計為獨立 run 是正確的遙測粒度而非失真。若日後要「按 parent_run_id 摺疊顯示」，另開 run 處理。

## 7. 開放問題（供前置 1 風險分析與前置 2 使用情境 HITL 裁示）

1. ~~eval_state 聚合的具體形狀~~ **已定案為 D4**（各自持有、全部迷你 run、不聚合），見決策表。
2. **多 commit 下 Run-Id 溯源**：家族反查改為「`git log --grep "Run-Id: <parent_run_id>"` 撈 prep run ＋ 逐子 manifest 的 run_id 各撈一筆」，或子 run 的 commit trailer 同時附 `Parent-Run-Id: <parent_run_id>`（一次 grep 撈全族）——傾向後者，前置 3 定案。
3. **門檻的行數估計來源**：150 行以 task-decomposer 的 item 行數估計（`~<行數>行`）為準；估計不準時的保守處理（估不準 → 不 fan-out，走循序）。
4. **hook gate 對「多 branch 未合」中間狀態的容忍**：fan-out 期間主 worktree 尚無完整變更，gate 不可誤擋。

## 8. 驗收標準（Definition of Done）

1. Tier 2 run 內 `[P]` item ≥2 且各 ≥150 行時，能各開 worktree 以獨立迷你 run 並行跑完整循環，收尾 rolling merge 回 main，產出一族 commit（各帶自己的 Run-Id、可由 parent_run_id 一次反查全族）。
2. 門檻不滿足時，退回主 worktree 循序執行，且 code-reviewer／task-verifier 使用 file-scoped diff（`-- <files>`），驗證範圍不含其他 sub_task 的變更。
3. 含「有意行為變更需改既有測試」的 item 被排除於 fan-out 批之外（留循序段）。
4. 所有既有 hook gate 效力不變；新增／調整的 gate 有對應測試。
5. 三個 skill（eval-flow／parallel-run／task-decomposition）與兩個 agent 定義的描述一致、無自相矛盾，且 self-contained 可讀。
6. 全套測試相對 baseline 無新增失敗。
