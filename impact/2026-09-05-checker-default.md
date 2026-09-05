# 影響面盤點 — 2026-09-05-checker-default（審查層 checker 化＋治理 v2＋上游補償三規則）

> 本報告自足：不依賴對話上下文。所有出處以 `檔案:行號` 指向。變更對象是流程文件與 agent 定義本身（非業務 code），故「呼叫端」＝文件互引點與消費規則的文字位置、「測試斷言」＝ tests/ 對文件靜態一致性的斷言。
> Spec：`spec/2026-09-05-checker-default.md`；usage：`usage/2026-09-05-checker-default.md`；risk：`risk/2026-09-05-checker-default.md`。變更塊 A（上游補償三規則）／B（checker-by-default）／C（治理 v2）。

---

## 1. 觸及模組清單

- `skills/eval-flow/SKILL.md` — B1–B4／B7 改寫循環 step 3 為 checker 預設、升級路徑、留痕、快速路徑限升級輪；全檔 reviewer 引用網最密（回歸面第一）。
- `skills/eval-flow-resume/SKILL.md` — B8：Step 3 處置表依 `checked_by` 決定重派 checker／reviewer（現寫死重跑 code-reviewer）。
- `.claude/agents/task-verifier.md` — B5：從「已退役、手動觸發」全檔改寫為「checker——審查層預設位」。
- `.claude/agents/code-writer.md` — A2：測試管轄規則插入 sabotage 鑑別力自檢條。
- `.claude/agents/code-reviewer.md` — B6：description 定位文字從「循環預設」改「升級路徑專用＋高風險手動觸發」（model 不動）。
- `skills/task-decomposition/SKILL.md` — A1（組合 row 規則，行為契約表節）＋A3（多處投放語義檢查，拆分期檢核）。
- `MODEL_POLICY.md` — B6：task-verifier／code-reviewer 兩列的「指派理由」欄文字更新（model 欄不動）。
- `TODO.md` — C：§15 治理規則整段改寫（凍結廢止→出生證制＋Minimality＋修剪啟動）。
- `retro/BUGLOG.md` — B7：檔頭格式增列選填尾註 `[checker-passed]` 的說明（供 grep 回退偵測）。
- `retro/RETRO.md` — M（出生證制）：兩層制升級來源從 bug 擴及所有規則來源；不改既有條目格式（僅可能被 A1/A3 出生證引用 R-006/R-007）。
- `tests/test_docs_consistency.py`、`tests/test_model_policy.py` — 被動回歸面：文件改寫須維持既有靜態一致性斷言綠（見第 4 節）。

---

## 2. 各模組既有慣例

### 落檔／留痕命名（B3／B8／E 情境的載體，最高重用面）
- 審查落檔命名：`run/<run_id>.review-st<id>-r<N>.md`（st＝sub_task id、r＝該 sub_task 審查輪次逐輪遞增）——`skills/eval-flow/SKILL.md:78`。B3 的 `checked_by` 尾註、B8 的 resume 重派、Tier 1 沿用（裁示 #4）皆掛在此命名上，**不新增欄位**。
- 落檔是熱 scratchpad，step 6 收尾隨 eval_state 一併清除、不進 git——`skills/eval-flow/SKILL.md:78,97`。
- eval 歸檔檔 `run/<run_id>.eval.json`（永久保留審查記錄，rounds 照舊）——`skills/eval-flow/SKILL.md:97`；B3 明言「不新增 eval_state.py 欄位」。

### 命名與狀態機慣例
- `step` 詞彙：`writing→reviewing→fixing→testing→done`；`verifying`／`scoring` 為舊版相容值——`skills/eval-flow/SKILL.md:229`、`eval-flow-resume/SKILL.md:45-47`。B5/B8 不新增 step 值（Spec 未列）。
- `phase` 詞彙：`init→risk_done→usage_confirmed→decomposed→completed`——`skills/eval-flow/SKILL.md:161`。B 塊不新增 phase（Spec §4）。
- 升級代碼字符：①-⑤（圈碼），Spec §3 B2 與 usage C 家族情境一致。

