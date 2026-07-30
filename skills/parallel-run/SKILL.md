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
3. **批次輕量 HITL（取代各 run 內的 HITL）**：把每個需求的「N tasks／M items」計畫一次列給使用者，**一次確認全部**。背景 agent 無法做 HITL，此步是它們能帶著 `phase: "decomposed"` 出發的前提。
   - 任一計畫在此觸發升級逃生門（>2 tasks 或合計 >8 items、歧義、遠超 300 行）→ 該需求升 Tier 2、退出並行批次，其餘照常。
4. **auto-mode 依據**：使用者呼叫本 skill 即視為對本批背景 run **明示開啟 auto-mode**（eval-flow「auto-mode 定義」的明示要件由此滿足），背景 agent 的 Bash 得以自動批准。此依據記入各 run manifest 的 `tier_rationale` 或附註。

## 開工

5. **每需求 spawn 一個背景 agent，worktree 交由 harness 建立**：以 `Agent` 工具的 `isolation: "worktree"` 啟動，harness 會建 `.claude/worktrees/agent-<id>/` 並**在啟動時把該 agent 的工作目錄釘定在其中**。
   - **釘定是 gate 生效的前提，不是便利**：hook 依該次 tool call 的**實際 cwd** 解析所屬工作區（見 `.claude/hooks/eval_gates.py` 的 root 解析）。agent 若改用 `cd` 進 worktree，cwd 仍被判為主工作區 → gate 套用到錯的 repo → 檔案改在 worktree、憑據卻對主工作區判定，等同無 gate。
   - **禁止改用「主 session 先 `git worktree add`，再叫 agent 自己進去」**：實測（2026-07-29）從 repo root 啟動的 subagent cwd 被釘死，`EnterWorktree` 明文拒絕從 repo root 做 path 切換（`switching is only available to sessions whose working directory is inside a worktree`），兩支 agent 皆於第一步即無法起跑。
   - **branch 由 harness 指派**（`worktree-agent-<id>`），**不是** `feat/<run_id>`。agent 必須在最終回報附上自己的 branch 名稱，主 session 靠它做 merge；run↔commit 的溯源靠 commit message 的 `Run-Id:` trailer，不靠 branch 名。
   - **worktree 起點不是主線 HEAD**：harness 從 `origin/<預設分支>` 切出，會少掉主線上未 push 的 commit，故 agent 起手必須同步（見步驟 6）。
   - `run_id` 仍依 eval-flow 慣例 `YYYY-MM-DD-<slug>`，只是不再體現在 branch 名上。
6. **同一訊息 spawn 全部背景 agent**（一 run 一 agent，並發啟動）。每個 agent 的指示必須包含：
   - **起手三步（順序不可換，任一步不符即停下回報）**：①`pwd && git branch --show-current && git log --oneline -1`——確認位於 `.claude/worktrees/` 底下並記下 branch 名稱 ②**`git merge main`**——確認與主線同步。本專案已設 `worktree.baseRef: "head"`（`.claude/settings.json`），harness worktree 直接從當前本地 HEAD 切出，故此步在正常情況下是 **no-op**（fast-forward 到同一個 commit，零成本）。**仍保留不移除**：設定未套用時（他人 clone 未取得、設定被改、harness 行為變動）worktree 會退回從 `origin/<預設分支>` 切出而**靜默落後主線**，此步是唯一攔截點；保留的代價是一次 no-op，移除而設定又沒生效的代價是整個 run 帶著錯誤前提做完 ③驗證本需求的前提在同步後確實成立（例如所需檔案／目錄存在、數量符合預期）。**前提不成立就停下回報，不可帶著錯的前提往下做**——第②③步互為備援：②保證起點正確，③保證即使②失效也攔得住。
   - 工作目錄已由 harness 釘定：**禁止呼叫 `EnterWorktree`、禁止用 `cd` 換目錄**，**禁止碰主工作區與其他 worktree**。
   - 載入 `eval-flow` skill，走 **Tier 1 精簡路徑**，但：
     - 精簡初始化照常（manifest 填 `tier: 1`、`spec_inline`、`risk_report_path: "skipped"`、`usage_report_path: "skipped"`）；因 HITL 已在主 session 完成，`phase` 直接設 `"decomposed"`，並在 manifest 附註「HITL 於主 session 批次完成（parallel-run）」。
     - **task 檔命名例外**：用 `task/YYYY-MM-DD-<slug>.md`（防兩個 run 同建當天檔造成 merge 衝突）。僅並行 run 適用此例外；單一 run 維持 `task/YYYY-MM-DD.md`。
   - 跑循環 1–7，全部 gate 照常（hook 以該次 tool call 的實際 cwd 解析所屬 worktree 根後才套用 gate，故在各 worktree 內獨立生效——`CLAUDE_PROJECT_DIR` 釘死在 session 啟動目錄、不隨 worktree 移動，此前提由 `.claude/hooks/eval_gates.py` 的 root 解析建立，非天然成立）。**限制**：`CLAUDE_PROJECT_DIR` 為 git 儲存庫子目錄的專案開 worktree 時解析到 worktree 根，該類專案目前不支援並行。
   - **既有測試只增不改**（含 fixture／conftest／測試工具檔）：發現必須修改既有測試＝這個變更動到既有行為＝獨立性假設已破 → 觸發「卡住即停」，該需求退出並行（之後改序列跑）。單一 run 的「有意行為變更同步舊測試」規則僅在非並行模式適用。
   - **BUGLOG 不落盤**：修到 bug 時，BUGLOG 條目寫進回報內容，**不** append `retro/BUGLOG.md`；由主 session 於 merge 後統一 append 並做兩層制升級判定（兩個 worktree 各 grep 自己的快照會漏看對方，重複偵測會失靈）。
   - **blocker 出在 main 既有 code 時禁止在 worktree 修**：標明後依「卡住／HITL 協定」停下，由主 session 在 main 上走 bugfix 流程（診斷先行→判級→修），修完後本 worktree `git merge main` 同步再續跑（修一次、兩支受惠、merge 零衝突）。
   - **commit 限定在自己的 branch**（harness 指派的那一支；eval-flow step 6 的收尾 commit，附 `Run-Id` trailer）；**禁止 push、禁止切 branch、禁止把自己的 branch 合進 main**。起手的 `git merge main` 是反方向的同步，允許且必要。
   - 卡住（2 次真失敗、升級逃生門、任何需要使用者裁決的事）→ 依「卡住／HITL 協定」停止並回報主 session，**不自行猜測往下**。

