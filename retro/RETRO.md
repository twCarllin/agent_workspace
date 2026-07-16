# RETRO

> 每條寫成可直接貼進 writer prompt 的**約束句式**（背景一句、約束一句），不寫敘事——retro 的消費方式是前置進 prompt 硬性約束區（eval-flow 循環 step 1），不是開工前通讀。

- 2026-07-15［hook／bugfix］`eval_gates.py` 的 `MANIFEST_RE` 誤把 `run/<id>.test_baseline.json` 當 manifest 攔 commit——排除規則只寫在單一呼叫點的 `endswith(".eval.json")`，新增衍生檔種類時沒有同步。**約束：以 pattern 判檔案身分時，排除規則必須寫進 pattern 本身（單一判定點），不可散落在呼叫點用 endswith 補丁；新增衍生檔命名時，先查所有以檔名 pattern 分流的地方。**
- 2026-07-16［流程設計／skill 規則投放路徑／2026-07-16-review-writeahead-fixture-rules］test-strategy skill 的 Mutation self-check 新增規則時，把重放 sabotage 的責任指派給 code-reviewer——但 reviewer 定義明訂只讀不寫（sabotage 需改檔）、且 reviewer 呼叫時完全不載入 test-strategy skill（無投放路徑），導致規則寫了等於沒生效。根因是新增跨角色規則時只驗證「內容對不對」，未驗「收件人讀得到嗎（投放路徑）」與「收件人有權限做嗎（角色約束）」。**約束：在 skill 或 agent 定義中新增執行步驟時，必須先確認兩點再落筆：（1）該步驟所在的文件是否在執行者的載入路徑內；（2）執行者的角色定義是否允許執行所需操作——任一不符則改換收件人，不可只改措辭。**
