> 本檔由 skills/eval-flow/SKILL.md 的觸發句按需載入，不單獨作為 skill 入口。
>
> 本文件中標 `（R-NNN）` 的規則源自真實失敗——改或刪該規則前，先讀 retro/RETRO.md 對應條目確認變更不會重開該失敗。

## Tier B Bootstrap 路徑（骨架工作，無業務邏輯）

空專案或新模組的純結構性工作：目錄結構、框架接線、CI、工具鏈。**沒有使用者情境可盤（usage 分析跳過）、行數天然爆表（不適用 5 items／300 行上限）**，但選型是使用者的決定，且這是引入測試框架成本最低的時點——路徑圍繞這兩點設計：

1. **Bootstrap 清單取代 Spec**：產出 `spec/<run_id>-bootstrap.md`，內容三段——要建什麼（逐項）、選型與理由（語言／框架／工具鏈，含捨棄的選項）、明確不做什麼（業務邏輯零容忍，出現即回 Router 重新判級）
2. **精簡風險分析**：只跑部署、資料兩面向（其餘四面向對空骨架無意義），結論併入清單檔，不另建 `risk/` 檔
3. **一次 HITL（硬性）**：清單交使用者確認**選型**後才動工——選型錯了整個骨架重來，這是 Tier B 唯一真正的風險
4. **建 manifest**：`tier: "B"`、`spec_path` 指向清單檔、`usage_report_path: "skipped"`、`risk_report_path: "inline"`、確認後 `phase: "decomposed"`。**不建 `eval_state.json`**（骨架多為 CLI 與樣板產出，不走循環評分——eval 維度對 scaffolding 不對口）
5. **DoD 固定兩條（hook 強制）**：①本地 build／run 指令跑得通 ②**測試框架已建立且有至少一個會跑的示範測試**——此後這個專案所有 run 的本地測試 gate 都沒有「無測試框架」的後門可走。兩條都過才把 manifest 標 `bootstrap_verified: true`，並把全套測試指令寫入 manifest 的 `test_command`（後續 run 的 test-strategy script 從此讀）
6. **收尾**：manifest 標 `status: "completed"` 隨骨架一併 commit（附 `Run-Id: <run_id>` trailer）。hook 對 `tier: "B"` 豁免 eval 歸檔檔要求，但 `bootstrap_verified` 非 `true` 擋 commit

## Hotfix 通道（先止血、後補債；債是硬性的）

僅限**使用者明確宣告**緊急（線上事故／資損進行中）時啟用，agent 不可自行認定。Bugfix 的診斷前判規則見 CLAUDE.md「工作型態前判」。

1. **止血**：診斷（重現 → 根因 → 修法）→ 直接修 ＋ 本地測試驗證（部署規則不豁免：未經本地驗證仍不可 commit／部署）
2. **精簡溯源**：建 manifest `run/<run_id>.json`，填 `tier: "hotfix"`、`tier_rationale`（含使用者宣告緊急的依據）、`spec_inline`（診斷結論）、`phase: "hotfix"`、`risk_report_path` / `usage_report_path: "deferred"`、**`debt: ["risk", "test", "retro"]`**。**不建 `eval_state.json`**（不走循環評分）
3. **commit**：manifest 標 `status: "completed"` 後隨修正一併 commit，message 附 `Run-Id: <run_id>` 與 `Hotfix: true` trailer（hook 對 `tier: "hotfix"` 的 manifest 豁免 eval 歸檔檔要求，但 intent gate 照常）
4. **補債（事後必須，不是可選）**：事故解除後依序還債，還清一項就從 manifest 的 `debt` 移除一項：
   - `risk`：補跑 task-risk-analysis，產出 `risk/<run_id>.md`、回填 `risk_report_path`（發現 🔴 → 立即回報使用者，可能需要 follow-up run 修正）
   - `test`：補上覆蓋該 bug 的回歸測試，本地跑過後隨 follow-up commit 進 git（同樣附 `Run-Id: <run_id>` trailer）
   - `retro`：強制呼叫 retro subagent，根因寫入 `retro/RETRO.md`
5. **欠帳 gate（hook 強制）**：任一 manifest 的 `debt` 非空時，**不可啟動新 run**（流程管制的 subagent 呼叫會被擋，還債所屬的原 run 不受影響）——防止「緊急」變成常態逃生門

