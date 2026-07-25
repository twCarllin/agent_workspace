# 使用情境報告 — Tier 2 [P] item worktree 並行  (run_id: 2026-07-25-tier2-p-worktree)

> 本報告分析對象是「流程框架變更」：為 Eval Flow 增加 Tier 2 run 內 [P] item 的 worktree 並行（fan-out）能力，並落地 file-scoped diff 修法。
> 「使用者／角色」= 未來執行 flow 的主 session agent、接手續跑的 AI／工程師、以及 hook gate（系統角色），**不是終端 app 使用者**。情境單位是「flow 執行時會走到的路徑」。
> 本報告自足可讀，不依賴對話上下文。情境 id 為 task-decomposer 的對映錨點。
> Spec 第 3 節 D1–D4 為已定案決策，本報告不重開；Spec 第 7 節開放問題 2–4 已併入本報告「開放問題」節。

## 角色

- **主 session agent（編排者）**：跑一個 Tier 2 run 的主控。判 fan-out 門檻、切 prep／fan-out 兩批、產子 manifest、spawn 背景 agent、跑 rolling merge 收尾。是本變更新增行為的主要觸發者。
- **item 背景 agent（迷你 run 執行者）**：在自己的 worktree 內以獨立 sibling 迷你 run 跑完整 Tier 2 循環（code-writer → review∥verify → step5 測試 → 自己歸檔、自己 branch commit）。禁止碰主工作區與其他 worktree。
- **循序 sub_task 執行者（退回路徑 / prep 段）**：門檻不滿足退回、或 prep（depends）item 時，在主 worktree 循序做，配 file-scoped diff。此角色也是主 session（同一實體，不同執行模式），但行為不同故分列。
- **code-reviewer / task-verifier（唯讀審查者，系統角色）**：讀 staged diff 核 scope 與 DoD。本變更改變其讀 diff 的範圍（file-scoped）。
- **hook gate（`eval_gates.py`，系統角色）**：PreToolUse 攔截亂序 subagent 呼叫與不合規 commit。fan-out 期間「多 branch 未合／多 manifest」中間狀態不可被它誤擋。是被副作用影響的角色，也是唯一的自動化裁判。
- **續跑者（接手的 AI／工程師，維運角色）**：主 session 死掉／compact 後，靠 `git worktree list`＋各 manifest＋`git log` grep 機械重建批次狀態續跑。不參與對話即需讀檔接手。
- **溯源反查者（維運 / 稽核角色）**：事後要把「一功能一族 run」的所有 commit 反查回父 run，靠 `parent_run_id`＋commit trailer。

## 情境

### A — 主 session 判門檻滿足、觸發 fan-out（happy path）  角色: 主 session agent
- 前置: Tier 2 run 前置 0–3 已過（Spec／usage／task 檔齊、`phase: decomposed`）；task 檔內 [P] item ≥2 個且各估計 ≥150 行。
- 操作: (1) 跑 prep 段（見 B）→ 父 manifest 標 `completed`；(2) 為每個符合門檻的 [P] item 從當前 run HEAD 切 `feat/<run_id>-item-<id>` worktree；(3) 產子 manifest `run/<run_id>-item-<id>.json`（`spec_path` 指回父 Spec、`parent_run_id`=父 run_id）；(4) 同一訊息 spawn 全部背景 agent；(5) rolling merge 收尾（見 F）。
- 預期: 每個 item 在自己 worktree 跑完整 Tier 2 循環、各自 branch commit，rolling merge 回 main，產出一族 commit（各帶自己 Run-Id、可由 parent_run_id 反查全族）。
- I/O: input `父 run 的 task 檔 + [P] item 清單 + 各行數估計` / output `N 個 feat branch + N 個 item commit + main 上一族 commit` / 副作用: 建 N 個 git worktree、寫 N 個子 manifest、寫 N 個子 eval_state（各 worktree 內）、spawn N 個背景 agent、merge 進 main、統一 append BUGLOG。

