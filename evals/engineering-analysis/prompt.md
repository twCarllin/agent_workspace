請調查 fixture 中的訂單資料流、原因、設計與影響。執行 `python3 app.py` 取得真實結果，閱讀程式及 `git log --all --format=%s`。不要修改 fixture。將分析寫入 `analysis.json`，格式如下，所有值均為 JSON：

- `understanding`：兩個案例的實際淨額，鍵為 `standard`、`discount`。
- `cause`：歷史目的 `operation_order` 是操作名稱陣列（折扣填 `discount`、稅填 `tax`，依實際先後排序）；另填目前折扣案例實際淨額 `actual`、符合目的的淨額 `expected`、前提是否仍成立 `premise_valid`（布林值）。
- `valid_cause`：對 `valid_pricing.py` 執行相同折扣案例，填 `actual`、`expected` 和 `premise_valid`，並在原因證據中列入該檔案。
- `design`：兩個候選 `before_tax`、`after_tax` 各自對兩案例的淨額（鍵同上），及符合「先扣折扣再計稅」契約的 `choice`。
- `impact`：列出直接消費淨額的兩個實際檔案路徑 `consumers`，以及折扣案例下兩者分別輸出的字串 `outputs`（以路徑為鍵）。
- `evidence`：以 `understanding`、`cause`、`design`、`impact` 為鍵，各列出支持結論的現有檔案路徑陣列；原因須包含可查詢的 Git 歷史（用 `git:HEAD` 表示）。

數值均使用整數分。證據不足時標示未知，不得猜測。
