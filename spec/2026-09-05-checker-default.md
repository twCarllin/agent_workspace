# Spec — 審查層 checker 化（checker-by-default）＋治理規則 v2＋上游補償三規則

> run_id: 2026-09-05-checker-default。本 Spec 自足：不依賴對話上下文，引用檔案以路徑＋節名指向。
> 決策背景（使用者已裁決）：全部 item 預設 checker、不分 tier、無 named 例外清單，僅保留升級路徑；#15 治理由時間閘改證據閘；三條上游規則為 checker 化的補償控制，必須同 run 落地。

## 1. 背景與動機（數據）

- 實測（run 2026-09-05-model-policy-devlog＋2026-09-05-agentflow-prompt-hardening，7 輪審查）：code-reviewer（opus）佔 subagent 原始 tokens 39%、**成本加權約 76%**（opus 單價 ≈ sonnet 5×、haiku 15×）。
- stats.py（33 run）：rework 率 5%（3/55 sub_task 首輪有 🔴）——95% 審查輪讀全 diff 後零 🔴。
- reviewer 近期實質 catch（devlog `--dir` 組合缺口、恆真斷言、信封語義碰撞）逐一可上游化或機械化（見 §3 A1–A3）——補償控制到位後，審查層可降為憑據核對。
- 歷史對照：task-verifier（checker 疊在 reviewer 上）2026-07-25 退役，因 0 獨有發現；本變更是反向實驗（checker 取代 reviewer 預設位），**必須帶回退條件與留痕**，讓 BUGLOG 數據裁決。

## 2. 目標

審查層成本（成本加權）降 ~70%＋，同時：契約覆蓋品質靠拆分期規則補強（A1、A3）、測試鑑別力靠機械自檢補強（A2）、漏網 bug 由 BUGLOG 回退條款兜底（D）。

## 3. 變更項目

### A. 上游補償三規則（同 run 落地；A→B 為閱讀排序偏好、非硬依賴——usage 裁示解除：單 run 原子 commit 下無 runtime 消費點）

- **A1 組合 row 規則**（`skills/task-decomposition/SKILL.md`「行為契約表」節）：item 有 **≥2 個可獨立取值的輸入面**（旗標×模式、參數×路徑、選項×子命令）時，契約表除既有「至少 1 條邊界輸入」外，**須含至少 1 條組合 row**（兩個輸入面同時取非預設值的可觀察效果）。出生證：「契約表覆蓋不足」家族第 2 次實例——第 1 次（怪檔名 🔴）催生「至少 1 條邊界」，第 2 次為 run 2026-09-05-model-policy-devlog 的 devlog `--dir`×清單模式缺口（reviewer r1 抓到、契約表無 row、測試零覆蓋）。
- **A2 sabotage 鑑別力自檢**（`.claude/agents/code-writer.md` 測試管轄規則）：交付含**新增測試檔**的 item 前，writer 須對每個新增測試檔做一次 sabotage 自檢——暫時破壞被測行為的關鍵判定 → 對應測試須 FAIL → 還原 → 須 PASS → 清 `__pycache__` → `git diff` 證明零殘留；證據（sabotage 點＋FAIL/PASS 輸出尾行）記入工作報告。出生證：「假測試」家族第 2 次實例——test_lint（靜態）抓語法型假測試，本次恆真斷言（`assertNotIn` 永不出現的字串）為語義空洞、僅動態可抓（run 2026-09-05-model-policy-devlog r2 reviewer 抓到）。既有 Tier 2 整合測試 item 的 mutation self-check 不變，本條把最小版擴到所有新增測試檔。
- **A3 多處投放語義檢查**（`skills/task-decomposition/SKILL.md`，拆分期檢核）：同一句規範文字投放到 **≥2 個異質語境**（多個 agent 定義、多個 skill）的 item，拆分期（Tier 2 拆分者／Tier 1 主 flow）須逐語境核對該句的關鍵詞在各語境無語義碰撞，碰撞則措辭加區隔詞。出生證：R-006（跨文件語義相容）之投放期應用——run 2026-09-05-agentflow-prompt-hardening 信封「報告」在 4 個寫檔 agent 與 artifact 檔碰撞（st2.4 r1 reviewer 抓到）。

