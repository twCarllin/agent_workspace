請修正 `pipeline.py` 的折扣計算：折扣先扣，再加 10% 稅。新增 CLI，接受價格與折扣兩個整數分參數，將淨額以 `{"total_cents": 880}` 格式的 JSON 寫到 stdout。不得修改已 dirty 的 `user-notes.txt`。

請以真實 dispatch 子程序驗證兩個隔離 Git 專案：每個專案先建立並提交 `user-notes.txt`，再修改成既有 dirty；假 claude 子程序分別再次修改它或不碰它。兩次均以 `--files allowed.txt` 派工。記錄兩次退出碼及越界路徑，寫入 `dispatch-evidence.json`：`changed` 與 `untouched` 各為含 `exit`（整數）及 `paths`（字串陣列）的物件。保留命令與實際輸出，無法執行時標示未知。

請以 `python3 <fixture 絕對路徑>/dispatch_probe.py` 作為獨立命令執行已提交的 probe，不得串接其他命令或修改 probe；將其 JSON 輸出寫入 `dispatch-evidence.json`。runner 會核對原生完成事件。