## 收尾（rolling merge，主 session）

7. **誰先完成先收，不等全批**：任一 agent 結束即回報該 run 結果——狀態（completed／failed）、review 輪數與首輪 🔴 數、diff 摘要（`git log --stat <agent 回報的 branch>`）——經使用者確認後即進入 merge 序列。愈早合，後合者要同步的 main 移動量愈小、語意衝突在 context 還熱時浮現。
8. **merge 序列（每支都做；未經使用者確認不 merge、不清 worktree）**。前置條件：**主工作區必須 clean**——批次期間主 session 做的 Tier 0 微調若尚未 commit，先請使用者處置（commit 或 stash），否則全套測試的結果混入未提交變更，紅綠都不可信：
   1. **機械檢查①（測試完整性）**：`git diff main...<branch> --name-status` 過濾測試路徑（含 conftest／fixture／測試工具檔），出現 M／D → 不 merge，把 diff 列給使用者過目（判準只有一個：測試有沒有被改弱）。純 A（新增檔）放行。
   2. **機械檢查②（實際交集重驗）**：本支與其他未合支的**實際** changed-file 清單取交集，非空 → 停下回報（前置 2 是預估，此處以實際值重驗）。
   3. **後合者先同步**：在自己 worktree `git merge main`，重跑自己的相關測試，綠了才進下一步（真衝突 → 停下回報，不自行硬解）。**副作用（無害，但別誤讀 log）**：同步是在 worktree 側執行，之後把該 branch 合入 main 時會留下 `Merge branch 'main' into <branch>` 這種方向看起來相反的 merge commit——那是同步那一步的紀錄，不是把 main 合進 main。
   4. `git merge <branch>` 進 main → 跑**全套測試**，判準為「相對 merge 前 main 的 baseline 無新增失敗」（非絕對全綠，避免 main 既有 flaky 卡死收尾）。全套 baseline 在合**第一支前**跑一次快照，存 `run/parallel-merge-YYYY-MM-DD.test_baseline.json`（批次層級，不屬於任一 run）。**此處必須手動帶 `--cmd "<全套指令>"`**——該 run_id 沒有對應的 manifest，而 `test_baseline.py` 預設從 manifest 讀 `test_command`，省略 `--cmd` 會直接失敗。
   5. 綠 → append 該 run 帶回的 BUGLOG 條目（append 前先 grep 舊條目做兩層制升級判定）→ 清理 worktree 與 branch。**清理可能失敗，且失敗時不可強拆**：harness 建的 worktree 帶 lock，`git worktree remove --force` 會被擋（提示需 `-f -f` 或先 unlock）。強拆有破壞 harness 狀態的風險，屬**應回報而非硬幹**的情況——工作已合入 main，殘留 worktree 無害。未上鎖者照常 `git worktree remove` 並刪 branch；仍上鎖者列入回報，交由使用者或 harness 自行回收。
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

## 被 Tier 2 [P] fan-out 重用

`eval-flow` skill 的「## Tier 2 [P] fan-out（worktree 並行）」節（`skills/eval-flow/SKILL.md`）重用本 skill 的以下機制——改任何一處時須對照另一端一併更新：