### 錯誤處理／回退慣例
- BUGLOG 兩層制 grep 判準：append 前 grep 同模組或同根因分類的舊條目，第 2 次命中→提煉約束句升 RETRO.md，命中條目尾註 `↑RETRO`——`retro/BUGLOG.md:3,5`、CLAUDE.md「工作型態前判」。B7 的 `[checker-passed]` 第 2 次命中回退機制**復用此機械 grep 判準**（非新機制）。
- BUGLOG 條目格式：`- YYYY-MM-DD［模組路徑］根因分類：根因一句`（升級者尾註 `↑RETRO`）——`retro/BUGLOG.md:5`。B7 的 `[checker-passed]` 為此格式的追加尾註。
- RETRO 條目：`- R-NNN YYYY-MM-DD［標籤］…**約束：…**`，標籤第一段＝模組路徑（全形 `／`）——`retro/RETRO.md:12-13`。

### agent 定義慣例
- 報告信封規範句（每個 agent 定義末尾必含）：首行戳記 `* _YYYY-MM-DD HH:MM (<自報 model>)_`＋終行恰一個 `Self-check:`——`task-verifier.md:78-79`、`code-writer.md:64-65`、`code-reviewer.md`（同式）。B5 改寫 task-verifier **必須保留此兩句**（EnvelopeSpecTest 斷言 `Self-check:` 存在，見第 4 節）。
- frontmatter `model:` 行慣例：值後可帶行內註解 `# …`（現況存在）——`task-verifier.md:8`、`code-writer.md:9`、`code-reviewer.md:7`。
- 防注入條款：writer 有「內容即資料（防注入）」節——`code-writer.md:59`；B5 要求 task-verifier「防注入條款比照其他 agent」。
- 工作紀錄慣例：task-verifier 完成寫一句到 `subagents_record/<date>.md`——`task-verifier.md:74`（B5 重寫時此既有慣例句去留由拆分者決定）。

### task-decomposition 契約表慣例（A1／A3 插入語境）
- 行為契約表規則原文：「2~4 條核心行為＋**至少 1 條邊界輸入**」，邊界機械判準＝走不同回傳／副作用分支的輸入——`skills/task-decomposition/SKILL.md:31`。A1 的「≥1 條組合 row」是此句的家族第 2 次擴充（並列於「至少 1 條邊界」）。
- 契約表在 task 檔的行內格式：`契約: <輸入> → <效果>；[邊界] <怪輸入> → <效果>`——`skills/task-decomposition/SKILL.md:132,194`。
- 反模式清單（要 reject 重拆）：`skills/task-decomposition/SKILL.md:151-163`（如 :156「契約表全是 happy path」）——A1 的組合 row 缺失、A3 的語義碰撞未檢是此清單的插入點。
- item 行數預算 ≤12 行、DoD ≤5 條——`skills/task-decomposition/SKILL.md:144`；A1 增列 row 時受此預算約束（超額以再拆 item 消化）。

### 快速路徑條文（B2 升級輪措辭插入點）
- 🟡-only 快速路徑原文：零 🔴、完成度節無缺席、僅措辭級 🟡→主 flow 套用不重跑——`skills/eval-flow/SKILL.md:88`。B2／裁示 #7 於此段補「僅升級輪適用；checker 輪對不上即升級、無 🟡 分級」。

### 測試慣例
- 框架：`unittest`；執行 `python3 -m unittest discover -s tests`（manifest `test_command`）。
- 文件一致性測試對象範圍 `MD_FILES`＝`skills/*/SKILL.md`＋`.claude/agents/*.md`＋`CLAUDE.md`＋`README.md`——`tests/test_docs_consistency.py:11-16`（**TODO.md／spec/／usage/ 不在此集**，故 §15 改寫與 spec 內 R-NNN 引用不被 RetroIdReferencesTest 檢查）。
- MODEL_POLICY 解析只讀 `| agent | model |` 兩欄，**不讀理由欄**——`tests/test_model_policy.py:15,20-25`（B6 改理由欄文字零觸發斷言，見第 4 節）。

