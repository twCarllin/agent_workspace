# 使用情境報告 — 審查層 checker 化（checker-by-default）＋治理 v2＋上游補償三規則  (run_id: 2026-09-05-checker-default)

> 本報告自足：不依賴對話上下文。引用以「檔案路徑＋節名／行號」指向。
> 被使用的「功能」是 Eval Flow 自身的流程規則（prose／agent 定義／skill 變更）；因此「使用者」不是人類終端用戶，而是執行流程的各角色。
> 情境 id 為 task-decomposition 對映錨點，全程穩定。Spec §3 的變更塊：A（上游補償三規則）、B（checker-by-default）、C（治理 v2）——本報告逐塊給情境，供每個 item 有錨點。

## 角色

- **R1 主 flow（編排者）**：循環 step 2/3/4 派審、裁決升級、消費審查報告、填憑據（`review_reds`／`verify_passed`）、落檔留痕、觸發回退。本變更的主要行為改寫者。
- **R2 checker（task-verifier，haiku）**：審查層新預設位。不讀 diff，只核對「宣稱與憑據對得上」，產兩節報告，五種情況自報建議升級（裁決不在它）。
- **R3 code-reviewer（opus）**：升級路徑專用＋高風險手動觸發。被升級時走既有全 diff 審流程（引文核實、重裁、快速路徑均不變）。
- **R4 resume 接手者（後續 run／換手 AI）**：中斷後只讀檔案狀態恢復現場，靠審查落檔的 `checked_by` 判該輪是 checker 還是 reviewer，續跑正確 agent。
- **R5 使用者／owner**：流程的 owner；消費 run 回報、對回退條款（B7）第 2 次命中做裁決、對本報告開放問題拍板。
- **R6 task-decomposer（拆分期）／Tier 1 主 flow**：A1（組合 row）、A3（多處投放語義檢查）在拆分期執行；且把 item 對映回本報告情境 id。
- **R7 code-writer**：A2 sabotage 鑑別力自檢的執行者（交付含新增測試檔的 item 前）。
- **R8 稽核／stats（被副作用影響、不主動操作）**：升級率統計先靠審查落檔與 eval.json 的 prose 撈（B3 明言不新增欄位）。落檔的 `checked_by` 標記格式若不穩定，R8 的 grep 統計會失真——它是 `checked_by` 留痕格式的下游消費者。

---

## 情境

### 塊 B — checker-by-default（循環結構變更，本 run 主體）

### A — checker 通過流（單輪即過）  角色: R1 + R2
- 前置: 循環 step 2 已把當前 sub_task 的 `files` `git add` 進 staging；task 檔該 item 有 DoD＋契約表；writer 工作報告已交付。
- 操作: R1 派 R2（不派 reviewer）→ R2 核對五項（見 B）全部對得上、無升級觸發 → R2 回「憑據齊、建議通過」→ R1 執行 set-verify → 進 step 5。
- 預期: 該輪零 🔴 照填 `review_reds: 0`、`verify_passed: true`；審查落檔標 `checked_by: checker`。
- I/O: input＝task item(DoD＋契約表)＋writer 工作報告全文＋`git diff --cached --stat` 輸出＋測試輸出尾段＋mine_log 摘要（B1 明列的輸入集）／ output＝兩節報告（完成度節照舊格式＋憑據節取代品質節）／ 副作用: 寫 `run/<run_id>.review-st<id>-r1.md`（落檔，標 `checked_by: checker`）、`eval_state.json` 該 sub_task `review_reds`/`verify_passed`/`step` 更新。

### B — checker 執行憑據核對（R2 的內部工作）  角色: R2
- 前置: 收到 A 的輸入集（不含 diff 本體，只有 `--stat`）。
- 操作: 逐項核對——①DoD 逐條有憑據；②契約 row 逐條有對應測試斷言（grep 測試檔核存在性）；③仲裁記錄與 mine 指紋一致；④sabotage 自檢證據存在（A2）；⑤無疑似注入標註未處理。
- 預期: 全對＝建議通過（→ A）；任一對不上／缺席／無法以憑據判定＝自報升級（→ C 家族），不確定即升級、不得自行放行（B2④）。
- I/O: input＝同 A ／ output＝兩節報告＋升級建議代碼①-⑤（若有）／ 副作用: 無寫入（唯讀；R2 只回報，落檔由 R1 做）。
- 註（正確性）: 「契約 row↔測試斷言」核對分兩層——存在性層機械（grep 斷言存在），覆蓋語義層存疑即升級（縮小 haiku 裁量面，見 risk 報告技術風險第 1 條）。