### B. checker-by-default（eval-flow 循環結構變更）

- **B1 循環 step 3 改寫**（`skills/eval-flow/SKILL.md`）：預設派 **`task-verifier`（checker，haiku）**，取代預設派 code-reviewer。checker **不讀 diff**，輸入＝task 檔該 item（DoD＋契約表）＋writer 工作報告全文＋step 2 的 `git diff --cached --stat` 輸出＋測試輸出尾段＋mine_log 摘要；職責＝核對「宣稱與憑據對得上」：DoD 逐條有憑據、契約 row 逐條有對應測試斷言（以 grep 測試檔核）、仲裁記錄與 mine 指紋一致、sabotage 自檢證據存在（A2）、無疑似注入標註未處理。產出兩節報告（完成度節照舊格式；憑據節取代品質節）。
- **B2 升級路徑**：checker 遇任一情況 → 主 flow 改派 **code-reviewer 全 diff 審**（既有流程原樣）：①憑據對不上或缺席；②契約 row 找不到對應測試斷言；③checker 讀到的 mine_log 摘要與 writer 仲裁記錄不一致（主 flow 的交付稽核照舊在前，本觸發為 checker 側複核，usage 裁示 #5）；④checker 自報無法以憑據判定（不確定即升級，不得自行放行；**疑似注入標註未處理併入本類**，usage 裁示 #1，不設第 6 類）；⑤writer 報告帶失敗交付或「表沒答案」仲裁未經主 flow 處置——正常路徑為循環 step 1 主 flow 補表回派，checker 遇未處置者＝流程遺漏，本觸發為兜底（usage 裁示 #6）。升級後該 sub_task 本輪照舊 reviewer 流程（引文核實、重裁、快速路徑均不變）；升級輪與 checker 輪**同輪同 r 號**、以 checked_by 區分（usage 裁示 #3）；checker 輪與升級本身**不計入修正 2 輪上限**（上限只數 reviewer 退回的修正迭代，usage 裁示 #9）。
- **B3 留痕**：每輪審查落檔標明 `checked_by: checker|reviewer(escalated: <理由代碼①-⑤>)`；eval.json 歸檔的 rounds 照舊（不新增 eval_state.py 欄位——升級率統計先靠審查落檔與 eval.json 的 prose，欄位化待 stats 有需求再議，Minimality）。
- **B4 憑據契約不動**：`review_reds`／`verify_passed`／commit gate 全部照舊——checker 通過＝該輪零 🔴 照填；升級輪由 reviewer 結果填。hook（eval_gates.py）零變更（task-verifier／code-reviewer 均不在 AGENT_MIN_PHASE，經查證 eval_gates.py:51-56）。
- **B5 task-verifier 定義改造**（`.claude/agents/task-verifier.md`）：從「完成度驗證員（退役保留手動）」改為「checker——審查層預設位」；明定不讀 diff／輸入清單／兩節報告格式／五種升級觸發（自報建議，裁決在主 flow）；防注入條款與報告信封比照其他 agent（已有信封）。model 維持 haiku。
- **B6 code-reviewer 定位更新**（定義檔 description＋`MODEL_POLICY.md` 理由欄）：從「循環預設」改為「升級路徑專用＋高風險手動觸發」。model 維持 opus。
- **B7 回退機制（v3，usage 裁示 #8 定案：機械的是偵測與停下，補救一律 HITL）**：checker-only 放行的 item 事後爆 bug → BUGLOG 條目加尾註 `[checker-passed]`（機械留痕）。BUGLOG append 時 grep 同根因分類＋`[checker-passed]` 尾註，**第 2 次命中 → 強制停下、產出裁決 packet 交使用者**：packet 含兩個 bug 的根因、checker 當輪審查落檔、四個選項附成本——(a) 上游規則提案（retro 產出＋出生證）(b) 新增升級觸發⑥（該類特徵命中即派 reviewer）(c) 恢復 reviewer 預設 (d) 接受風險。**agent 不可自行選任一補救**（同 Hotfix「不可自行認定」原則）。設計依據：「reviewer 攔得住該類」是未經證明的反事實、補救選擇是經濟權衡屬 owner 決策、觸發點必然在 bugfix run 內人在場故 HITL 零延遲。不設自動總開關（每次命中都過人）。
- **B8 resume 相容（usage 裁示 #2 納入範圍）**：`skills/eval-flow-resume/SKILL.md` 的 Step 3 處置表更新——中斷在 reviewing 時依審查落檔的 `checked_by` 標記決定重派對象（checker 輪→重派 task-verifier；升級輪→重派 code-reviewer；無落檔→依新制預設派 checker）；Tier 1 落檔命名沿用既有 `review-st<item編號>-r<N>`（usage 裁示 #4，零新欄位）。

