# TODO — Agent Flow 改進事項

> 來源：2026-07-08 agent flow 架構檢視（基於 commit 8a06bc6 這一版）。
> 建議執行順序：#2 → #4 → #3，#1 可隨時獨立進行。

## 1. 用 hooks 把硬性 gate 落地（最大槓桿）

目前所有 gate 都是散文層級約束，靠 model 遵循，無技術強制。至少三條搬進 pre-commit hook：

- [ ] 檢查 `run/<run_id>.json` 存在且 `spec_path`／`spec_inline` 至少一個非空（intent gate）
- [ ] 確認測試指令已執行且通過（對應循環步驟 5 的本地測試 gate）
- [ ] 擋住 `eval_state.json` 尚存在時的 commit（防跳過歸檔）

可用 `/update-config` 設定。

## 2. 把 Eval Flow 執行細節抽成 project skill

CLAUDE.md 每個 session 全文載入，但約七成內容（前置 0–3、循環 1–8、兩個 JSON schema、操作規則）只在實際執行 Tier 2 run 時需要。

- [ ] 新建 `eval-flow` skill，承載流程執行細節
- [ ] CLAUDE.md 只留：部署規則、Router 分級表、防濫用規則、「判為 Tier 1/2 → 依 eval-flow skill 執行」的指引
- 效果：常駐 context 變小、按需載入時遵循率更高、漂移面縮小（與 task-decomposition skill 同一原則）

## 3. 解決雙語文件漂移（做個決定）

`CLAUDE.eng.md` 曾落後中文版好幾代而無人發現；兩份手工維護的等價文件必然漂移。三選一：

- [ ] (a) 刪除英文版（推薦——若無明確讀者，僅是維護成本）
- [ ] (b) 明定中文版為唯一 source of truth，英文版標「generated, do not edit」、由同步指令產生
- [ ] (c) 只留英文版

另注意：專案內還有 `CLAUDE.gl.md`，一併盤點用途。

## 4. 修「commit 後回填」的慢一拍問題（一句話補丁）

先 commit manifest、再回填 `commit_sha` → git 裡的 manifest 永遠缺 `commit_sha`；`run/<run_id>.eval.json` 也是「下次 commit 才進 git」。若是最後一個 run，溯源鏈最後一環斷在 working tree。

- [ ] 在 CLAUDE.md 補一條：「每次 run 的 commit 前，先把上一輪殘留的 manifest 回填／eval 歸檔檔一併 `git add`」

## 5. 讓「測試存在」成為要求，closing the loop

循環步驟 5 允許「無測試框架時實際運行驗證」——專案只要一直沒測試，gate 就一直走後門。

- [ ] 在 task-decomposer 的 item 五要素（或 DoD）明定「新行為需附測試」，使步驟 5 有測試可跑，與 Testability 評分維度閉環

## 6. 持續追蹤項

- [ ] **Tier 分佈統計**：manifest 已記 `tier`，跑一陣子後統計——若 Tier 1 幾乎為零，代表分級未發揮省成本作用，門檻應放寬
- [ ] **RETRO.md 增長控制**：code-writer 每次都讀，遲早膨脹。加一條「超過 N 條時，retro agent 合併同根因條目」