---

## 3. 可重用既有元件（防重複造輪；新條文應指向重用而非重列，R-007）

- `skills/eval-flow/SKILL.md:78` 審查落檔命名 `review-st<id>-r<N>.md` — B3 `checked_by` 尾註、B8 resume 重派、G 情境 Tier 1 留痕（裁示 #4）皆掛此命名，新條文指向、不另立載體。
- `retro/BUGLOG.md:3,5` + CLAUDE.md「工作型態前判」BUGLOG 兩層制 grep 判準（同根因分類第 2 次命中升級） — B7 回退偵測直接復用「grep＋第 2 次命中」機械判準，只把 grep 目標從「同根因分類」擴為「同根因分類＋`[checker-passed]` 尾註」。
- `skills/eval-flow/SKILL.md:88` 🟡-only 快速路徑條文 — B2 升級輪快速路徑不重寫、僅在原段補「僅升級輪適用」一句。
- `.claude/agents/task-verifier.md:78-79`（及 code-writer:64-65、code-reviewer 同式）報告信封規範句 — B5 重寫 task-verifier 保留原句、不重擬。
- `skills/task-decomposition/SKILL.md:31` 「至少 1 條邊界輸入」契約表句 — A1 組合 row 並列於此句、共用「契約表覆蓋不足」家族敘事，不另開新表節。
- `skills/eval-flow/SKILL.md:74` 既有 writer 交付稽核（mine 指紋、仲裁引文核對）— B2③ 升級（mine 指紋異常）是此稽核的 checker 側複核補網（裁示 #5），指向既有稽核、不重述判準。
- `skills/eval-flow/SKILL.md:79-84` 引文核實／重裁條款、`:89` scope 防線 — 升級輪 reviewer 流「原樣不變」（Spec B2、usage C/D），新條文指向既有 step 3/4 條文。
- `retro/RETRO.md:12`（R-006 跨文件語義相容）— A3 是 R-006 的投放期應用；`:13`（R-007 單一枚舉點）— 是本 run 全條文「指向而非重列」的執法依據。
- `.claude/agents/code-writer.md:46` 既有「行為契約表是測試預算」＋整合測試 item 的 mutation self-check — A2 sabotage 自檢是既有 mutation self-check 的最小版擴用（Spec A2），指向既有規則、不新造測試教義。

---

## 4. 被改介面的呼叫端清單

> 「被改介面」＝本 run 預計修改的文字規則／定位句；「呼叫端」＝ codebase 中引用該規則的其他文字位置與 tests 斷言。以下 grep 皆從 repo 根全掃。

