# 2026-07-30 reviewer 行號核對紀律（run_id: 2026-07-30-reviewer-citation-discipline）

**背景（自足說明，不依賴對話）**：2026-07-28～30 期間 code-reviewer 的審查報告出現 5 次行號漂移——引用的程式碼文字為真、但行號與實際檔案不符，偏移 1～16 行。現行防線只在消費端（`skills/eval-flow/SKILL.md` 的「引文核實」規則要求主 flow 發現不符即駁回該條發現），生產端（`.claude/agents/code-reviewer.md`）沒有任何核對要求。實測觀察：主 flow 在派審 prompt 中明確要求「行號請以實際檔案核對過再寫」的輪次未發生漂移，未特別要求的輪次則發生 → 問題在生產端可控，但目前全靠主 flow 每次臨時補一句、未制度化。又因發現的實質多為真，主 flow 曾三次未依「直接駁回」規則駁回，使消費端規則形同虛設。

**Tier**：1（精簡路徑）。**檔案範圍（硬性）**：僅 `.claude/agents/code-reviewer.md` 與 `skills/eval-flow/SKILL.md`；不得修改任何既有測試檔。

**不做的事**：不新增測試（本需求無機械可驗的行為面，效果靠後續實際審查輪次觀察）；不改任何 hook 判定式（`.claude/hooks/*.py` 零變更）；不新增章節結構（一律放進既有節、沿用既有書寫體例）。

---

## Task 1：行號核對紀律雙端落地（prose 合併為一個 sub_task，一輪審查）

兩個 item 同源於一個設計決策（生產端下硬性核對要求、消費端把處置寫死成機械判準），皆為純 prose、單檔 ≤30 行，依 eval-flow skill「小 prose item 合併」規則合併為單一 sub_task 審查。

- [x] **item 1：生產端硬性核對要求**（`.claude/agents/code-reviewer.md`，~10 行）
  - 契約：**放進既有「工作守則」節的「有憑有據」條目內**（該條已規範「引文須當場複製」，行號核對是同一主題的延伸），不另起新節、不加冗長段落。
  - 契約：要求具體到指令層級——明寫用 `git show :<檔案> | sed -n '<N>p'`（讀 staged 內容，與主 flow 核實基準一致）或 `git show :<檔案> | grep -n -F '<片段>'` 取得真實行號，並明文禁止憑記憶／憑 diff hunk 標頭推算行號。
  - 契約：寫明對 reviewer 自身的後果（誘因說明）——行號對不上會被主 flow 依「引文核實」規則駁回整條發現，等於該發現作廢。
  - DoD：`grep -c "sed -n" .claude/agents/code-reviewer.md` ≥ 1；新增內容位於「## 工作守則」與「## 輸出格式」之間（既有節內）。

- [x] **item 2：消費端寫死行號偏移判準**（`skills/eval-flow/SKILL.md` 循環 step 3「引文核實」條，~12 行）
  - 契約：補上與生產端的呼應（生產端已有核對要求，本條為消費端補網）。
  - 契約：**釐清「引文文字為真、僅行號偏移」的處置，且必須是無臨場裁量空間的機械判準**——以 grep 得不得到引文文字作為二分依據，並附一個機械的整份退件門檻（同一輪需修正的條目數上限）。留裁量正是這條規則被繞過三次的原因。
  - DoD：該條讀完後，任何接手者面對「文字真、行號錯」只有一種可執行動作，不需再問人。
  - DoD：`skills/eval-flow/SKILL.md` 修改後同步部署副本 `~/.claude/skills/eval-flow/SKILL.md`（`diff` 空輸出）。

### 驗收（DoD 總表）

1. `code-reviewer.md` 含具體核對指令的硬性要求，且位於既有節內。
2. `skills/eval-flow/SKILL.md` 的引文核實規則已補上明確可執行的行號偏移判準（無臨場裁量空間）。
3. `python3 -m unittest tests.test_docs_consistency` → OK。
4. `python3 -m unittest discover -s tests` → 162 tests OK。
5. `diff skills/eval-flow/SKILL.md ~/.claude/skills/eval-flow/SKILL.md` 空輸出。