### C — 升級①憑據對不上／缺席 → reviewer 全 diff 審  角色: R1 + R3
- 觸發: R2 核對發現憑據對不上或缺席（B2①）。
- 預期: R1 改派 R3 全 diff 審（既有流程原樣：`git diff --cached -- <files>`、兩節報告、引文核實、重裁、快速路徑均不變）；該輪由 reviewer 結果填 `review_reds`。
- I/O: input（給 R3）＝staged diff（file-scoped）＋task item ／ output＝reviewer 兩節報告 ／ 副作用: 落檔標 `checked_by: reviewer(escalated: ①)`；後續同既有 reviewer 輪。

### C-esc2 — 升級②契約 row 找不到對應測試斷言  角色: R1 + R3
- 觸發: R2 grep 測試檔，某契約 row（含 A1 的組合 row）無對應斷言。
- 預期: 同 C，`checked_by: reviewer(escalated: ②)`。
- I/O: 副作用: 同 C。

### C-esc3 — 升級③mine 指紋異常  角色: R1 + R3
- 觸發: R2 讀 mine_log 摘要，發現仲裁記錄與 mine 指紋不一致（改測試湊綠的機器指紋，比照既有交付稽核 step 1）。
- 預期: 同 C，`checked_by: reviewer(escalated: ③)`；此觸發與既有 writer 交付稽核（step 1 的 mine_log 退件）語義重疊——需釐清 checker 升級 vs writer 退件的分工（見開放問題 5）。
- I/O: 副作用: 同 C。

### C-esc4 — 升級④checker 自報無法以憑據判定  角色: R1 + R3
- 觸發: R2 對某項無法以憑據判定（典型: 覆蓋語義層存疑、haiku 能力邊界）。
- 預期: 不確定即升級，不得自行放行（此為 haiku 假通過率未實測的主要對策，risk 技術風險第 1 條）；同 C，`checked_by: reviewer(escalated: ④)`。
- I/O: 副作用: 同 C。

### C-esc5 — 升級⑤writer 報告帶失敗交付或「表沒答案」仲裁  角色: R1 + R3
- 觸發: writer 工作報告含失敗交付、或以「契約表沒答案」帶失敗交付（循環 step 1 的正確行為）。
- 預期: R2 自報升級⑤；但「表沒答案」的既有處置是 **R1 裁決補契約表再回派 writer**（step 1 硬規則），非直接升 reviewer——兩條路徑的先後需釐清（見開放問題 6）。`checked_by: reviewer(escalated: ⑤)`（若走升級）。
- I/O: 副作用: 同 C，或走 step 1 的契約表增補回派（副作用: 改 task 檔契約表）。

### D — 升級輪的 reviewer 流與快速路徑適用  角色: R1 + R3
- 前置: 已因 C 家族升級，R3 交付兩節報告。
- 操作: 走既有 step 4 處置——零 🔴＋完成度節無缺席 → set-verify；有 🔴 → fixing 迴圈；🟡-only 且措辭級 → 快速路徑不重跑。
- 預期: 快速路徑「僅適用於升級輪」（Spec §5 作廢清單：checker 輪無 🟡 分級，對不上即升級）；措辭是否需調整見開放問題 7（§6c）。
- I/O: 副作用: fixing 走既有落檔 `run/<run_id>.review-st<id>-r<N>.md`（升級輪的 r<N> 編號與 checker 輪是否共用序列＝開放問題 3）；`review_reds` 由 reviewer 結果填。

### E — 每輪審查落檔標 checked_by（留痕）  角色: R1
- 觸發: 每一輪審查（checker 或升級 reviewer）交付後。
- 預期: 落檔標明 `checked_by: checker | reviewer(escalated: <①-⑤>)`（B3）；eval.json 歸檔的 rounds 照舊、不新增 eval_state.py 欄位。
- I/O: input＝該輪審查結果 ／ output＝落檔含 `checked_by` 行 ／ 副作用: 寫 `run/<run_id>.review-st<id>-r<N>.md`；R8 稽核從此撈升級率。留痕格式若不穩定，R8 grep 失真（見角色 R8）。