### 介面 4-1：循環 step 3「預設派 code-reviewer」及全檔 reviewer 引用網（B1，最高優先，risk 技術風險第 2 條點名）
`skills/eval-flow/SKILL.md` 內 `code-reviewer|reviewer|審查|task-verifier` 全部命中點（逐點附改／不改初判，供拆分者切 B1 item DoD）：
- `:75` — step 2「派 code-reviewer 時 prompt 硬性指示 `git diff --cached -- <files>`」。**改**：checker 不讀 diff，step 2 派審對象與 diff 指示需區分 checker（只給 `--stat`）vs 升級 reviewer（full file-scoped diff）。
- `:76` — step 3「呼叫 code-reviewer（唯讀、讀 staged diff）強制兩節」。**改（核心）**：改為預設派 task-verifier（checker），輸入集＝item＋writer 報告＋`--stat`＋測試尾段＋mine 摘要；產完成度節＋憑據節。
- `:77` — task-verifier 退役告示＋回退條件。**改**：退役敘述作廢，改為 checker 預設位敘述。
- `:78` — 審查報告 write-ahead 落檔 `review-st<id>-r<N>.md`。**改（增補）**：增列 `checked_by:` 尾註；命名本身不改（裁示 #3 同輪同 r 號）。
- `:79` — 🔴 重裁條款（reviewer）。**不改本體**：屬升級輪 reviewer 流；可加註「升級輪適用」。
- `:80` — 引文核實（reviewer，生產端 code-reviewer.md）。**不改本體**：升級輪適用。
- `:81` — grep 無輸出駁回。**不改**：升級輪 reviewer 流內。
- `:83` — 機械退件門檻「退回 reviewer 重審」。**不改**：升級輪內。
- `:85` — step 4「審查結果的處置」。**改**：需區分 checker 通過（→set-verify）／checker 升級（→派 reviewer）／reviewer 輪處置；checker 輪無 🟡 分級。
- `:87` — 有 🔴／缺席→fixing。**不改本體**：升級輪 reviewer 結果驅動。
- `:88` — 🟡-only 快速路徑。**改（加限定詞）**：補「僅升級輪適用，checker 輪對不上即升級」（裁示 #7）。
- `:89` — scope 防線。**不改**：兩輪皆適用（升級輪主體）。
- `:90` — 修正迭代上限「reviewer 仍有 🔴」。**改（加註）**：checker 輪與升級本身不計入上限（裁示 #9）。
- `:97` — step 6 收尾清除 `review-st*-r*.md`。**不改**：落檔清除照舊（含 checker 輪落檔）。
- `:99-100` — step 7 retro 條件（code-reviewer 有/無 🔴）。**待判（初判不改）**：checker 通過輪無 🔴 概念，需確認 retro 觸發是否僅掛升級輪（Spec 未明列，拆分者標為 B1 邊角待確認）。
- `:105` — Model 指派原則「審查→強 model」。**不改**：checker 是機械核對降 haiku，此原則敘述可留（B6 於 MODEL_POLICY 更理由欄）。
- `:110` — Subagent 呼叫原則「code-reviewer（含手動觸發的 task-verifier）需 `git diff --cached`」。**改**：task-verifier 不再是「手動觸發」且不讀 diff，本句的 diff 指示對 checker 不適用，需區分。
- `:161` — phase 轉移「前置 3 審查通過」。**不改**：指前置 3 拆分審，非循環 step 3。
- `:229` — write-ahead step 詞彙（reviewing/fixing）。**不改**：step 詞彙不變（B5/B8 不增 step）。
- `:230` — set-review「首輪 code-reviewer 的 🔴 原始數」。**改（加註）**：checker 輪零 🔴 照填、升級輪由 reviewer 結果填（Spec B4/B2）。
- `:231` — set-verify「reviewer 完成度節通過」語義。**改（加註）**：checker 通過亦 set-verify（完成度節照舊格式，Spec B1/B4）。
- `:234` — 修正 2 輪 reviewer 仍有 🔴。**同 :90 加註**。
- `:246`（Gate 節）— 測試 gate `verify_passed` 語義「reviewer 完成度節通過」。**不改**：Spec §4 禁動 gate 條文；此為已知語義略陳舊、留為已知不一致（Spec §4、usage 互動點）。
- `:267` — Tier 1「reviewer 一次讀完可審」。**不改／輕調**：prose 合併審仍成立；checker 化對 Tier 1 循環的影響走 G 情境（step 3 預設派 checker），拆分者確認 Tier 1 節是否需一句指向。
- `:268` — Tier 1 小 prose item 合併「reviewer 一次讀完」。**不改本體**。
- `:270` — Tier 1 主 flow 直寫捷徑「code-reviewer 照常獨立審 staged diff」。**改（加註）**：新制下 step 3 預設派 checker，直寫捷徑的「審的人」預設為 checker、升級同 C 家族（G 情境）。
- `:313` — fan-out 退回循序「派 code-reviewer 改用 file-scoped diff」。**改（加註）**：退回循序時 step 3 預設派 checker，升級走 file-scoped diff reviewer（I 情境，各 worktree 獨立生效）。
- **查詢方法**：`grep -n -E 'code-reviewer|reviewer|審查|task-verifier|checker' skills/eval-flow/SKILL.md` → 命中 27 行（上列全數；已排除純 phase/step 詞彙誤命中並標「不改」）。另 `grep -n 'checker' skills/eval-flow/SKILL.md` → 0 hits（新概念尚未進檔，確認為淨新增）。

