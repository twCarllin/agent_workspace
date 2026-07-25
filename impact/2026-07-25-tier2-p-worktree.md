# 影響面盤點：Tier 2 [P] item worktree 並行  (run_id: 2026-07-25-tier2-p-worktree)

> Spec: `spec/2026-07-25-tier2-p-worktree.md`；本報告自足可讀，不依賴對話上下文。
> 證據來源：scout 證據檔 `scout/2026-07-25-tier2-p-worktree.md` 為主，關鍵斷言（MANIFEST_RE、check_other_runs、manifest_phase、file-scoped diff 目標行、呼叫端完整性）已抽查原檔／自行重跑 Grep 驗證。
> Spec 第 3 節 D1–D4 與 6 條 HITL 裁示為前提，本報告不重開。

## 1. 觸及模組清單

- `skills/eval-flow/SKILL.md` — 三段式 fan-out 執行、file-scoped diff 派工描述（step 3）、`[P]` 共用樹舊節（273–279）改寫。
- `skills/parallel-run/SKILL.md` — 抽出／標明 Tier 2 fan-out 重用點（worktree 開設、rolling merge、卡住協定）。
- `skills/task-decomposition/SKILL.md` — `[P]` 標註補「≥150 行才觸發 worktree」門檻註記與 item 大小估計欄位。
- `.claude/agents/task-verifier.md` — 行 21 `git diff --cached` 改 file-scoped（`-- <files>`）。
- `.claude/agents/code-reviewer.md` — 行 15 `git diff --cached` 改 file-scoped（`-- <files>`）。
- `.claude/hooks/eval_gates.py` — `parent_run_id` 向後相容、確認 `check_other_runs`／`manifest_phase`／`MANIFEST_RE` 對子 manifest 與多 commit 的既有行為（Spec 目標為零改動，須帶測試佐證）。
- `.claude/hooks/stats.py` — 未在 Spec 5 明列，但有獨立 `MANIFEST_RE`＋glob run/*.json＋讀 manifest 欄位，子 manifest 命名會影響其統計（見第 4 節與第 5 節）。
- `tests/test_eval_gates.py` — hook 任何相容改動的對應測試（DoD 4）；子 manifest／parent_run_id 若加檢查須在此補 case。
- `.claude/hooks/eval_state.py` — Spec 提「可能」動；經盤點**本 run 無須改**（`list-files` helper 已存在、子 eval_state 各 worktree 各自 init／archive，沿用現行子指令）。列此明示「盤過確認不動」。

## 2. 各模組既有慣例

### skills/eval-flow/SKILL.md
- **循環派工結構**：step 1 writer→step 2 `git add`→step 3 並發呼叫 reviewer＋verifier→step 4 匯合→step 5 本地測試→step 6 收尾（`skills/eval-flow/SKILL.md:80-97`）。file-scoped diff 派工描述須嵌入 step 3 附近，不破壞此序。
- **派工 prompt 硬約束區慣例**：知識前置（retro／模組 CLAUDE.md／impact report 慣例段，`:72-76`）、測試管轄註記（`:77`）、契約前置與仲裁句（`:78`）以「硬性步驟」列點、附出處引文原文。新增 file-scoped diff 指示須沿此體例（附一句可直接貼進 prompt 的指令）。
- **`[P]` 平行既有語義**：現行「單一 run 內 `[P]` 併發 code-writer 共用同一棵樹」＋測試 barrier＋mine 不適用註（`:69` 引 279 段、`:77` 末句、`:82` 末句「各開 worktree」）。改寫時三處引用須一併改，否則殘留自相矛盾語義。
- **中斷恢復慣例**：`git diff --cached -- <files>` 還原工作現場（`:233`）已是既有 file-scoped 用法——file-scoped diff 修法與此收斂方式一致，可引為先例。

### skills/parallel-run/SKILL.md
- **worktree 開設格式**：`git worktree add ../<repo>-<slug> -b feat/<run_id>`，run_id 慣例 `YYYY-MM-DD-<slug>`（scout 證據 `:88-91`）。fan-out 的 branch 命名 `feat/<run_id>-item-<id>` 是此格式的延伸。
- **rolling merge 序列**：機械檢查①測試只增不改→②實際交集重驗→③後合者先 `git merge main`→④全套測試 baseline gate（存 `run/parallel-merge-YYYY-MM-DD.test_baseline.json`）→⑤BUGLOG append＋worktree remove（scout 證據 `:99-107`）。fan-out 收尾直接套此序。
- **既有測試只增不改**：`git diff main...feat/<run_id> --name-status` 過濾測試路徑出現 M／D 即不 merge（scout 證據 `:93-97`）。fan-out 批的篩選規則沿用。
- **卡住協定落盤**：manifest 標 `status: "blocked"`＋blocked_reason＋自足卡點報告 `run/<run_id>-blocked.md`（scout 證據 `:109-113`）。子 run 卡點沿用（命名見 usage 開放問題 5）。

### skills/task-decomposition/SKILL.md
- **`[P]` 標註條件**：不共用檔案＋無資料依賴，兩者都要成立；有依賴標 `depends: <id>`，前置基礎 task 不可 `[P]`（scout 證據 `:115-124` 引 Step 4）。門檻註記須嵌此段。
- **item 行數估計格式**：`~<估計行數（含測試、已 ×2 校準）>行  files: ...`（scout 證據 `:126-132` 引 `:99-102`）。150 行門檻的行數來源即此欄。
- **行數校準慣例**：申報行數＝表列量級 ×2（naive 粗估系統性低估 2–3 倍，`skills/task-decomposition/SKILL.md:60`）。門檻判定須用 ×2 後的申報值，不是 naive 值。
- **300 行上限出處**：`git diff --cached` 小到 reviewer 能一次讀完（`skills/task-decomposition/SKILL.md:25`），與 150 行下限並存（下限觸發 fan-out、上限觸發再拆）。

### .claude/agents/task-verifier.md / code-reviewer.md
- **取 diff 慣例**：固定 `git diff --cached`，附「使用者指定 commit 範圍則用該範圍」（task-verifier `:21-24`、code-reviewer `:15-18`）。**staging area 為空即停止並回報**、不自行 fallback（task-verifier `:23`、code-reviewer `:17`）——file-scoped 改動須保住此守則（`-- <files>` 命中為空時仍走「空即停」而非 fallback 全域）。
- **不使用 unstaged `git diff`**：確保驗證範圍與最終 commit 一致（task-verifier `:24`、code-reviewer `:18`）——file-scoped 仍在 `--cached` 語義內，不破此前提。

### .claude/hooks/（eval_gates.py / stats.py）— Python 慣例
- **manifest 讀取容錯**：`load_json`（block on error，`eval_gates.py:66-71`）vs `load_json_quiet`／`load`（return None，`eval_gates.py:147-152`、`stats.py:33-38`）——掃描性讀取用 quiet 版容忍壞檔。
- **衍生檔排除寫進 pattern**：`MANIFEST_RE` 用 `(?<!\.eval)(?<!\.test_baseline)` 負向後查，「新增衍生檔種類時只改這裡」（`eval_gates.py:20-24` 註解）。新增衍生檔（如 `-blocked.md` 非 .json 不受影響；`.mine_log.json`／`.review-*.md` 已在別處清）。
- **向後相容慣例**：舊 manifest 無新欄不炸——`manifest_phase` 無 phase 欄由既有欄推導（`eval_gates.py:135-144`）；`scout_report_path` 舊檔無此欄視同 skipped（scout 證據 Manifest 欄位全集節）。`parent_run_id` 須比照此模式（可選欄、無此欄視同無父 run）。
- **gate 遙測**：block 時 `log_gate_hit` append `run/gate_hits.log`（`eval_gates.py:44-55`）。
- **測試慣例**：`unittest.TestCase`，class 名 `<主題>Test`（`ValidateStateTest`／`ManifestPhaseTest`／`ManifestRegexTest`／`TestFileDetectionTest`，scout 證據 `:157`）；直接呼叫函式斷言回傳／用 `assertRaises(SystemExit)` 驗 block（見 `tests/test_eval_gates.py:115-147` 對 `manifest_phase`／`MANIFEST_RE` 的 pattern）。新增子 manifest／parent_run_id case 沿此體例。

## 3. 可重用既有元件

- `.claude/hooks/eval_state.py` `cmd_list_files` `list-files` 子指令（scout 證據 `:41`，eval_state.py 166–173）— 輸出所有 sub_task files 聯集（逐行），**正是 file-scoped diff 的 `<files>` 來源**（`git diff --cached -- <files>`）。file-scoped 修法直接複用，無須新 helper。
- `skills/parallel-run/SKILL.md` rolling merge 序列全套（機械檢查①②、後合者同步、全套 baseline gate、BUGLOG 帶回，scout 證據 `:99-107`）— fan-out 收尾直接引用，不重寫。
- `skills/parallel-run/SKILL.md` worktree 開設＋背景 agent spawn＋卡住協定（scout 證據 `:88-91`、`:109-113`）— fan-out 段複用。
- `eval_gates.py` `MANIFEST_RE`（`:22-24`）與 `stats.py` `MANIFEST_RE`（`:30`）的衍生檔排除機制 — 已能正確識別／排除 `.eval.json`／`.test_baseline.json`；子 manifest `<run_id>-item-<id>.json` 天然被視為合法獨立 manifest（見第 4 節驗證），無須改 pattern。
- `manifest_phase` 向後相容推導（`eval_gates.py:135-144`）與其測試（`tests/test_eval_gates.py:113-129`）— `parent_run_id` 相容測試可比照此模式撰寫。
- `skills/test-strategy/SKILL.md` `git diff --cached -- <各 sub_task 的 files>` 定位肇事者（`:84`、`:103`）— file-scoped 收斂在既有 flow 已有先例，可引為一致性佐證。
- `skills/eval-flow-resume/SKILL.md:35` `git diff --cached -- <files>` 還原工作現場 — 同上，file-scoped 用法已存在。

## 4. 被改介面的呼叫端清單

### 介面 A：`parent_run_id`（manifest 新增欄位）
本 run 新增，codebase 中**尚無任何讀取端**。需相容的是「所有 glob run/*.json 並讀 manifest 欄位的地方」——它們讀舊 manifest（無此欄）不可炸：

- `.claude/hooks/eval_gates.py:157` `check_other_runs` — `glob.glob("run/*.json")` 逐檔讀 `debt`／`run_id`／`status`（`:164-169`）；不讀 parent_run_id，加欄不影響，但子 manifest 進入其掃描範圍（見介面 D）。
- `.claude/hooks/eval_gates.py:135` `manifest_phase` — 讀 `phase`／`task_file`／`usage_report_path`；不讀 parent_run_id，安全。
- `.claude/hooks/stats.py:50` `collect` — `glob.glob("run/*.json")` 逐檔讀 `run_id`／`tier`／`status`／`test_policy`／`hitl_confirmed_at`／`hitl_rejections`（`:54-64`）；不讀 parent_run_id，加欄不影響統計欄位，但子 manifest 會被計為獨立 run（見介面 D 影響）。
- `.claude/hooks/doctor.py` — 不 glob run/*.json、不讀 manifest 欄位（只讀 `eval_state.json`＋`settings.json`，`doctor.py:48-80`）；parent_run_id 無關。
- `.claude/hooks/test_baseline.py:100` — `manifest = f"run/{run_id}.json"` 為路徑組字串，非讀 manifest 內容欄位；不受影響。

  **查詢方法**：`grep -rn "parent_run_id\|Parent-Run-Id" --include=*.py --include=*.md --include=*.sh .`（排除 spec/usage/risk/scout/impact）→ 0 hits（純新增欄，無既有讀取端）。`grep -rn "run/\*.json\|glob.*run\|MANIFEST_RE\|manifest_phase" --include=*.py .claude/hooks/ tests/` → 命中上列 eval_gates.py（`:157,158,284,106,135,218,223`）、stats.py（`:30,50,52`）、test_baseline.py（`:100,130`）、test_eval_gates.py（`:115-147`）。

### 介面 B：`git diff --cached`（task-verifier / code-reviewer 取 diff 指令）→ 改 file-scoped `-- <files>`
- `.claude/agents/task-verifier.md:21` — agent 定義固定指令（直接文字，改此行）。附屬守則 `:23`（空即停）、`:24`（不使用 unstaged）須保留。
- `.claude/agents/code-reviewer.md:15` — agent 定義固定指令（直接文字，改此行）。附屬守則 `:17`、`:18` 同須保留。
- `skills/eval-flow/SKILL.md:80` — step 2 `git add` 描述（提及 reviewer/verifier 透過 `git diff --cached` 讀取）；派工描述改動點。
- `skills/eval-flow/SKILL.md:110` — 「Subagent 呼叫原則」明文「必須在 prompt 中指示使用 `git diff --cached`」；file-scoped 後此句須同步為 `git diff --cached -- <files>`，否則與 agent 定義矛盾。
- **非本 run 改動、但同介面的既有引用（改動須不破壞它們）**：`skills/eval-flow/SKILL.md:233`（resume 還原）、`skills/eval-flow-resume/SKILL.md:35`、`skills/test-strategy/SKILL.md:84,87,103`、`skills/task-decomposition/SKILL.md:25`、`tests/test_eval_gates.py:214`（測 GIT_COMMIT_RE 不誤判 `git diff --cached`）——這些是 `git diff --cached` 的其他用途，本 run **不改**，但改 agent 定義時勿波及。

  **查詢方法**：`grep -rn "git diff --cached\|diff --cached" --include=*.md --include=*.py .`（排除報告資料夾）→ 上列全部命中，共 12 處；本 run 目標僅 task-verifier.md:21、code-reviewer.md:15、eval-flow/SKILL.md:80,110 四處，其餘為須避讓的既有用途。

### 介面 C：`[P]` 標註／共用樹語義（skill prose）
- `skills/eval-flow/SKILL.md:69,77,82`（共用樹段、測試 barrier、mine 不適用、「各開 worktree」逃生門）— 改寫為 fan-out 語義的主戰場。
- `skills/task-decomposition/SKILL.md`（Step 4 `[P]` 條件、行數估計欄）— 補門檻註記。
- `skills/parallel-run/SKILL.md` — 標明 Tier 2 fan-out 重用點。
- `.claude/agents/task-decomposer.md` — 含 `[P]` 描述（Grep 命中，見查詢方法）；須確認其 `[P]` 標註規則與改後 task-decomposition skill 一致，不留舊語義。
- `skills/test-strategy/SKILL.md` — 含 `[P]` 相關描述（Grep 命中）；writer 層 mine 模式與 `[P]` 平行的互動，改寫共用樹段時須確認引用一致。

  **查詢方法**：`grep -rln "\[P\]" skills/ .claude/agents/` → 命中 `skills/test-strategy/SKILL.md`、`skills/eval-flow/SKILL.md`、`skills/task-decomposition/SKILL.md`、`.claude/agents/task-decomposer.md`（共 4 檔）。逐檔確認 `[P]` 語義一致性。

### 介面 D：子 manifest 命名 `run/<run_id>-item-<id>.json` 對兩個 `MANIFEST_RE` 的匹配
自行重跑 regex 匹配驗證（非取樣，直接對 pattern 求值）：
- `eval_gates.py` `MANIFEST_RE`（`:22-24`）：`run/2026-07-25-tier2-p-worktree-item-1.json` → 匹配，run_id=`2026-07-25-tier2-p-worktree-item-1`（**視為合法獨立 manifest，不被 `.eval`／`.test_baseline` 負向後查排除**）。
- `stats.py` `MANIFEST_RE`（`:30`，無 `run/` 前綴、對 basename 匹配）：`2026-07-25-tier2-p-worktree-item-1.json` → 匹配，run_id 同上。
- **影響**：子 manifest 被 `check_other_runs`（`:157-174`）掃到 → **這正是 D4 依賴的行為**（各 worktree 獨立 `run/`，主 worktree 掃不到未合回的子 manifest，故不誤擋；同 worktree 內子 manifest in_progress 會擋——符合設計）。子 manifest 被 `stats.collect` 掃到 → 計為獨立 run（family 反查靠 parent_run_id，統計層一族 run 顯示為 N+1 筆，須確認是否為預期，見第 5 節風險）。
- **`check_manifest` commit gate**（`eval_gates.py:104-132`）：子 manifest commit 時 `run_id = MANIFEST_RE.match(...).group("run_id")` = `<run_id>-item-<id>`，要求 `run/<run_id>-item-<id>.eval.json` 已 staged——子 run 各自歸檔即滿足（D4「各自歸檔」），無須改 gate。

  **查詢方法**：`python3` 對兩個 `MANIFEST_RE` pattern 逐一求值（`run/<run_id>-item-<id>.json`、`.eval.json`、`-blocked.md`），確認匹配／排除行為如上。命中：eval_gates.py、stats.py 各一個 MANIFEST_RE 定義。

### 介面 E：`eval_state.py` 子指令（子 run 沿用，無簽章改動）
- `list-files`（cmd_list_files，eval_state.py 166–173）被 file-scoped diff 消費（介面 B 的 `<files>` 來源），呼叫端在 `skills/eval-flow/SKILL.md:200`（操作規則）＋新增的 file-scoped 派工描述。子 run init／archive 沿用 `cmd_init`／`cmd_archive`，無新子指令、無簽章改動。

  **查詢方法**：scout 證據 `:148-153` 已列 eval_state.py 引用處；本 run 不改 eval_state.py 介面，故無新呼叫端。

## 5. 跨模組風險點

- **三 skill＋兩 agent prose 一致性殘留**：`[P]` 共用樹語義散在 `eval-flow/SKILL.md:69,77,82`、`task-decomposition`、`test-strategy`、`task-decomposer.md` 四處（介面 C）；改寫時任一處殘留舊語義＝接手者拿到自相矛盾的兩套 `[P]` 併發規則 — 建議：拆分時把「grep 驗證無殘留關鍵句」列為明確 item DoD（比照風險報告 §6 對策），grep 對象含「共用同一棵樹」「共用樹」等關鍵句。
- **`git diff --cached` 改動波及非目標引用**：介面 B 有 12 處引用，本 run 只改 4 處，其餘 8 處（resume／test-strategy／task-decomposition:25／test）是既有用途 — 建議：改 agent 定義與 eval-flow:80,110 時精準定位，確認 `:110` 的「Subagent 呼叫原則」與 agent 定義改後表述一致（否則 skill 說全域、agent 說 file-scoped，矛盾）。
- **file-scoped 破壞「空即停」守則**：`-- <files>` 命中為空（該 sub_task files 尚未 add）時，若 agent 改成 fallback 全域 diff，會回退到累積污染 — 建議：agent 定義保留「空即停止並回報」守則（task-verifier:23／code-reviewer:17），file-scoped 只是縮小範圍、不改「空即停」語義；此為 DoD 2 的正確性核心，列 item DoD 驗證。
- **子 manifest 進 stats 統計膨脹**：介面 D 確認子 manifest 被 `stats.collect` 計為獨立 run，一族 run 在統計層顯示為 prep run＋N 個 item run（N+1 筆）— 建議：確認此為可接受行為（family 語義靠 parent_run_id，stats 未必需感知）；若不可接受則須改 stats（Spec 未列此改動，屬新發現面，建議前置階段向使用者確認是否納入範圍或明確排除）。
- **hook 零改動假設須實測佐證（非推論即信）**：D4／HITL 裁示④「hook 零改動、worktree 天然隔離」的機械根據是 `check_other_runs:157` 只 `glob.glob("run/*.json")` 掃當前工作區 — 風險在「各 worktree 的 `run/` 是否真獨立、子 manifest 是否不洩漏到主 worktree」（usage 正確性假設 4「待確認」）— 建議：拆分時把「fan-out 期間主 worktree `git status`／`ls run/` 不含子 manifest」寫成可執行的 item DoD 實測驗證，不靠 prose 斷言。
- **parent_run_id 相容無測試即無效**：介面 A 確認加欄不影響現有讀取端，但 DoD 4 要求「hook 相容改動帶測試」— 建議：即使 hook 零改動，也在 `tests/test_eval_gates.py` 補一條「manifest 含 parent_run_id 時 `manifest_phase`／`check_other_runs`／`check_manifest` 行為不變」的迴歸測試（比照 `ManifestPhaseTest:113-129` 向後相容體例），把「相容」從斷言變成綠燈。
- **自我修改風險（本 run 改自己跑的 skill）**：eval-flow skill 改完即生效，本 run 後半段踩到改過的規則 — 建議：依 usage 情境 J／風險報告 §5 對策，本 run 自身序列跑、不 fan-out 自己，部署外層前先收外層 in_progress run、清孤兒 agent（此為操作約束，非可拆 item，列 run 級注意事項）。