### B — prep 段（依賴型 item 循序落地）  角色: 循序 sub_task 執行者
- 前置: fan-out 觸發前；task 檔含標 `depends`／不可 [P] 的 item（DB schema、共用型別等）。
- 操作: 在主 worktree 循序做完 depends item → 照現行 step 6 正常歸檔（`archive` 刪 eval_state、產 `run/<run_id>.eval.json`）＋commit → 父 manifest 標 `completed`。
- 預期: depends item 落地成為 [P] item branch 的共同基礎；父 run 正常收尾（gate 全程照規則走、零後門）。
- I/O: input `depends item 清單` / output `prep commit（父 Run-Id trailer）+ 父 manifest completed` / 副作用: 主 worktree commit、歸檔父 eval_state、更新父 manifest phase→completed。
- 註（載入證據）: 父 manifest 必須先 `completed` 才 fan-out——`eval_gates.py:169` `check_other_runs` 對「同工作區存在另一 in_progress manifest」直接 block subagent 呼叫；父 run 保持 in_progress 會讓 item worktree 內的 hook 因此擋掉 code-writer。且 prep commit 若父 eval_state 未歸檔會被歸檔 gate（eval_state 尚存擋 commit）攔死。此為 D4「prep 自成一 run」的機械依據。

### C — 門檻不滿足，退回主 worktree 循序（happy path 分支）  角色: 循序 sub_task 執行者
- 前置: [P] item <2 個，或有 item 估計 <150 行。
- 操作: 該批 [P] item 退回主 worktree **循序**執行（不開 worktree）；派 code-reviewer／task-verifier 時 prompt 指示改用 `git diff --cached -- <該 sub_task 的 files>`（files 取自 eval_state 的 `list-files` helper）。
- 預期: 循序做完，驗證範圍**只含當前 sub_task 的檔案**，不含前面 sub_task 的累積變更；一個 run 一個原子 commit（退回路徑沿用單 run 語義）。
- I/O: input `[P] item 清單（不夠門檻）` / output `主 worktree 循序 commit` / 副作用: file-scoped diff 派工（不改 staging 行為，只改 reviewer/verifier 讀取範圍）。

### C-edge1 — 兩個 sub_task 改到同一檔案（已知邊界）  角色: 循序 sub_task 執行者
- 觸發: 循序做時，sub_task N 與 sub_task N-1 都改到同一檔案。
- 預期: `-- <file>` 仍會把兩者對該檔的變更一起帶出（file-scoped 無法區分同檔的跨 sub_task 變更）；prompt 註「同檔跨 sub_task 時以 task 描述判歸屬」，不上更重機制。
- I/O: input `同檔跨 sub_task 變更` / output `該檔全部變更帶入當前驗證範圍` / 副作用: 無；屬已接受的驗證精度降級（Spec 4.3 明文）。

### D — item 背景 agent 跑完整迷你 run（happy path）  角色: item 背景 agent
- 前置: A 已開好 worktree、spawn 帶指示（工作目錄固定、禁碰他樹、載 eval-flow Tier 2 循環、既有測試只增不改、BUGLOG 不落盤、commit 限自己 feat branch）。
- 操作: 在自己 worktree init 子 eval_state → 跑 code-writer → review∥verify → step5 本地測試 → 自己歸檔 → 自己 branch commit（trailer 帶自己 Run-Id）。
- 預期: 乾淨 diff（`git diff --cached` 天生只含本 item）、mine 模式復活、hook gate 在本 worktree 內獨立生效；完成即回報主 session。
- I/O: input `子 manifest + 父 Spec + 分派的 item` / output `feat branch 上一個 item commit + 子 eval.json 歸檔` / 副作用: 本 worktree 內 git add／commit、寫子 eval_state 並歸檔、BUGLOG 條目寫進**回報內容**（不 append 檔案）。

### D-err1 — item 背景 agent 卡住（2 次真失敗／升級逃生門／需裁決）  角色: item 背景 agent
- 觸發: 循環內 2 次真失敗、觸發升級逃生門（>5 items／歧義／遠超 300 行）、或任何需使用者裁決的事。
- 預期: 停前落盤（硬要求）——子 manifest 標 `status: blocked`＋blocked_reason，寫自足卡點報告 `run/<run_id>-item-<id>-blocked.md`（重現步驟、根因假設、試過什麼、要裁決的問題與選項）；落盤後才停，不自行猜測往下。凍結不擋其他 item（照常跑、照常 rolling merge）。
- I/O: input `失敗現場` / output `blocked manifest + 卡點報告` / 副作用: 本 worktree 原地凍結；主 session 收到回報後不立刻 merge 該支。
- 開放問題連結: 卡點報告命名慣例（見開放問題 5）。