### 介面 4-2：eval-flow-resume Step 3 處置表（B8）
- `skills/eval-flow-resume/SKILL.md:43` — `reviewing` 列「重跑循環步驟 3（呼叫 code-reviewer）」。**改**：依落檔 `checked_by` 重派（checker→task-verifier；escalated→code-reviewer；無落檔→預設 checker）。
- `:44` — `fixing` 列「讀落檔續修」。**改（加註）**：`<N>` 取最大值語義不變（裁示 #3）、重派對象依 checked_by。
- `:45` — `verifying` 列「task-verifier 已退役…重跑 reviewer 兩節報告」。**改**：task-verifier 復活為 checker，退役敘述作廢。
- `:25`（Step 2 表）— `usage_confirmed` 行 impact_report 恢復動作。**不改**：與 checker 化無關。
- **查詢方法**：`grep -n -E 'code-reviewer|reviewer|task-verifier|checked_by|審查' skills/eval-flow-resume/SKILL.md` → 命中 :43,:44,:45（處置表三列，均需改）；`grep -n 'checked_by' skills/eval-flow-resume/SKILL.md` → 0 hits（消費點待新增，確認 B8 為淨新增消費者）。

### 介面 4-3：task-verifier「已退役」定位（B5）
- `.claude/agents/task-verifier.md:4`（frontmatter description「在 code-reviewer 通過後、commit 前呼叫，也可隨時手動觸發」）、`:11`（退役告示 block）、`:13`（職責敘述）、`:8`（model 註解「假通過率為回退依據」）。**全檔改寫**：改為 checker 預設位定義。
- 外部對 task-verifier 的引用點：`skills/eval-flow/SKILL.md:77,110`、`skills/eval-flow-resume/SKILL.md:45`、`MODEL_POLICY.md:13`（理由欄）。**全部需同步**（見 4-1、4-2、4-5）。
- **查詢方法**：`grep -rn 'task-verifier' --include='*.md' .` → 命中 `.claude/agents/task-verifier.md`（多處）、`skills/eval-flow/SKILL.md:77,110`、`skills/eval-flow-resume/SKILL.md:45`、`MODEL_POLICY.md:13`、`tests/test_model_policy.py`（stem 掃描，見 4-6）；spec/usage/risk 本 run 檔命中不計入。

### 介面 4-4：code-writer 測試管轄規則（A2 插入）
- `.claude/agents/code-writer.md:33-47`（測試管轄規則節，規則 1–7）為插入語境；A2 為新增一條 sabotage 自檢（交付含新增測試檔的 item 前）。**新增**：不改既有 7 條，並列新條並指向既有 mutation self-check（Spec A2）。
- 下游消費者：checker 核對項④「sabotage 自檢證據存在」——`spec §3 B1/B2④`、usage B/C-esc4 情境。
- **查詢方法**：`grep -n -E 'sabotage|self-check|mutation|測試管轄|__pycache__' .claude/agents/code-writer.md` → `:33`（節標題）、無既有 sabotage 字樣（確認 A2 為淨新增，不與既有條文碰撞）。

### 介面 4-5：code-reviewer 定位＋MODEL_POLICY 理由欄（B6）
- `.claude/agents/code-reviewer.md:2-6`（description）— 定位文字「循環預設」→「升級路徑專用＋高風險手動觸發」。**改**：僅 description 文字；model 行 `:7` 不動。
- `MODEL_POLICY.md:8`（code-reviewer 理由）、`:13`（task-verifier 理由）— 理由欄文字更新。**改**：僅第三欄文字；agent／model 欄不動。
- `MODEL_POLICY.md:18`（去相關化約束）、eval-flow `:104-105`（Model 指派原則）— **不改**：異族約束與強/快 model 原則不變。
- **查詢方法**：`grep -n 'code-reviewer' MODEL_POLICY.md` → `:8,:18`；`grep -n 'task-verifier' MODEL_POLICY.md` → `:13`。