## 單一 run 原則與併發（worktree 隔離）

- **一個 worktree 同一時間只允許一個 in_progress 的 run**。這不是任意規定：`eval_state.json` 是單例、git staging area 也是單例，同工作區並行兩個 run 必然互相污染（staged 變更分不開、commit 切不乾淨）
- **要並行 → 開 `git worktree`**：每個 run 在自己的 worktree／branch 裡跑，單例假設在 worktree 內自然成立，收尾各自 commit 後合回主線。**≥2 個互不相依的 Tier 1 需求同時進來時，依 `parallel-run` skill 執行**（批次 HITL、背景 agent、merge 收尾的細節住在該 skill）
- **插單（run 跑到一半來了急件）**：原 run 的 worktree **原地凍結**（狀態已全在 manifest／`eval_state.json`／staging area 裡，不需要任何「暫停」操作），急件在新 worktree 處理，完成後回原 worktree 依 `eval-flow-resume` skill 接續
- hook 強制：呼叫流程管制的 subagent 時，若本工作區存在**其他** in_progress 的 manifest（run_id 與 `eval_state.json` 不一致）→ 擋，並提示「先收尾／封存既有 run，或開 worktree 並行」
- **`[P]` item 的並行執行由 fan-out 達成，不再有共用同一棵樹的併發 writer**：門檻滿足（`[P]` item ≥2 且各自預估 ≥150 行）→ 走「## Tier 2 [P] fan-out（worktree 並行）」節，各開 worktree 隔離，mine 模式在各自樹內正常生效；門檻不足 → 退回主 worktree **循序**執行（一次一個 item），亦無共用樹併發。舊「shared-tree join barrier」概念隨共用樹模型一併移除；跨 item 的全套測試把關由 rolling merge 段的全套 baseline gate（見 `parallel-run` skill 步驟 8）負責

## Tier 2 [P] fan-out（worktree 並行）

Tier 2 run 內符合門檻的 `[P]` item 各開 git worktree 並行執行，取得真正的 worktree 隔離：每個 item 在自己的樹裡，`git diff --cached` 天生乾淨、mine 模式復活。本節描述三段式 fan-out 執行協定，由**主 flow**（前景，判門檻／開 worktree／rolling merge）編排、**背景 item agent**（在各自 worktree 跑迷你 run，具備 Bash／Write／Edit 工具）執行、收尾序列**直接引用 `skills/parallel-run/SKILL.md`**（避免兩處漂移）。改此 skill 的 run 自身序列跑、不 fan-out（新機制首次執行不用在改它自己的 run 上）。

### 門檻與退回

fan-out 僅在「**`[P]` item ≥2 且各自預估 ≥150 行**（以 task-decomposer 的 `~<行數>行` 欄位 ×2 校準估計為準）」時啟動。估計不準即不 fan-out（保守偏循序）。不滿足門檻 → 該批 `[P]` item 退回主 worktree **循序**執行（不開 worktree），步驟 3 預設仍派 checker、升級改派 code-reviewer 時用循環 step 2 的 file-scoped diff 收斂（引用循環 step 2 的規則，不在此重述）。含「有意行為變更需更新既有測試」的 item 不可進 fan-out 批，改留循序段——理由與 `parallel-run` skill 相同：既有測試只增不改是 merge gate 的裁判前提，破掉它等於裁判換人、全套綠燈失去安全保證。

### 三段式執行協定

三段的跨段不變量：**prep 段的父 manifest 標 `completed` 是 fan-out 的必要前提，fan-out 不可提前**。這個跨段條件的機械依據有二：`eval_gates.py` 的 `check_other_runs`（約 :155）對同工作區另一個 in_progress manifest 直接 block subagent 呼叫——父 run 若保持 in_progress，item worktree 裡的 code-writer 就會被擋；歸檔 gate 對未歸檔的 `eval_state.json` 擋 commit——prep 段必須照現行 step 6 正常歸檔後才能 commit，commit 完父 manifest 才能標 `completed`。

**① 循序前置段（prep run）**

