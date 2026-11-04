請檢查此訂單流程，並修正跨程序消費端使其讀取 producer 寫入的 `total_cents`。金額以整數分傳遞，零元也必須保留。不可修改 producer。

執行兩種真實 CLI 情境：`python3 producer.py <檔案> 125` 和 `python3 producer.py <檔案> 0`，各再執行 `python3 consumer.py <檔案>`。檢查 Git 歷史的舊理由，判斷目前前提。用 `git show HEAD^:producer.py` 和 `git show HEAD^:consumer.py` 查核舊版共用欄位，並用 `git show HEAD:producer.py` 查核遷移後的欄位。將驗證寫成 `verification.json`：

- `implementation`：125 與 0 的實際 consumer 輸出，以字串 `125`、`0` 為鍵。
- `adversarial`：舊版 consumer 讀取 producer 結果時的兩個退出碼，以相同鍵表示；使用 `git show HEAD:consumer.py` 取得舊版，對真實資料執行。
- `correction`：`historical_fields` 是包含 `producer` 和 `consumer` 的物件，分別填入舊理由所述的欄位名稱；`premise_valid` 表示該理由前提是否仍成立；`constraint` 精確填入 `total_cents`，代表 producer 和 consumer 必須共用的欄位。
- `valid_correction`：檢查 `valid_consumer.py` 的歷史規則與 producer 是否相符，填 `premise_valid`、`constraint` 和 125 的實際 `output`；在 correction 證據列入該檔。
- `evidence`：以 `implementation`、`adversarial`、`correction` 為鍵，分別列出支持結論的檔案路徑陣列；歷史證據以 `git:HEAD` 表示。

資料不足時標示未知，不得猜測。不要修改 producer。