### 介面 4-6：tests/ 對文件的靜態一致性斷言（被動回歸面，全部須維持綠）
- `tests/test_docs_consistency.py:118-125` EnvelopeSpecTest — 斷言每個 `.claude/agents/*.md` 含 `Self-check:`。**風險**：B5 重寫 task-verifier 若刪掉信封規範句→紅。**DoD 綁**：`python3 -m unittest tests.test_docs_consistency.EnvelopeSpecTest` 綠。
- `tests/test_docs_consistency.py:78-94` GateListConsistencyTest — 斷言 gate 區間宣稱＝清單最大編號。**評估：零觸發**——正則 `（gate (\d+)–(\d+)）` 需第二段為帶 `–` 的範圍；eval-flow `:241` 現為「（gate 1–6）…（gate 7）」，`（gate 7）`無 `–` 故 `re.search` 不匹配→`continue` 跳過；且 step 3 改寫落在循環節（:55-100），gate 清單在 :239-255 另一節，Spec §4 禁動 gate。**初判不觸及**，拆分者只需確認 step 3 改寫不誤入 gate 清單節。
- `tests/test_docs_consistency.py:97-115` RetroIdReferencesTest — MD_FILES 內 `(R-NNN)` 引用須存在於 RETRO.md。**風險**：A3 出生證引 R-006、C/M 若在 SKILL/agent 內引 R-007，兩者均已存在（`retro/RETRO.md:12,13`），**綠**；但若新條文寫入 SKILL/agent 引用不存在的 R-NNN→紅。TODO.md／spec 不在 MD_FILES 故不受檢。
- `tests/test_model_policy.py:41-70` ModelPolicyConsistencyTest — 斷言表↔frontmatter model 一致、writer/reviewer 異族、frontmatter 解析忽略行內註解。**評估：零觸發於理由欄改動**——`POLICY_ROW_RE`（`:15`）只捕捉 agent 與 model 兩欄，理由欄文字不入斷言；B6 不改 model 欄故 `test_frontmatter_matches_policy` 綠、`test_writer_reviewer_families_differ` 綠。**唯一風險**：B5 若誤改 task-verifier frontmatter 的 `model:` 值（Spec §4 明禁）才會紅。
- **查詢方法**：`grep -rn -E 'reviewer|verifier|checker|step 3|escalat' tests/` → 命中 `test_docs_consistency.py`（class 名如上）、`test_model_policy.py`（`:59-65` 異族）；無任何測試斷言循環 step 3 的 prose 內容或升級代碼①-⑤（確認 §5 作廢清單「無既有自動化測試斷言舊流程句」成立）。

### 介面 4-7：BUGLOG 檔頭格式（B7）
- `retro/BUGLOG.md:1-5`（檔頭說明＋格式行）為 B7 `[checker-passed]` 尾註說明的插入點。**改（增補說明）**：不改既有條目（:8 起），僅檔頭增列尾註語義。
- 消費者：主 flow 回退偵測 grep（F 情境）、CLAUDE.md「bugfix retro 兩層制」。
- **查詢方法**：`grep -rn 'checker-passed' .` → 0 hits（確認 B7 尾註為淨新增，無既有消費點需同步）。

### 介面 4-8：TODO §15 治理規則（C）
- `TODO.md:120-127`（§15 全節）為 C 塊改寫範圍。**改（整段）**：凍結條款（:122）廢止→出生證制＋Minimality＋修剪啟動；保留 game day（:124）、收斂判準（:127）、選題多樣化（:126）。
- 相關但不同節：`TODO.md:123`（eval-scorer 存廢審計）、`:125`（修剪審查）與修剪啟動語義相鄰——拆分者確認 C 塊「修剪啟動」是否指向既有 :125 而非重列。
- **查詢方法**：`grep -n -E '凍結|game day|收斂判準|選題多樣|修剪' TODO.md` → `:122,:124,:125,:126,:127`（§15 範圍）；TODO.md 不在 MD_FILES，無 R-NNN 一致性檢查。

