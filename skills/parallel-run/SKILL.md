---
name: parallel-run
description: 多個互不相依的 Tier 1 需求並行執行：主 session 批次判級與批次 HITL 後，每需求開一個 git worktree ＋背景 agent 各自跑 eval-flow Tier 1 精簡路徑，完成後 rolling merge（機械檢查＋全套測試 gate）回 main。觸發語：「/parallel-run」、「這幾個需求同時做」、「並行跑這些 Tier 1」。不適用於：單一需求（走原本流程，不開 worktree）、Tier 0（一律主 session 序列直接做）、Tier 2 背景執行（HITL gate 多；Tier 2 僅可由主 session 前景在自己的 worktree 跑，與本批並存）、需求之間有相依或觸及檔案相交（並行必互相污染，改序列）。
---

# Parallel Run（多個 Tier 1 需求並行）

> 觸發條件：**同時有 ≥2 個互不相依的 Tier 1 需求**。條件不滿足就不開 worktree——單一 Tier 1 走原本 eval-flow、Tier 0 一律序列直接做。**一批上限 2 個 run**：每多一支，後合者的「同步 main→重測→全套」稅多收一輪，且卡住的 run 都排隊等使用者裁決。並行省的是 wall-clock，不省 token（每 run 約多 10–20% 編排開銷，使用者已知情接受）。

## 前置（全部在主 session 完成，spawn 前）

1. **逐一判級（Router）**：每個需求各自過 CLAUDE.md 分級表。
   - 全部必須是 **Tier 1** 才可進入並行。
   - 任一判為 Tier 2 → 從並行批次剔除，另走完整 eval-flow（可在並行批次跑完後跑，或**由主 session 前景在自己的 worktree 跑、與本批並存**——Tier 2 禁止丟背景）。
   - 任一判為 Tier 0 → 剔除，主 session 直接改（不建檔、不開 worktree）。
2. **相依檢查（硬性）**：預估各需求會觸及的檔案清單，兩兩比對：
   - 檔案相交、或功能上有先後相依 → 相依的那組**不並行**（序列跑，或合併成一個 run）。
   - 比對的不只檔案路徑，還有**行為面／模組**——兩支會動同一條資料流、同一張表、同一個共用模組的行為，即使檔案不相交也算相依（全套測試 gate 只保護有測試覆蓋的行為，沒覆蓋的路徑靠這裡擋）。
   - 需求含**有意的既有行為變更**（會觸發 task-decomposition「測試同步段」、需要更新既有測試）→ 該需求**不進並行**，改序列跑——並行模式既有測試只增不改，這種需求進來必觸發卡住，前置就篩掉。
   - **共享可變資源也算相依**：兩支的測試會同時碰同一個本地 DB、固定 port、共用外部沙箱 → 測試並跑必互相污染（假紅／假綠都可能），不並行或由主 session 錯開測試時段。
   - 判不準時保守處理：寧可序列，不賭 merge。
3. **批次輕量 HITL（取代各 run 內的 HITL）**：把每個需求的「1 task／N items」計畫一次列給使用者，**一次確認全部**。背景 agent 無法做 HITL，此步是它們能帶著 `phase: "decomposed"` 出發的前提。
   - 任一計畫在此觸發升級逃生門（>5 items、歧義、遠超 300 行）→ 該需求升 Tier 2、退出並行批次，其餘照常。
4. **auto-mode 依據**：使用者呼叫本 skill 即視為對本批背景 run **明示開啟 auto-mode**（eval-flow「auto-mode 定義」的明示要件由此滿足），背景 agent 的 Bash 得以自動批准。此依據記入各 run manifest 的 `tier_rationale` 或附註。

## 開工

5. **每需求開一個 worktree**：
   ```
   git worktree add ../<repo>-<slug> -b feat/<run_id>
   ```
   `run_id` 依 eval-flow 慣例：`YYYY-MM-DD-<slug>`。
6. **同一訊息 spawn 全部背景 agent**（一 run 一 agent，並發啟動）。每個 agent 的指示必須包含：
   - 工作目錄固定在自己的 worktree，**禁止碰主工作區與其他 worktree**。
   - 載入 `eval-flow` skill，走 **Tier 1 精簡路徑**，但：
     - 精簡初始化照常（manifest 填 `tier: 1`、`spec_inline`、`risk_report_path: "skipped"`、`usage_report_path: "skipped"`）；因 HITL 已在主 session 完成，`phase` 直接設 `"decomposed"`，並在 manifest 附註「HITL 於主 session 批次完成（parallel-run）」。
     - **task 檔命名例外**：用 `task/YYYY-MM-DD-<slug>.md`（防兩個 run 同建當天檔造成 merge 衝突）。僅並行 run 適用此例外；單一 run 維持 `task/YYYY-MM-DD.md`。
   - 跑循環 1–7，全部 gate 照常（hook 在各 worktree 內獨立生效）。
   - **既有測試只增不改**（含 fixture／conftest／測試工具檔）：發現必須修改既有測試＝這個變更動到既有行為＝獨立性假設已破 → 觸發「卡住即停」，該需求退出並行（之後改序列跑）。單一 run 的「有意行為變更同步舊測試」規則僅在非並行模式適用。
   - **BUGLOG 不落盤**：修到 bug 時，BUGLOG 條目寫進回報內容，**不** append `retro/BUGLOG.md`；由主 session 於 merge 後統一 append 並做兩層制升級判定（兩個 worktree 各 grep 自己的快照會漏看對方，重複偵測會失靈）。
   - **blocker 出在 main 既有 code 時禁止在 worktree 修**：標明後依「卡住／HITL 協定」停下，由主 session 在 main 上走 bugfix 流程（診斷先行→判級→修），修完後本 worktree `git merge main` 同步再續跑（修一次、兩支受惠、merge 零衝突）。
   - **commit 限定在自己的 feat branch**（eval-flow step 6 的收尾 commit，附 `Run-Id` trailer）；**禁止 merge、禁止 push、禁止切 branch**。
   - 卡住（2 次真失敗、升級逃生門、任何需要使用者裁決的事）→ 依「卡住／HITL 協定」停止並回報主 session，**不自行猜測往下**。