### D-err2 — blocker 出在 main 既有 code  角色: item 背景 agent
- 觸發: item 背景 agent 發現 blocker 根因在 main 既有 code（非本 item 新寫）。
- 預期: **禁止在 worktree 修**；標明後依卡住協定停下，由主 session 在 main 上走 bugfix 流程（診斷先行→判級→修），修完本 worktree `git merge main` 同步再續跑（修一次、兩支受惠、merge 零衝突）。
- I/O: input `main 既有 code blocker` / output `回報主 session + 本支凍結待同步` / 副作用: 主 session 在 main 上另起 bugfix；本 worktree 待 `git merge main`。

### D-err3 — item 需改既有測試（有意行為變更混入 fan-out 批）  角色: 主 session agent / item 背景 agent
- 觸發: 某 item 含「有意行為變更、需更新既有測試（含 fixture／conftest／測試工具檔）」，卻被分進了 fan-out 批。
- 預期: **前置就應篩掉**——含此類 item 不可進 fan-out 批（會破 merge gate 的「既有測試只增不改」裁判前提），改留循序段。若漏篩到背景 agent 才發現需改既有測試 → 觸發卡住即停，該 item 退出並行、改序列跑。
- I/O: input `需改既有測試的 item` / output `退出 fan-out、回主 worktree 循序` / 副作用: 無 merge；該 item 改由循序段處理。
- 註: 這是 DoD 3 的正確性核心，也是與 parallel-run 同規則的分岔點（Spec 4.4）。

### E — 主 session 誤把 depends item 判入 fan-out 批（編排錯誤，prose 無 hook 強制）  角色: 主 session agent
- 觸發: 主 session 依 skill 文字判門檻／切批時，誤把標 `depends` 的 item 放進 fan-out 批（門檻與切批是 prose 驅動，hook 不攔）。
- 預期: 兜底靠子 run 內既有 gate＋merge 機械檢查②（實際 changed-file 交集非空 → 停下回報）；skill 應寫成機械可查的檢核步驟（比照 parallel-run 前置的兩兩比對）降低發生率。
- I/O: input `錯誤切批` / output `merge 機械檢查②攔截（交集非空）或子 run gate 失敗` / 副作用: 可能到 merge 段才被抓，浪費一支 worktree 的工。
- 開放問題連結: 門檻判定要不要進 hook 硬檢（見開放問題 6）。

### F — rolling merge 收尾（happy path）  角色: 主 session agent
- 前置: item 背景 agent 陸續回報 completed。
- 操作: 直接套 parallel-run 收尾序列——①機械檢查測試只增不改（`git diff main...feat/<run_id>-item-<id> --name-status` 過濾測試路徑，出現 M／D 不 merge）；②實際檔案交集重驗（本支與其他未合支實際 changed-file 交集非空 → 停）；③後合者先 `git merge main` 同步＋重跑自己測試；④`git merge` 進 main→全套測試 baseline gate（相對 merge 前 main 無新增失敗）；⑤BUGLOG 帶回統一 append＋兩層制升級判定→移除 worktree／刪 branch。誰先完成先收，不等全批。
- 預期: 一族 commit 進 main，各帶自己 Run-Id、可 parent_run_id 反查；BUGLOG 條目統一 append（含 grep 升級判定）；worktree 清乾淨。
- I/O: input `completed 的 feat branch` / output `main 上 merge commit + 清空 worktree + BUGLOG append` / 副作用: merge 進 main、寫 `run/parallel-merge-YYYY-MM-DD.test_baseline.json`（批次層級快照）、append `retro/BUGLOG.md`、`git worktree remove`＋刪 branch。

### F-err1 — merge gate 全套測試紅燈  角色: 主 session agent
- 觸發: `git merge` 進 main 後全套測試相對 baseline 出現新增失敗（跨兩支 branch 的語意衝突）。
- 預期: 由 bugfix 走既有「診斷先行」流程，在**主 session**（main）做（語意衝突根因跨兩支、單一 worktree 視野只有一半）；診斷完照常判級修復。
- I/O: input `merge 後新增失敗` / output `主 session bugfix` / 副作用: 主 session 在 main 上診斷修復，其餘支照常。

### F-err2 — 機械檢查②實際交集非空（disjoint 前提被破）  角色: 主 session agent
- 觸發: 兩支未合 branch 的實際 changed-file 清單交集非空（前置 2 是預估，此處以實際值重驗）。
- 預期: 停下回報，不自行硬解——disjoint 假設已破，該支退出並行、之後改序列。
- I/O: input `實際交集非空` / output `停下回報` / 副作用: 該支不 merge、待人裁決。

