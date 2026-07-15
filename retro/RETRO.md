# RETRO

> 每條寫成可直接貼進 writer prompt 的**約束句式**（背景一句、約束一句），不寫敘事——retro 的消費方式是前置進 prompt 硬性約束區（eval-flow 循環 step 1），不是開工前通讀。

- 2026-07-15［hook／bugfix］`eval_gates.py` 的 `MANIFEST_RE` 誤把 `run/<id>.test_baseline.json` 當 manifest 攔 commit——排除規則只寫在單一呼叫點的 `endswith(".eval.json")`，新增衍生檔種類時沒有同步。**約束：以 pattern 判檔案身分時，排除規則必須寫進 pattern 本身（單一判定點），不可散落在呼叫點用 endswith 補丁；新增衍生檔命名時，先查所有以檔名 pattern 分流的地方。**
