# Task — 三處 skill 文件缺口修正（parallel-run 實戰暴露）  (created: 2026-07-30)

> run_id: `2026-07-30-flow-doc-gaps`（Tier 1 精簡路徑）。需求原文見 manifest 的 `spec_inline`。
> 現行全套測試基線：`python3 -m unittest discover -s tests` → **162 tests, OK**。

## 背景（自足，不依賴對話）

2026-07-29／30 首次實際執行 `parallel-run` 及其後續修正，暴露三處文件缺口。三者同源——皆為「skill 文件與實際行為、或與另一份 skill 不一致」。

### 缺口①：`eval-flow` step 6 的 `git add` 清單漏列 baseline 檔

- `skills/test-strategy/SKILL.md:20` 明訂 `run/<run_id>.test_baseline.json`「**此檔隨 commit 進 git**」
- `skills/eval-flow/SKILL.md` step 6 子項②的清單只列「manifest `run/<run_id>.json`、eval 歸檔檔、usage 報告、task 檔」，**未含 baseline 檔**

**實證（非推測）**：本 repo 所有 `run/*.test_baseline.json` 中，唯二漏進 git 的是 `2026-07-25-tier2-p-worktree`（2026-07-30 補 commit）與 `2026-07-30-reviewer-citation-discipline`（並行批次 Run B 產出，清理其 worktree 前搶救才未遺失）。**兩者都出自「照 step 6 清單執行」的情境**；主 flow 逐檔手動 stage 的 run 皆未漏。故為文件缺口而非執行者疏忽。

**失效模式是靜默的**：漏掉不會有任何錯誤訊息或 gate 攔截，只有在剛好要刪除該 run 的 worktree 且事前做了檢查時才會發現。前兩次都是事後補救。

### 缺口②：`parallel-run` 步驟 5 對 worktree 起點的敘述已過時

`skills/parallel-run/SKILL.md:32` 現寫「**worktree 起點不是主線 HEAD**：harness 從 `origin/<預設分支>` 切出，會少掉主線上未 push 的 commit」。此敘述在 run `2026-07-30-worktree-baseref` 將 `.claude/settings.json` 的 `worktree.baseRef` 設為 `head` 之後**已不成立**。該 run 只更新了起手三步第②步（`:35`），未同步此處。

### 缺口③：`baseRef: head` 的潛在假設未記載

`head` 從「當前 session 所在 branch 的本地 HEAD」切出，隱含**主 session 位於 `main`** 這個前提。若在 feature branch 上 spawn 並行批次，worktree 會繼承該 branch 的尖端（其未合併的工作會洩入並行 run），而起手第②步的 `git merge main` 只是把 main 疊加上去、不會取代。此假設在現行 `parallel-run` 流程中恆成立（批次 HITL 在主 session 完成、當時位於 `main`），但文件未寫。

## 明確不做的事（scope 邊界）

- 不改 `.claude/settings.json`（`baseRef` 已於前一個 run 設定完成）
- 不移除 `parallel-run` 起手三步的任何一步
- 不改任何 hook 邏輯、agent 定義、測試、`CLAUDE.md`
- 不改 `skills/test-strategy/SKILL.md`（缺口①的修法是讓 eval-flow 對齊 test-strategy，不是反向）
- 不新增測試（純文件、無行為面可測）

## Task 1: 三處敘述修正

- [x] 1.1 缺口①②③修正 ＋ 部署副本同步  ~25 行  files: `skills/eval-flow/SKILL.md`, `skills/parallel-run/SKILL.md`
      待改處:
        - `skills/eval-flow/SKILL.md` step 6 子項②：`git add` 清單補上 `run/<run_id>.test_baseline.json`，並註明其與 `test-strategy` 的對應關係（避免日後又漂移）
        - `skills/parallel-run/SKILL.md:32`：改為描述現行行為（本專案已設 `baseRef: head`，從主線本地 HEAD 切出），並保留「設定未套用時會退回從 origin 切出」的失效情境說明——該說明是起手第②步存在的理由
        - `skills/parallel-run/SKILL.md`（同段）：補注 `head` 隱含「主 session 位於 `main`」的前提與 feature branch 情境的後果
      DoD（機械可驗）:
        1. `grep -c "test_baseline" skills/eval-flow/SKILL.md` ≥ 1，且該命中位於 step 6 的 `git add` 清單語境（非其他章節的既有提及）。
        2. `skills/parallel-run/SKILL.md` 不再含「harness 從 `origin/<預設分支>` 切出，會少掉主線上未 push 的 commit」這句**作為現況描述**；若保留該語意，只能出現在「設定未套用時的失效情境」語境。
        3. `grep -c "主 session 位於" skills/parallel-run/SKILL.md` ≥ 1（潛在假設已記載）。
        4. **起手三步三步俱在**：`grep -c "git merge main" skills/parallel-run/SKILL.md` 不得為 0。
        5. `python3 -m unittest tests.test_docs_consistency` → OK（未破 hook 路徑引用、skill 互引寫法、未新造 gate 編號區間樣式）。
        6. 部署副本同步：`diff skills/eval-flow/SKILL.md ~/.claude/skills/eval-flow/SKILL.md` 與 `parallel-run` 對應 `diff` 皆**空輸出**。
        7. `python3 -m unittest discover -s tests` → `Ran 162 tests ... OK`。
        8. **反向自驗（缺口①）**：修正後，依 step 6 清單逐項列出本 run 收尾要 `git add` 的檔案，其中**必須包含** `run/2026-07-30-flow-doc-gaps.test_baseline.json`；收尾 commit 後以 `git cat-file -e main:<該檔>` 確認確實進了 git。此為「新清單真的會被照做」的即時驗證。
      情境: 文件與實際行為對齊
      備註: 三處同源（皆為 parallel-run 首次實戰暴露的文件與現實不一致），依 eval-flow「小 prose item 合併」併為一個 sub_task 一輪審。無行為契約表（無新行為面）。DoD 8 是本 item 的鑑別力設計——缺口①的失效模式是靜默的，若不在本 run 當場走一次新清單，就只是把字寫上去而已。