### G — 批次中斷恢復（主 session 死掉／compact）  角色: 續跑者
- 觸發: fan-out 期間主 session 死掉或 context compact，需接手續跑。
- 操作: 用既有痕跡機械重建，不靠記憶——`git worktree list`＋各 worktree manifest（in_progress／blocked／completed）看還有哪些 item run；main 的 `git log` 找 Run-Id trailer 看哪支已 merge；`run/parallel-merge-*.test_baseline.json` 看全套 baseline 是否已快照；單一 item run 內部進度走 eval-flow-resume。
- 預期: 從對應收尾步驟續跑，無靜默遺失。
- I/O: input `殘留痕跡` / output `重建的批次狀態` / 副作用: 無（純讀）。
- 邊界: 「已 merge 但 BUGLOG 未 append」的遺失窗口——子 manifest 已 merge 而 BUGLOG 無對應條目 → 恢復時列入機械重建檢查項，補問（風險報告 §3 對策）。

### H — 溯源反查（事後把一族 commit 查回父 run）  角色: 溯源反查者
- 觸發: 稽核／debug 要找某父 run 的所有 commit（prep run＋N 個 item run）。
- 預期: 依開放問題 2 的定案方式反查（見開放問題 2）——傾向子 run commit trailer 同附 `Parent-Run-Id`，一次 `git log --grep` 撈全族。
- I/O: input `parent_run_id` / output `該族全部 commit` / 副作用: 無（純讀）。
- 開放問題連結: trailer 附 Parent-Run-Id vs 逐 manifest 撈（見開放問題 2）。

### I — hook 讀舊 manifest（無 parent_run_id 欄）  角色: hook gate
- 觸發: hook／stats 掃 `run/*.json` 時讀到本變更前的舊 manifest（無 `parent_run_id` 欄）。
- 預期: 不可炸——欄位設計為可選，無此欄視同無父 run（比照 `scout_report_path` 舊欄相容慣例）；`manifest_phase` 既有向後相容推導不動。任何 hook 相容性改動須帶測試（DoD 4）。
- I/O: input `舊 manifest（無新欄）` / output `照常運作、視同無父 run` / 副作用: 無。

### J — 本 run 自身執行（自我修改風險）  角色: 主 session agent
- 觸發: 本 run 改的是自己正在跑的 eval-flow skill，改完即生效，後半段會踩到自己改過的規則。
- 預期: 本 run **自身序列跑、不觸發自己的 fan-out**（新機制首次執行留給下一個真實 Tier 2 需求）；部署外層前先收外層 in_progress run、清孤兒 agent（memory 慣例）。
- I/O: input `本 run 的 task` / output `序列 commit（不 fan-out 自己）` / 副作用: 修改 eval-flow／parallel-run／task-decomposition skill＋兩 agent＋可能 hook。
- 註: 這是操作約束（風險報告 §5 對策），非可選路徑——避免用未驗證的新機制跑改它自己的 run。

## 與現有功能互動點