**重用清單**

- **worktree 開設方式**：fan-out 的 item agent 同樣以 `Agent` 的 `isolation: "worktree"` 啟動、branch 由 harness 指派、起手三步（含 `git merge main`）一致。**兩端都不再用 `git worktree add` 自建**（舊契約已於 2026-07-29 實測證明不可行）；父子關係與 run 溯源靠 commit trailer（`Run-Id:` / `Parent-Run-Id:`），不靠 branch 命名。
- **背景 agent spawn**：同一訊息並發啟動全部 item agent 的模式，與本 skill 步驟 6 完全對應。
- **rolling merge 收尾序列（步驟 7–10）**：eval-flow fan-out 節的「Rolling merge 段」直接引用本 skill 步驟 7–10，不另行重寫——「誰先完成先收」、「merge 序列逐支執行」、「merge gate 紅燈」、「任一 run failed 原地凍結」的機制與文字以本 skill 為單一來源。
- **機械檢查①②（步驟 8 子項 1–2，即 8.1/8.2）**：測試完整性檢查（`git diff main...<branch> --name-status` 過濾測試路徑，出現 M/D 不 merge；`<branch>` 一律取自該 agent 回報的 harness 指派 branch，fan-out 亦同）與實際交集重驗（本支與其他未合支 changed-file 清單取交集，非空停下回報）。
- **卡住／HITL 協定（步驟 11–13）**：item worktree 的背景 agent 遇到需使用者裁決的事，依本 skill 同名協定停下：落盤 `run/<子run_id>-blocked.md`、manifest 標 `status: "blocked"`、凍結不擋人、恢復雙路徑（SendMessage 回原 agent 或新 agent 讀卡點報告接手）。
- **批次中斷恢復（步驟 14）**：fan-out 的主 session 死掉後，同樣用 `git worktree list`＋各 worktree manifest `status`＋main 的 `git log` 找 `Run-Id` trailer 機械重建批次狀態，不靠記憶。
- **BUGLOG 不落盤規則**：各 item worktree 修到 bug 時，BUGLOG 條目寫進回報內容、不 append `retro/BUGLOG.md`；由主 session 於 merge 後統一 append 並做兩層制升級判定（沿本 skill 步驟 8 子項 5 及步驟 6 的卡點）。
- **blocker 出在 main 既有 code 時禁止在 worktree 修**（本 skill 步驟 6 中「blocker 出在 main 既有 code 時禁止在 worktree 修」一條）：fan-out 的 item agent 同樣須停下，由主 session 在 main 上走 bugfix 流程，修完後各 item worktree `git merge main` 同步。

**分岔點（fan-out 與本 skill「跨獨立 Tier 1 需求並行」的不同）**

- **前置不同**：本 skill 的前置是「逐一判級＋批次 HITL」（步驟 1–3），每個 run 從零開始走 Tier 1 初始化；Tier 2 fan-out 的前置在父 run 的前置 0–3 已做完（風險分析、usage 報告、影響面盤點、task 拆分都屬父 run），item 迷你 run 直接帶 `phase: "decomposed"` 出發、無需重跑前置。
- **身分不同**：本 skill 每個 worktree 是一個**獨立 Tier 1 need**（各自帶 `spec_inline`、彼此無父子關係）；Tier 2 fan-out 每個 worktree 是**父 run 的一個 `[P]` item 迷你 run**，子 manifest 含 `parent_run_id` 指回父 run、`spec_path` 指回父 Spec，commit trailer 附 `Parent-Run-Id: <父run_id>` 供全族溯源。
- **「既有測試只增不改」前提沿用**：含「有意行為變更需更新既有測試」的 item **不進 fan-out 批**、改留循序段——理由與本 skill 步驟 6 的同名規則相同（既有測試只增不改是 merge gate 的裁判前提，破掉它等於裁判換人、全套綠燈失去安全保證）。
- **進入門檻不同**：本 skill 進入條件是「≥2 個互不相依的 Tier 1 需求」；fan-out 進入條件是「`[P]` item ≥2 且各自預估 ≥150 行」。門檻不足的 fan-out 退回主 worktree 循序執行，無對應的本 skill 路徑。

## 不變量

- 並行的單位是 **run**，隔離的單位是 **worktree**——eval-flow「單一 run 原則」在每個 worktree 內照常成立，本 skill 不鬆動任何 gate。
- 主 session 在 agent 執行期間**不得在主工作區起新的 eval-flow run**（避免與收尾 merge 攪在一起）；Tier 0 微調與純問答不受限；Tier 2 前景 run 須在**自己的 worktree**（同樣適用「BUGLOG 帶回」與收尾 merge 序列）。
- **merge gate 的效力以「既有測試只增不改」為前提**：該規則被繞過時，全套綠燈不構成安全證據（裁判被換掉，跑幾遍都沒意義）。