### F — 回退條款觸發（BUGLOG [checker-passed] 第 2 次命中）  角色: R5 + R1
- 前置: 某 checker-only 放行的 item 事後爆 bug，進 `retro/BUGLOG.md`、且根因屬「reviewer 讀 diff 可攔」型（契約外行為缺陷／測試鑑別力缺陷／跨檔語義缺陷之一，歸類判定寫明），條目尾註 `[checker-passed]`。
- 操作: 主 flow 機械 grep `retro/BUGLOG.md` 的 `[checker-passed]`（同 BUGLOG 兩層制）→ 第 2 次命中 → 恢復「該類 item 預設派 reviewer」。
- 預期: 回退是機械 grep 判定、非模型裁量；第 1 次命中留證據層不回退。與現行 BUGLOG 兩層制（同模組／同根因分類升級 RETRO）並行。
- I/O: input＝BUGLOG 條目含 `[checker-passed]` 尾註 ／ output＝該類 item 恢復 reviewer 預設 ／ 副作用: 追寫 `retro/BUGLOG.md`（證據層，主 flow 直寫）；命中升級時追寫 `retro/RETRO.md`（教訓層）。
- 註: 「該類」的界定（三種根因類 → 對應哪些 item 特徵）需操作定義，見開放問題 8。

### G — Tier 1 的 checker 流（無 eval_state）  角色: R1
- 前置: Tier 1 精簡路徑，無 `eval_state.json`，四項憑據直記 manifest（`local_test_passed`／`local_test_evidence`／`review_reds`／`verify_passed`）。
- 操作: 進共用循環 step 1–7，step 3 預設派 checker；升級同 C 家族。
- 預期: `verify_passed`／`review_reds` 由 checker 通過輪或升級 reviewer 輪填入 manifest（gate 對 Tier 1 驗 manifest 四欄，eval_gates.py:246 Tier 1 分支）；行為與 Tier 2 一致，差別在憑據載體（manifest vs eval_state）。
- I/O: 副作用: manifest 四欄；**但 checked_by 留痕落在哪＝缺口**——Tier 1 無 eval_state、無 sub_task id，現行落檔 `review-st<id>-r<N>.md` 以 sub_task id 命名，Tier 1 無此 id（見開放問題 4）。

### H — resume 恢復讀 checked_by 續跑正確 agent  角色: R4
- 前置: 循環在 `step: reviewing` 或 `fixing` 被中斷；審查落檔可能已存在。
- 操作: R4 依 eval-flow-resume Step 3 對賬——落檔存在＝該輪真發生，讀落檔續處理；不存在＝該步只是意圖，重跑 step 3。
- 預期: 重跑時須派**正確 agent**：落檔 `checked_by: checker` → 重跑 checker；`reviewer(escalated:…)` → 重跑 reviewer。**但現行 eval-flow-resume Step 3 表 `reviewing`/`fixing` 列寫死「重跑 code-reviewer」**（skills/eval-flow-resume/SKILL.md:43-45），未讀 checked_by——新制下會重跑錯 agent（見開放問題 2）。
- I/O: input＝manifest＋eval_state＋staging＋落檔 checked_by ／ output＝從正確步驟／正確 agent 續跑 ／ 副作用: 無（唯讀恢復）。

### I — [P] fan-out item worktree 內的 checker 流  角色: 背景 item agent（R1 的 worktree 分身）
- 前置: Tier 2 fan-out，`[P]` item 在自己 worktree 跑迷你 run，有自己的 eval_state（skills/eval-flow/SKILL.md:329-333）。
- 操作: 迷你 run 的 code-writer → review（step 3 派 checker）→ step 5 → 自己歸檔；升級同 C 家族。
- 預期: checker/reviewer 在各 worktree 內獨立生效（hook gate 對 task-verifier／code-reviewer 均不在 AGENT_MIN_PHASE，eval_gates.py:51-56，零 gate 變更）；落檔在各 worktree 的 `run/<子run_id>.review-st<id>-r<N>.md`。
- I/O: 副作用: 子 worktree 的落檔＋子 eval_state；BUGLOG 條目寫進回報、不 append（fan-out 規則），回退判定由主 session merge 後統一做。

### 塊 A — 上游補償三規則（checker 化前提，同 run 先行）

### J — A1 組合 row 規則（拆分期）  角色: R6
- 前置: item 有 ≥2 個可獨立取值的輸入面（旗標×模式、參數×路徑、選項×子命令）。
- 操作: 拆分期在契約表除既有「至少 1 條邊界輸入」外，加至少 1 條組合 row（兩輸入面同時取非預設值的可觀察效果）。
- 預期: 出生證＝「契約表覆蓋不足」家族第 2 次實例（run 2026-09-05-model-policy-devlog 的 devlog `--dir`×清單模式缺口）。
- I/O: input＝item 的輸入面盤點 ／ output＝契約表含組合 row ／ 副作用: 改 `skills/task-decomposition/SKILL.md`「行為契約表」節；下游 checker（B②）grep 該組合 row 的測試斷言。