- **`skills/eval-flow/SKILL.md`「單一 run 原則與併發」節（273–279）**：現行「單一 run 內 [P] 併發 code-writer 共用同一棵樹」段（含測試 barrier、mine 不適用註）需改寫——fan-out 後 [P] item 各開 worktree，共用樹段變成「門檻不足時的循序退回」語義。回歸風險：舊段落若沒清乾淨，接手者會拿到自相矛盾的兩套 [P] 併發語義。
- **`skills/parallel-run/SKILL.md`**：本變更重用其 worktree 開設、背景 agent spawn、rolling merge 收尾序列、機械檢查、卡住協定、批次中斷恢復。互動點：parallel-run 前置是「逐一判級＋批次 HITL」，Tier 2 fan-out 換成「已過父 run 前置 0–3」。若抽共用機制成獨立節，兩處引用須一致，否則 parallel-run 的既有語義（跨獨立 Tier 1 需求並行）可能被誤改。
- **`skills/task-decomposition/SKILL.md` Step 4 [P] 標註 + 行數估計格式**：可能需補「≥150 行才觸發 worktree」註記與 item 大小估計欄位。互動點：既有 `~<行數>行 ×2 校準` 格式是門檻判定的行數來源（開放問題 3）；disjoint 檔案前提不動（Spec Non-goal）。
- **`.claude/agents/task-verifier.md`（行 21「固定使用 git diff --cached」）＋ `code-reviewer.md`（行 15–18 同）**：file-scoped diff 修法動這兩處——改成 `git diff --cached -- <files>`。回歸風險：這兩個 agent 也被非 fan-out 的一般 Tier 1／2 循序 run 使用，改動 prompt 對所有 run 生效，須確保 `-- <files>` 為空／單檔時行為正確，且「staging 為空即停」的既有守則不被破壞。
- **`.claude/hooks/eval_gates.py`（`check_other_runs` @155–174、`check_task_gate` @201–245、`manifest_phase` @135–144、`MANIFEST_RE` @22–24）**：高風險互動面。(1) `check_other_runs`@169 對「同工作區另一 in_progress manifest」硬 block——D4 靠此推出「prep 必須先 completed」＋「item worktree 彼此隔離（gate 只掃當前 worktree 的 `run/*.json`）」；子 manifest 命名 `run/<run_id>-item-<id>.json` 須被 `MANIFEST_RE` 正確識別（不被 `.eval`／`.test_baseline` 排除誤傷）。(2) fan-out 期間「多 branch 未合／主 worktree 尚無完整變更」的中間狀態，gate 不可誤擋（開放問題 4）。(3) 若加 `parent_run_id` 相容檢查須帶測試。**改壞方向**：誤擋（commit 全被攔）或誤放（gate 靜默失效、綠燈不再是證據）。
- **`retro/BUGLOG.md`**：fan-out 沿用 parallel-run「條目隨回報帶回、merge 後統一 append＋兩層制升級判定」——兩個 worktree 各 grep 自己快照會漏看對方，故不落盤。互動點：中斷恢復時「已 merge 但未 append」的遺失窗口需列入機械重建檢查。

## 正確性假設清單（需使用者逐條裁示）

1. **[P] item 之間檔案 disjoint**（同一父 run 內 fan-out 的 item 不共用檔案）。消費點：merge 機械檢查② `skills/parallel-run/SKILL.md:50`（實際 changed-file 交集重驗）＋ task-decomposition Step 4 [P] 標註前提。被破壞時可觀察差異：兩支實際 changed-file 交集非空 → 機械檢查② stop 回報（F-err2）；若檢查②被略過，merge 會產生語意衝突、全套測試出現新增失敗（F-err1）。**此為真需求**（有明確消費點與可觀察 stop 行為），保留。
2. **既有測試只增不改（fan-out 批內）**。消費點：merge 機械檢查① `skills/parallel-run/SKILL.md:49`（`git diff main...branch --name-status` 過濾測試路徑，出現 M／D 不 merge）。被破壞時可觀察差異：測試路徑出現 M／D → 檢查①擋 merge、列 diff 給人過目。**真需求**——這是 merge gate 的裁判前提，被繞過則全套綠燈不構成安全證據（Spec Non-goal 4 明文不鬆動）。保留。
3. **父 manifest 必須先 `completed` 才 fan-out**。消費點：`.claude/hooks/eval_gates.py:169`（`check_other_runs`：同工作區存在另一 in_progress manifest → block subagent 呼叫）＋歸檔 gate（eval_state 尚存擋 commit）。被破壞時可觀察差異：父 run 保持 in_progress → item worktree 內 spawn code-writer 被 hook block（訊息「本工作區已有另一個 in_progress 的 run」）；prep commit 若 eval_state 未歸檔被歸檔 gate 攔。**真需求**（已抽查原始碼驗證），保留。這是 D4「prep 自成一 run、全程照 gate」的機械根據。
4. **item worktree 彼此隔離、子 manifest 不互相干擾 gate**。消費點：`check_other_runs` @157 只 `glob.glob("run/*.json")` 掃**當前工作區**的 `run/`。被破壞時可觀察差異：若各 worktree 的 `run/` 目錄實際共享（例如 worktree 未正確隔離 `run/`），A worktree 的 in_progress 子 manifest 會擋 B worktree 的 subagent 呼叫。**待確認的隱含假設**——git worktree 各自有獨立工作目錄故 `run/` 天然分離，但子 manifest 命名同帶父 run_id 前綴（`<run_id>-item-<id>`），需確認 fan-out 期間主 worktree 是否也會看到子 manifest（若子 manifest 也 commit 進各 branch 而未合回 main，主 worktree 的 `run/` 不會有它們→安全）。建議在分拆時把「子 manifest 落在哪個 worktree／是否進主 worktree 的 `run/`」寫成明確 item DoD 驗證。
5. **fan-out 不涉及順序／決定性／時序類正確性需求**。全篇 Spec 的並行單位是 run、隔離單位是 worktree，rolling merge「誰先完成先收、不等全批」明示無順序要求；正確性靠「檔案 disjoint＋既有測試只增不改＋全套 baseline gate」三者，不靠 item 完成順序。**無保序類假設**——不需要為此增設情境。

