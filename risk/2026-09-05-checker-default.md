# 風險分析 — 2026-09-05-checker-default（審查層 checker 化＋治理 v2＋上游補償三規則）

> Spec: `spec/2026-09-05-checker-default.md`。六面向：技術、業務維護兩面向有風險；不適用清單見下。

不適用：安全、資料、效能、部署（本 run 全為 prose／agent 定義／流程文件變更＋既有測試檔更新；不處理使用者輸入、不觸 DB、不涉部署序、無執行期效能面——經查證 eval_gates.py／eval_state.py／stats.py 零變更，Spec §4 明文排除）

## 技術風險 (Technical Risk)

- 🟡 **checker（haiku）能力邊界**：憑據核對含「契約 row ↔ 測試斷言對映」（需 grep 測試檔並判斷斷言語義覆蓋），haiku 對語義判定的假通過率未實測。**對策**：①升級觸發④明定「無法以憑據判定＝升級」，不確定不放行；②B7 回退條款以 BUGLOG `[checker-passed]` 留痕，第 2 次命中即恢復 reviewer——假通過的損害有兜底與量測；③task-verifier 定義中把「逐 row grep 斷言存在」寫成機械步驟（存在性層機械、覆蓋語義層存疑即升級），縮小 haiku 的裁量面。帶入分拆備註（B5 item）。
- 🟡 **循環文件的內部一致性**：eval-flow step 3 是全 skill 引用最密的節（step 2 派審指示、step 4 處置、快速路徑、重裁條款、引文核實、憑據紀律、Tier 1 精簡路徑、[P] fan-out 節均引用「code-reviewer」或審查行為）——改 step 3 而漏改引用點會產生互相矛盾的指令（R-006 家族風險）。**對策**：分拆時設「全檔引用點盤點」為 B1 item 的 DoD 條目（grep `code-reviewer|reviewer` 全 skill 逐點裁決改／不改），並由 impact-analyzer（前置 2.5）先盤引用清單。帶入分拆備註。
- 🟢 過度工程風險低：Spec §4 已排除欄位化、hook 化、統計化（Minimality 先行）。

## 業務與維護風險 (Business & Maintenance Risk)

- 🟡 **regression 面＝審查品質下降**（本 run 的本質權衡，使用者已知情裁決）：checker 不讀 diff，「契約外行為缺陷」的攔截率下降是設計上接受的成本。**對策**：①三條上游補償規則（A1–A3）同 run 先行（拆分依賴：A 塊 items 完成才進 B 塊）；②B7 回退條款寫死、機械 grep 判定；③本 run 自己的循環仍用舊制（reviewer）審——新制自下一個 run 生效，避免「用未經審查的新制審查新制」的自舉風險。帶入分拆備註（生效時點寫進 B1 item DoD）。
- 🟡 **文件↔既有測試的一致性**：tests/test_docs_consistency.py 的 EnvelopeSpecTest（信封關鍵句）與 RetroIdReferencesTest（R-NNN 引用）對 agent 定義與 skill 有斷言——task-verifier 定義重寫必須保留信封規範句；新規則若引用 R-NNN 需真實存在。**對策**：B5／A1–A3 items 的 DoD 綁 `python3 -m unittest tests.test_docs_consistency` 綠。帶入分拆備註。
- 🟢 使用者可見影響：流程行為變更已由 Spec §5 作廢清單明列，使用者即本 flow 的 owner，已裁決。

## 結論

無 🔴。四條 🟡 全數有對策並標注「帶入分拆備註」，可進前置 2（使用情境分析）。