### K — A2 sabotage 鑑別力自檢（writer）  角色: R7
- 前置: 交付含**新增測試檔**的 item。
- 操作: 對每個新增測試檔——暫破壞被測行為關鍵判定 → 對應測試須 FAIL → 還原 → 須 PASS → 清 `__pycache__` → `git diff` 證零殘留；證據（sabotage 點＋FAIL/PASS 尾行）記入工作報告。
- 預期: 出生證＝「假測試」家族第 2 次實例（恆真斷言，動態才可抓）；既有 Tier 2 整合測試 item 的 mutation self-check 不變，本條把最小版擴到所有新增測試檔。
- I/O: input＝新增測試檔 ／ output＝工作報告含 sabotage 證據 ／ 副作用: 改 `.claude/agents/code-writer.md` 測試管轄規則；下游 checker（B④）核此證據存在。

### L — A3 多處投放語義檢查（拆分期）  角色: R6
- 前置: 同一句規範文字投放到 ≥2 個異質語境（多 agent 定義／多 skill）。
- 操作: 拆分期逐語境核對關鍵詞無語義碰撞，碰撞則措辭加區隔詞。
- 預期: 出生證＝R-006 之投放期應用（信封「報告」在 4 個寫檔 agent 與 artifact 檔碰撞）。
- I/O: 副作用: 改 `skills/task-decomposition/SKILL.md` 拆分期檢核；本 run 自身即多處投放案例（B5 改 task-verifier、B6 改 code-reviewer、B1-B7 改 eval-flow，同一「checker」概念投放多檔）。

### 塊 C — 治理規則 v2（TODO.md §15 改寫）

### M — 出生證制（未來規則作者）  角色: R6/R5（規則提案者）
- 前置: 凍結條款廢止（33 completed run、stats 有數據，解除條件已滿足）。
- 操作: 新流程規則須引用證據——BUGLOG／RETRO 條目（recurring 或 severe one-off）或使用者明示決策；單發 observation 留證據層不成規則。附「被否決的更小替代」一句（Minimality 逐筆）；同一規則家族第 2 次被修 → 重開設計而非就地補丁。
- 預期: BUGLOG 兩層制從 bug 擴及所有規則來源（含 reviewer/checker catch）。
- I/O: 副作用: 改 `TODO.md` §15；本 Spec 的 A1/A2/A3 每條已附「出生證」＝本規則的自我遵循示範。

### N — 修剪啟動（第一次修剪審查）  角色: R5 + R1
- 前置: stats 已點名兩批候選。
- 操作: 對①HITL 打回率 0%（0/33）的人閘門（降級候選；註記 33 run 幾乎全為框架自我改進 domain、外部專案未驗證，修剪保守）②從未命中的 gate，進第一次修剪審查。保留 game day、收斂判準、選題多樣化（未滿足，續列）。
- 預期: 修剪是審查、非自動刪除；保守（外部 domain 未驗證）。
- I/O: 副作用: 改 `TODO.md` §15；可能影響既有 HITL gate／gate 定義（審查結論而定，本 run 只寫入修剪啟動條款、不執行刪除）。

---

## 與現有功能互動點