## 開放問題（需使用者確認）

1. **本 run 自身是否序列跑、不 fan-out 自己？**（情境 J）預設傾向：序列跑、不觸發自己的 fan-out（新機制首次執行留給下一個真實 Tier 2 需求，風險報告 §5 對策）。若改「用新機制跑自己」則須先讓 fan-out 全套硬化，且踩到「改到一半的規則即時生效」的自我修改風險，強烈不建議。此問題影響本 run 的執行模式，須先拍板。

2. **（Spec 開放問題 2）多 commit 下 Run-Id 溯源方式**（情境 H）：家族反查用「`git log --grep "Run-Id: <parent_run_id>"` 撈 prep run ＋逐子 manifest 各撈一筆」，或子 run commit trailer 同附 `Parent-Run-Id: <parent_run_id>`（一次 grep 撈全族）？預設傾向：後者（trailer 附 `Parent-Run-Id`）。若選前者則反查需多步（逐 manifest），且中斷恢復時反查邏輯更脆。此問題影響 code-writer commit trailer 格式與溯源反查 item 的 DoD。

3. **（Spec 開放問題 3）門檻的行數估計來源**：150 行以 task-decomposer 的 item 行數估計（`~<行數>行`，已 ×2 校準）為準；估計不準時保守處理（估不準 → 不 fan-out，走循序）？預設傾向：以 task-decomposer 估計為準＋估不準即不 fan-out（保守偏循序）。若要更精確（如實際寫完才知）則門檻判定無法在 fan-out 前定，機制失去意義。此問題影響 task-decomposition skill 是否補「≥150 行觸發 worktree」註記與大小估計欄位。

4. **（Spec 開放問題 4）hook gate 對「多 branch 未合」中間狀態的容忍**（情境 I、E、互動點 hook）：fan-out 期間主 worktree 尚無完整變更、多子 manifest 並存，gate 不可誤擋。需確認：(a) 子 manifest 命名 `run/<run_id>-item-<id>.json` 是否需調整以避免 `MANIFEST_RE`／`check_other_runs` 誤傷；(b) 是否需為「fan-out 中間狀態」加 gate 相容邏輯（若需改 hook 則屬高風險面，須帶測試）。預設傾向：靠 worktree 天然隔離（各 worktree 獨立 `run/`）使 hook 零改動，僅在確認假設 4 不成立時才改 hook。此問題直接決定要不要動 `eval_gates.py`（本 run 判 Tier 2 的主因）。

5. **item 卡點報告命名慣例**（情境 D-err1）：parallel-run 用 `run/<run_id>-blocked.md`；fan-out 子 run 用 `run/<run_id>-item-<id>-blocked.md` 還是各 worktree 內的 `run/<run_id>-blocked.md`（因 worktree 隔離，同名不衝突）？預設傾向：各 worktree 內用 `run/<子 run_id>-blocked.md`（沿用 parallel-run 慣例，worktree 隔離下不衝突）。此問題影響背景 agent 派工指示與中斷恢復的檔案掃描 glob。

6. **fan-out 門檻判定要不要進 hook 硬檢**（情境 E，風險報告 §1 對策）：門檻判定（≥2 且各 ≥150 行）、prep／fan-out 切批目前是 prose 驅動、hook 不攔，判錯（如 depends item 誤入 fan-out）只靠 merge 機械檢查②兜底（到 merge 段才抓、浪費一支工）。要不要在 hook 加前置硬檢，還是接受「skill 寫成機械可查步驟＋子 run gate＋merge 檢查②」的三層兜底？預設傾向：後者（不加 hook 硬檢，避免再擴大高風險面）。若要加 hook 硬檢則 hook 改動面與測試量增加。此問題影響是否新增 hook item。