## 收尾（rolling merge，主 session）

7. **誰先完成先收，不等全批**：任一 agent 結束即回報該 run 結果——狀態（completed／failed）、review 輪數與首輪 🔴 數、diff 摘要（`git log --stat feat/<run_id>`）——經使用者確認後即進入 merge 序列。愈早合，後合者要同步的 main 移動量愈小、語意衝突在 context 還熱時浮現。
8. **merge 序列（每支都做；未經使用者確認不 merge、不清 worktree）**。前置條件：**主工作區必須 clean**——批次期間主 session 做的 Tier 0 微調若尚未 commit，先請使用者處置（commit 或 stash），否則全套測試的結果混入未提交變更，紅綠都不可信：
   1. **機械檢查①（測試完整性）**：`git diff main...feat/<run_id> --name-status` 過濾測試路徑（含 conftest／fixture／測試工具檔），出現 M／D → 不 merge，把 diff 列給使用者過目（判準只有一個：測試有沒有被改弱）。純 A（新增檔）放行。
   2. **機械檢查②（實際交集重驗）**：本支與其他未合支的**實際** changed-file 清單取交集，非空 → 停下回報（前置 2 是預估，此處以實際值重驗）。
   3. **後合者先同步**：在自己 worktree `git merge main`，重跑自己的相關測試，綠了才進下一步（真衝突 → 停下回報，不自行硬解）。
   4. `git merge feat/<run_id>` 進 main → 跑**全套測試**，判準為「相對 merge 前 main 的 baseline 無新增失敗」（非絕對全綠，避免 main 既有 flaky 卡死收尾）。全套 baseline 在合**第一支前**跑一次快照，存 `run/parallel-merge-YYYY-MM-DD.test_baseline.json`（批次層級，不屬於任一 run）。
   5. 綠 → append 該 run 帶回的 BUGLOG 條目（append 前先 grep 舊條目做兩層制升級判定）→ `git worktree remove ../<repo>-<slug>` 並刪除 feat branch。
9. **merge gate 紅燈**：當一個 bugfix 走既有「診斷先行」流程，在**主 session** 做（語意衝突根因跨兩支 branch，單一 worktree 的視野只有一半），診斷完照常判級修復。
10. **任一 run failed**：該 worktree **原地凍結**（狀態全在 manifest／`eval_state.json`／staging area），回報死因；其餘成功的 run 照常走確認→merge。凍結的 run 之後依 `eval-flow-resume` skill 在原 worktree 續跑。

## 卡住／HITL 協定（背景 agent 需要使用者裁決時）

11. **停前落盤（硬要求）**：manifest 標 `status: "blocked"`＋一句 blocked_reason；寫自足卡點報告 `run/<run_id>-blocked.md`（重現步驟、目前的根因假設、試過什麼且為何失敗、要使用者裁決的問題與選項）。落盤後才停——恢復路徑不保證是同一個 agent，沒落盤備援就斷了。
12. **凍結不擋人**：blocked 的 run 原地凍結，另一支照常跑、照常 rolling merge。使用者不需立刻處理。
13. **恢復雙路徑**：首選 SendMessage 回原 agent（context 尚熱，最便宜）；原 agent 已不在（session 重啟、隔日處理）→ 於原 worktree 起新 agent 走 `eval-flow-resume`＋讀卡點報告接手。使用者的裁決內容記入 manifest 留痕（比照驗證豁免慣例）。

## 批次中斷恢復（主 session 死掉／compact 後）

14. **批次沒有獨立狀態檔，用既有痕跡機械重建**，不靠記憶：
    - 還有哪些 worktree／哪些 run：`git worktree list` ＋ 各 worktree 的 manifest（`status`：in_progress／blocked／completed）。
    - 哪支已 merge：main 的 `git log` 找 `Run-Id` trailer。
    - 全套 baseline 是否已快照：`run/parallel-merge-*.test_baseline.json` 存在與否。
    - 單一 run 內部跑到哪，照常走 `eval-flow-resume`。重建後從對應的收尾步驟續跑。

## 不變量

- 並行的單位是 **run**，隔離的單位是 **worktree**——eval-flow「單一 run 原則」在每個 worktree 內照常成立，本 skill 不鬆動任何 gate。
- 主 session 在 agent 執行期間**不得在主工作區起新的 eval-flow run**（避免與收尾 merge 攪在一起）；Tier 0 微調與純問答不受限；Tier 2 前景 run 須在**自己的 worktree**（同樣適用「BUGLOG 帶回」與收尾 merge 序列）。
- **merge gate 的效力以「既有測試只增不改」為前提**：該規則被繞過時，全套綠燈不構成安全證據（裁判被換掉，跑幾遍都沒意義）。