- **skills/eval-flow/SKILL.md step 3 及其全檔引用點（最高互動密度，R-006 家族風險）**：step 2 派審指示、step 4 處置、🟡-only 快速路徑（:88）、重裁條款（:79）、引文核實（:80-84）、Subagent 呼叫原則（:110）、Tier 1 精簡路徑（:270 直寫捷徑「code-reviewer 照常獨立審」）、[P] fan-out（:332）均引用「code-reviewer/reviewer」或審查行為。改 step 3 而漏改任一引用點 → 互相矛盾指令。回歸風險高，拆分須設「全檔 `code-reviewer|reviewer` 引用點盤點」為 B1 item 的 DoD（並由前置 2.5 impact-analyzer 先盤引用清單，risk 報告技術風險第 2 條）。
- **skills/eval-flow-resume/SKILL.md Step 3 表（:43-45）**：現寫死重跑 code-reviewer、未讀 checked_by——新制下 resume 會重跑錯 agent。Spec §4「明確不做」未列 resume skill，故此檔在不在變更範圍＝需裁示（開放問題 2）。回歸風險：中斷恢復派錯 agent。
- **.claude/agents/task-verifier.md**：從「已退役、手動觸發」（:11 退役告示）改為「checker 預設位」（B5）。互動: `tests/test_docs_consistency.py` 的 EnvelopeSpecTest 對 agent 定義有信封關鍵句斷言——重寫須保留信封規範句（該檔已有信封，:78-79）。回歸風險：測試紅。
- **.claude/agents/code-reviewer.md 定義 description＋MODEL_POLICY.md 理由欄**（B6）：只改定位文字，model 維持 opus；`tests/test_model_policy.py` 強制 frontmatter↔MODEL_POLICY 一致——只改理由欄文字、不動 model 指派（Spec §4）。
- **.claude/hooks/eval_gates.py（零變更，僅被依賴）**：task-verifier／code-reviewer 均不在 AGENT_MIN_PHASE（:51-56），checker 化不需改 gate。`verify_passed` gate 語義註解（:246「reviewer 完成度節通過」）在 checker 通過時語義略陳舊，但 Spec §4 禁止動該檔任何行含註解——留為已知不一致、不修。
- **retro/BUGLOG.md**：B7 加選填尾註 `[checker-passed]` 供 grep；與現行兩層制（CLAUDE.md「工作型態前判」）並行，不衝突。回退判定復用機械 grep 機制。
- **retro/RETRO.md**：M（出生證制）把兩層制升級從 bug 擴及所有規則來源；不改既有條目格式。
- **本 run 自身用舊制（reviewer）審**：新制自下一個 run 生效（risk 報告業務風險第 1 條），避免「用未經審查的新制審查新制」的自舉風險——生效時點須寫進 B1 item 的 DoD。

## 正確性假設清單（需使用者逐條裁示）

1. **升級理由代碼①-⑤窮盡**：任一「checker 不該放行」的情況都落在 ①-⑤ 之一；消費點 `.claude/agents/task-verifier.md`（B5 五種升級觸發）＋ eval-flow step 3（B2，R1 裁決）；被破壞時可觀察差異＝某類失敗 case 被 checker 放行且無升級 → 漏網進 commit（由 B7 回退兜底，但延遲一個 bug 才發現）。**真需求（完整性）**；§6b 要求 usage 驗證是否需第 6 類——盤點未發現①-⑤外的觸發，但「疑似注入標註未處理」目前散在 B（核對項⑤）未列入升級代碼，建議確認其歸屬（見開放問題 1）。
2. **checked_by 落檔存在且格式穩定 → resume 辨別 checker/reviewer 的唯一依據**；消費點 `skills/eval-flow-resume/SKILL.md:43-45`（`reviewing`/`fixing` 續跑）＋ R8 稽核 grep 升級率；被破壞時可觀察差異＝resume 重跑錯 agent（checker↔reviewer）、R8 統計失真。**真需求**，但現行 resume 表未讀 checked_by（缺口，見開放問題 2）。
3. **「A 塊先於 B 塊」的拆分排序**；消費點＝**找不到 runtime 消費點**——Tier 2 一個 run 單次 commit 原子落地（eval-flow step 6 收尾單 commit），且新制自「下一個 run」生效（本 run 用舊制審），故 A、B item 在本 run 內誰先寫、對「新制何時帶補償生效」無可觀察差異（次 run 讀到的是同一個 commit 的完整文件）。**裁決＝採納降級：A→B 解除硬依賴，降為閱讀排序偏好（裁示 #11）**——拆分可仍按 A→B 排序以利閱讀，但不設硬 depends、不作為正確性依賴。
4. **仲裁記錄↔mine 指紋一致**（checker 核對項③、既有交付稽核）；消費點 eval-flow step 1 交付稽核＋B② checker；被破壞時可觀察差異＝「改測試湊綠」的機器指紋（mine 次數異常、失敗集合遊走）被漏放。**真需求（既有）**，checker 化不改此假設，只是多一個核對點。

## 開放問題（已於 2026-09-05 HITL 全數裁決；每條附裁決＋一句依據，報告自足）

