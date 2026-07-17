---
name: parallel-run
description: 多個互不相依的 Tier 1 需求並行執行：主 session 批次判級與批次 HITL 後，每需求開一個 git worktree ＋背景 agent 各自跑 eval-flow Tier 1 精簡路徑，完成後彙整回報、經使用者確認再 merge 回 main。觸發語：「/parallel-run」、「這幾個需求同時做」、「並行跑這些 Tier 1」。不適用於：單一需求（走原本流程，不開 worktree）、Tier 0（一律主 session 序列直接做）、Tier 2（HITL gate 多，不適合背景執行）、需求之間有相依或觸及檔案相交（並行必互相污染，改序列）。
---

# Parallel Run（多個 Tier 1 需求並行）

> 觸發條件：**同時有 ≥2 個互不相依的 Tier 1 需求**。條件不滿足就不開 worktree——單一 Tier 1 走原本 eval-flow、Tier 0 一律序列直接做。並行省的是 wall-clock，不省 token（每 run 約多 10–20% 編排開銷，使用者已知情接受）。

## 前置（全部在主 session 完成，spawn 前）

1. **逐一判級（Router）**：每個需求各自過 CLAUDE.md 分級表。
   - 全部必須是 **Tier 1** 才可進入並行。
   - 任一判為 Tier 2 → 從並行批次剔除，另走完整 eval-flow（可在並行批次跑完後、或另開 worktree 由主 session 前景跑）。
   - 任一判為 Tier 0 → 剔除，主 session 直接改（不建檔、不開 worktree）。
2. **相依檢查（硬性）**：預估各需求會觸及的檔案清單，兩兩比對：
   - 檔案相交、或功能上有先後相依 → 相依的那組**不並行**（序列跑，或合併成一個 run）。
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
   - **commit 限定在自己的 feat branch**（eval-flow step 6 的收尾 commit，附 `Run-Id` trailer）；**禁止 merge、禁止 push、禁止切 branch**。
   - 卡住（2 次真失敗、升級逃生門、任何需要使用者裁決的事）→ 停止並回報主 session，**不自行猜測往下**。

## 收尾（主 session）

7. **彙整回報**：全部 agent 結束後，主 session 彙整各 run 的結果——狀態（completed／failed）、review 輪數與首輪 🔴 數、diff 摘要（`git log --stat feat/<run_id>`）——一次回報使用者。
8. **使用者確認後才 merge**：逐一 `git merge feat/<run_id>`（前置 2 已保證檔案不相交，理論上零衝突；真衝突 → 停下回報，不自行硬解），merge 完成後 `git worktree remove ../<repo>-<slug>` 並刪除 feat branch。**未經使用者確認不 merge、不清 worktree**。
9. **任一 run failed**：該 worktree **原地凍結**（狀態全在 manifest／`eval_state.json`／staging area），回報死因；其餘成功的 run 照常走確認→merge。凍結的 run 之後依 `eval-flow-resume` skill 在原 worktree 續跑。

## 不變量

- 並行的單位是 **run**，隔離的單位是 **worktree**——eval-flow「單一 run 原則」在每個 worktree 內照常成立，本 skill 不鬆動任何 gate。
- 主 session 在 agent 執行期間**不得在主工作區起新的 eval-flow run**（避免與收尾 merge 攪在一起）；Tier 0 微調與純問答不受限。