---

## 5. 跨模組風險點

- **step 3 改寫漏改任一 reviewer 引用點 → 互相矛盾指令**（R-006 家族，risk 技術風險第 2 條）— 確認方式：B1 item 的 DoD 設「全檔 `code-reviewer|reviewer` 引用點盤點」條，逐點對照本報告 4-1 的 27 行清單；交付後 `grep -n -E 'code-reviewer|reviewer' skills/eval-flow/SKILL.md` 復查每點是否已標 checker 化或明示「升級輪不改」。
- **checked_by 留痕格式↔resume 消費↔R8 稽核 grep 三方需一致**（usage 假設 2）— checked_by 字面格式（`checker` / `reviewer(escalated: ①-⑤)`）在 B3（生產）、B8（resume 消費，:43-45）、R8 grep（統計）三處必須同字面。確認方式：拆分時把「格式字串」定為單一枚舉點（B3 定義處），B8 與稽核指向引用、不各自重寫（R-007）。
- **task-verifier 五處引用不同步 → 定位分裂**（4-3）— `.claude/agents/task-verifier.md`（本體）、eval-flow :77/:110、resume :45、MODEL_POLICY :13 若只改部分，會出現「一處說退役、一處說 checker 預設」。確認方式：B5 item 的 files 清單須含全部五個檔，DoD 綁 `grep -rn '退役\|已退役' skills .claude/agents` 應僅剩合理歷史敘述（或零）。
- **EnvelopeSpecTest 回歸**（4-6）— task-verifier 重寫刪信封句即紅。確認方式：B5 DoD 綁 EnvelopeSpecTest 綠。
- **A→B 非硬依賴但需同 run 原子落地**（usage 假設 3，裁示 #11）— A/B/C 為單 commit 原子落地，A 塊補償規則與 B 塊 checker 化必須同一 commit（次 run 才讀到完整補償）。風險：若拆成多 commit 部分落地，會出現「checker 已預設但 A 補償規則未進」的空窗。確認方式：本 run 收尾單 commit（eval-flow step 6），拆分不設 A→B 硬 depends、但全部 item 在同一 run 內收尾。
- **本 run 自身用舊制（reviewer）審，新制自下一 run 生效**（usage 互動點、risk 業務風險第 1 條）— 避免「用未審查的新制審新制」自舉。確認方式：生效時點寫進 B1 item 的 DoD；本 run 循環 step 3 仍派 code-reviewer。
- **A1 組合 row 與既有「至少 1 條邊界」預算衝突**（4-4／契約表 :31,:144）— 組合 row 可能使契約 row 數超 item ≤5 行預算。確認方式：A1 條文須明言「超額以再拆 item 消化、不砍邊界覆蓋」（沿 :144 既有規則）。
- **升級③與既有 writer 交付稽核職責重疊**（usage 假設 4／開放問題 5，已裁示 #5）— checker 側複核 vs step 1 稽核退件的分工。確認方式：B2③ 條文明寫「主 flow 交付稽核在前、升級③為 checker 側複核補網」，指向 eval-flow :74 既有稽核、不重述判準。
- **retro 觸發（step 7）在 checker 通過輪的語義未定**（4-1 :99-100）— checker 通過輪無「reviewer 有無 🔴」概念。確認方式：拆分者標為 B1 邊角待確認，Spec 未明列時 park 進收尾請使用者裁決（不自行擴 scope，eval-flow :89）。

Self-check: 五節齊備，第 4 節七個被改介面各附 grep pattern 與命中數、step 3 全檔 27 個 reviewer 引用點逐行標改/不改、兩測試檔的觸發性經正則核實（EnvelopeSpecTest 唯一真回歸面、理由欄與 gate 區間零觸發），報告自足可供 task-decomposer 直接切 item。