### C. 治理規則 v2（`TODO.md` §15 改寫）

- 凍結條款廢止（解除條件已滿足：33 completed run、stats 有數據），改為：
  1. **出生證制**：新流程規則須引用證據——BUGLOG／RETRO 條目（recurring 或 severe one-off）或使用者明示決策；單發 observation 留證據層不成規則（BUGLOG 兩層制從 bug 擴及所有規則來源，含 reviewer/checker catch）。
  2. **Minimality 逐筆**：新規則附「被否決的更小替代」一句；同一規則家族第 2 次被修 → 重開設計而非就地補丁。
  3. **修剪啟動**：stats 已點名的兩批進第一次修剪審查——HITL 打回率 0%（0/33）的人閘門（降級候選；註記：33 run 幾乎全為框架自我改進 domain，外部專案未驗證，修剪保守）、從未命中的 gate。
  4. 保留：game day、收斂判準、選題多樣化（未滿足，續列）。

## 4. 明確不做

- 不動 `eval_gates.py`／`eval_state.py`／`stats.py`／任何 hook script 的任何行（含註解）
- 不刪 code-reviewer 定義、不改任何 agent 的 model 指派（MODEL_POLICY 只改理由欄文字）
- 不新增 manifest／eval_state 欄位
- 不動 Tier 0／Tier B 路徑、不動前置 0–3、不動 step 5 測試 gate 與 step 6 收尾
- 不做 checker 的升級率統計欄位化（等實測需求）

## 5. 作廢舊行為清單（流程行為變更對照）

| 舊 | 新 |
|---|---|
| 循環 step 3 預設派 code-reviewer 讀 staged diff | 預設派 task-verifier（checker）核憑據；五類觸發升級派 code-reviewer |
| task-verifier＝已退役、僅手動觸發 | task-verifier＝checker，審查層預設位 |
| reviewer 🟡-only 快速路徑（審查輪內） | 保留，僅適用於升級輪（checker 輪無 🟡 分級——對不上即升級） |
| #15 規則凍結（5 run 前不加規則） | 廢止，換證據閘（出生證＋Minimality＋修剪） |
| resume 中斷在 reviewing → 固定重跑 code-reviewer | 依審查落檔 checked_by 決定重派 checker 或 reviewer |

（本清單為流程文件行為，無既有自動化測試斷言舊流程句——tests/test_docs_consistency.py 的檢查項不涉 step 3 內容，經查證。）

## 6. 開放設計點（已全數裁決，2026-09-05 HITL；裁示全文見 usage 報告「開放問題」節）

- 截斷策略：已截斷＋存疑即升級，不明文上限（裁示 #10）
- 升級代碼①-⑤足夠，疑似注入併入④（裁示 #1）
- 快速路徑僅適用升級輪，checker 輪對不上即升級、無 🟡 分級（裁示 #7，§5 作廢清單同義）