依賴型 item（task 中標 `depends`、不可標 `[P]`，典型如 DB schema 定義、共用型別）在主 worktree 循序做完，照現行 step 6 正常歸檔＋commit，父 manifest 標 `status: "completed"` 後才進入 fan-out。這批 item 是各 `[P]` item branch 出去時的共同基礎，必須先落地才能確保各子 worktree 起點一致。沒有 depends 型 item 時，此段為空、直接進入 fan-out。

**② Fan-out 段**

主 flow 為每個符合門檻的 `[P]` item spawn 一個背景 item agent，**worktree 交由 harness 建立**：以 `Agent` 工具的 `isolation: "worktree"` 啟動，harness 建 `.claude/worktrees/agent-<id>/` 並在啟動時釘定該 agent 的工作目錄。細節與禁止事項見 `parallel-run` skill 步驟 5（**禁止改用「主 flow 先 `git worktree add`，再叫 agent 自己進去」**——2026-07-29 實測證明 repo root 啟動的 subagent 無法切入，`EnterWorktree` 會拒絕；亦禁止用 `cd` 替代，那會使 gate 判到主工作區）。

branch 名稱由 harness 指派（非 `feat/<父run_id>-item-<id>`），item agent 須在回報中附上；全族溯源靠 commit trailer `Parent-Run-Id: <父run_id>`，不靠 branch 命名。**worktree 起點見 `parallel-run` 步驟 5**（單一來源，本節不自述以免漂移；現況為主線本地 HEAD，設定未套用時會退回 origin）。item agent 起手仍必須依 `parallel-run` 步驟 6 的「起手三步」`git merge main` 同步並驗證前提——該步是設定失效時的唯一攔截點（本節的 prep 段成果若未 push，正是靠這一步才進得了 item worktree）。

然後同一訊息 spawn 全部背景 item agent（一 item 一 agent，並發啟動）。每個背景 agent 以**獨立 sibling 迷你 run**執行完整 Tier 2 循環：

- **子 manifest**：`run/<父run_id>-item-<id>.json`，填入 `parent_run_id: <父run_id>`、`spec_path` 指回父 Spec（`spec/<父run_id>.md`）、`tier: 2`、`status: "in_progress"`，以及自己的 `run_id`、`created_at`、`phase`。
- **自己的 `eval_state.json`**（在自己 worktree 初始化），自己的 eval_state 貫穿自己的 code-writer → review（含完成度節）→ step 5 本地測試 → 自己歸檔。
- **mine 模式在隔離樹下復活**：各 worktree diff 乾淨，未提交變更只屬於自己，`python3 .claude/hooks/test_baseline.py mine --strike-key <item_id>` 可正常推導範圍。
- **hook gate 在各 worktree 內獨立生效（有前提，非天然成立）**：每個 worktree 有自己的 staging area 與 `eval_state.json`，所有現行 gate 照常運作、零後門——**前提是 hook 以該次 tool call 的實際 cwd（payload 的 `cwd`）解析所屬 worktree 根後才 chdir**。`CLAUDE_PROJECT_DIR` 由 Claude Code 釘死在 session 啟動目錄、**不隨 worktree 移動**（`EnterWorktree` 與背景 subagent 皆然），若 gate 逕以它決定工作區，worktree 內的 run 會誤用主工作區狀態：subagent 呼叫 gate 誤判、commit gate 因讀主工作區空 index 而靜默失效。此解析住在 `.claude/hooks/eval_gates.py`，改動該處等同動搖本節前提。**限制**：`CLAUDE_PROJECT_DIR` 為 git 儲存庫子目錄的專案開 worktree 時會解析到 worktree 根（不拼接子路徑），該類專案目前不支援 fan-out。
- **自己 branch commit**：step 6 收尾 commit 附 trailer `Run-Id: <子run_id>` 與 `Parent-Run-Id: <父run_id>`（後者讓主 session 一次 grep `Parent-Run-Id: <父run_id>` 撈全族 commit）。禁止 push、禁止切 branch、禁止把自己的 branch 合進 main（同 `parallel-run` skill 的背景 agent 規則；起手的 `git merge main` 是反方向同步，允許且必要）。
- **BUGLOG 條目寫進回報內容、不 append 檔案**：沿 `parallel-run` skill 規則——各 worktree grep 自己的快照會漏看對方的條目，兩層制升級判定由主 session 於 merge 後統一做。
- **blocker 出在 main 既有 code 時禁止在 item worktree 修**：標明後依 `parallel-run` skill 的「卡住／HITL 協定」停下，由主 session 在 main 上走 bugfix 流程，修完後各 item worktree `git merge main` 同步（修一次、多支受惠）。
- 卡住（2 次真失敗、任何需使用者裁決的事）→ 依 `parallel-run` skill 的「卡住／HITL 協定」停止並回報主 session，manifest 標 `status: "blocked"`，落盤卡點報告 `run/<子run_id>-blocked.md`，**不自行猜測往下**。