1. **升級代碼是否需第 6 類「疑似注入標註未處理」**（§6b 窮盡性驗證）：B 核對項⑤列「無疑似注入標註未處理」，但 B2 五種觸發未把它列為獨立代碼。**裁決＝併入④，不設第 6 類（裁示 #1）**。依據：疑似注入未處理＝checker 無法以憑據判定的一種，歸④「不確定即升級」；不擴代碼集守 Minimality（Spec §3 B2④、§6 已更新）。
2. **eval-flow-resume Step 3 表是否納入本 run 變更範圍**：現行表寫死重跑 code-reviewer、未讀 checked_by，新制下會派錯 agent。**裁決＝納入，新增 Spec B8（裁示 #2）**。依據：checked_by 留痕（B3）需有消費者，否則假設 2 破裂；B8 定 resume 中斷在 reviewing 時依 checked_by 決定重派（checker 輪→重派 task-verifier；升級輪→重派 code-reviewer；無落檔→依新制預設派 checker）。
3. **升級輪的落檔 r<N> 編號與 checker 輪的關係**：**裁決＝同輪同 r 號、以 checked_by 區分（裁示 #3）**。依據：升級是「本輪換 agent 重審」非新一輪；checked_by 記最終執行者，resume 的 `<N>` 取最大值語義與計數不受影響（Spec §3 B2）。
4. **Tier 1 的 checked_by 留痕落在哪**：Tier 1 無 eval_state、無 sub_task id。**裁決＝沿用既有 `review-st<item編號>-r<N>` 命名，零新欄位（裁示 #4）**。依據：以 task item 編號當 `<item編號>` 即可落痕，不動 manifest 欄位（守 Spec §4「不新增 manifest 欄位」），R8 稽核仍可見 Tier 1 升級率（Spec §3 B8）。
5. **升級③（mine 指紋異常）與既有 writer 交付稽核（step 1 mine_log 退件）的分工**：**裁決＝主 flow 交付稽核照舊在前；升級③收窄為「checker 讀到的 mine_log 摘要與仲裁記錄不一致」的 checker 側複核（裁示 #5）**。依據：③ 是稽核的補網、非取代——稽核先退件，退不掉的由 checker 憑其讀到的摘要複核升級（Spec §3 B2③）。
6. **升級⑤（writer「表沒答案」失敗交付）與 step 1「主 flow 補契約表回派」的先後**：**裁決＝正常路徑為 step 1 主 flow 補表回派；升級⑤僅為「未經主 flow 處置」時的兜底（裁示 #6）**。依據：checker 遇未處置的失敗交付＝流程遺漏，兜底升 reviewer；不與 step 1 硬規則衝突（Spec §3 B2⑤）。
7. **快速路徑在升級輪的措辭是否需調整**（§6c）：**裁決＝快速路徑僅適用升級輪；checker 輪對不上即升級、無 🟡 分級（裁示 #7）**。依據：checker 輪不做 🟡 分級（Spec §5 作廢清單同義），措辭在 step 4 快速路徑段補「僅升級輪適用」即可（Spec §6）。
8. **B7 回退「該類 item」的操作定義**：**裁決＝回退機制升級為 v3——機械偵測＋補救一律 HITL（裁示 #8）**。依據：機械的是「BUGLOG `[checker-passed]` 尾註＋同根因分類 grep，第 2 次命中強制停下」；補救不機械化——產裁決 packet（含兩 bug 根因、checker 當輪落檔、四選項附成本：(a)上游規則提案 (b)新增升級觸發⑥ (c)恢復 reviewer 預設 (d)接受風險），agent 不可自行選、無自動總開關（比照 Hotfix「不可自行認定」）。原「機械 grep 恢復 reviewer」的裁量疑慮由「補救過人」消解（Spec §3 B7）。
9. **checker 輪是否計入「修正 2 輪上限」**：**裁決＝checker 輪與升級本身不計入；上限只數 reviewer 退回的修正迭代（裁示 #9）**。依據：checker 不產 🔴、不進 fixing，佔額度會誤縮修正空間（Spec §3 B2）。
10. **§6a 憑據節輸入截斷策略**：**裁決＝已截斷＋存疑即升級，不明文上限（裁示 #10）**。依據：輸入已是截斷版（`--stat` 非 full diff、測試輸出取尾段、mine_log 取摘要），逐項以 grep 存在性為主、語義存疑推給升級 reviewer；不設硬上限（Spec §6）。

## Self-check: 已覆蓋 A/B/C 三變更塊、5 種升級觸發、回退、Tier 1/2 差異、resume 讀 checked_by、[P] fan-out 相容；10 條開放問題與 A→B 拆分假設全數於 2026-09-05 HITL 裁決並逐條記入（附裁決＋依據，對照 Spec §3 B2/B7/B8 與 §6），報告自足。