角色確認（retro 約束）：主 flow 能開 worktree、讀寫 manifest（成立）；背景 agent 在隔離 worktree 內具 Bash／Write／Edit、hook gate 照常生效且能 commit 自己 branch（成立——gate 生效以上一項的 root 解析前提為條件）；引用 `parallel-run` skill 的收尾步驟確實存在於該 skill（收尾序列見 `parallel-run/SKILL.md` 步驟 7–10，機械檢查①②見步驟 8 的子項 8.1／8.2，已 Read 佐證）。

**③ Rolling merge 段**

直接引用 `skills/parallel-run/SKILL.md` 的收尾序列（步驟 7–10），不重寫——避免兩處機制描述漂移。重用其：① 測試只增不改機械檢查（`git diff main...<branch>` 過濾測試路徑，出現 M／D 不 merge；`<branch>` 取自該 item agent 回報的 harness 指派 branch）② 實際交集重驗（本支與其他未合支的實際 changed-file 清單取交集，非空停下回報）③ 後合者先 `git merge main` 同步再重跑相關測試 ④ 全套 baseline gate（`git merge <branch>` 後跑全套，判準為相對 merge 前 main baseline 無新增失敗；批次層 baseline 快照須手動帶 `--cmd`）⑤ BUGLOG 帶回統一 append＋兩層制升級判定＋清理 worktree 與 branch（append 前 grep 舊條目判是否升級 RETRO；清理**可能因 harness 的 worktree lock 而失敗，失敗時不可強拆**，依 `parallel-run` 步驟 8.5 處置——未上鎖者照常移除，仍上鎖者列入回報交由使用者或 harness 回收）。誰先完成先收，不等全批。**本①-⑤為重點提示，完整子步驟以 `parallel-run` 步驟 8 之子項 1–5 為準、不由本清單替代。**

一族 commit 完成後，可用 `git log --grep "Parent-Run-Id: <父run_id>"` 反查全族。

### 錯誤路徑與批次中斷恢復

**F-err1（rolling merge 後測試紅燈）**：全套測試在 merge 後出現新增失敗，根因跨兩支 branch 語意衝突。由 bugfix 走既有「診斷先行」流程、在**主 session（main）**做（單一 worktree 視野只有一半）——見 `parallel-run` skill 步驟 9。

**F-err2（機械檢查② 實際交集非空）**：fan-out 前置預估 disjoint、但合併前重驗時本支與其他未合支的實際 changed-file 清單有交集——disjoint 前提被實際變更打破。該支停下回報、退出並行改循序——見 `parallel-run` skill 步驟 8 子項 2（8.2）。

**G（批次中斷恢復）**：主 session 死掉後，以下痕跡機械重建批次狀態，不靠記憶——見 `parallel-run` skill 步驟 14：
- `git worktree list`：還有哪些 worktree 存活
- 各子 manifest `status`（in_progress／blocked／completed）：哪支還在跑、哪支卡住
- `git log --grep "Parent-Run-Id: <父run_id>"`：哪支已 merge 進 main
- `run/parallel-merge-*.test_baseline.json` 存在與否：全套 baseline 是否已快照

**特別檢查項——已 merge 但 BUGLOG 未 append 的遺失窗口**：子 manifest 標 `completed`、commit 已在 main 的 `git log` 內，但 `retro/BUGLOG.md` 沒有對應條目（收尾步驟 8.5 的 append 在 session 死掉前未完成）。重建後逐支確認：已 merge 的 run 有無帶 BUGLOG 條目（回報內容或卡點報告），有條目未 append → 補問使用者確認後補 append，並依兩層制做升級判定。
