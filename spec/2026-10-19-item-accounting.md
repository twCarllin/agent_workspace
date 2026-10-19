# Eval Flow 交付對帳與驗證信號

## 問題與證據

`run_commit.py` 在憑據檢查後直接設定 `status=completed`（`.agent-flow/scripts/run_commit.py:65`）。現有 `eval_state` 一筆代表 task，沒有 item 層資料（`.agents/skills/eval-flow/references/formats.md`「eval_state.json 格式」）。因此，task 少做一個 item 仍可能完成。

## 需求

1. HITL 確認時固定 task 檔的 item ID 清單；後續刪除或改名不得讓已確認 item 從對帳中消失。舊 run 保持可恢復，不補造確認資料。
2. 每個已確認 item 在完成前須有逐項交付憑據。交付憑據須指向本次 commit 內的檔案；收尾前先核對 staged 檔，提交後再核對實際 SHA 與檔案。
3. agent 建議不做 item 時，run 設為 `paused` 並記理由，不能自行移除。只有使用者裁示紀錄可把該 item 標為移除。裁示須包含原文、時間與來源；`hitl_rulings` 數字本身不算裁示。
4. `completed` 只用於已確認範圍全部交付或經使用者裁示移除。若使用者明示接受部分交付，使用 `partial`，記未交付 item；不能用 `completed` 表示部分完成。
5. 舊 manifest 不得因新增欄位直接失效。新 run 缺 item 對帳資料時須擋下完成。命令與文件須說明修復方法。
6. 涉及外部答案解析的修改，離線重放至少使用兩個獨立樣本，其中一個是已知失敗反例。單一樣本只能標為「單一樣本，未證實」，不能用來取消 item；審查與測試紀錄須可核對樣本、結果及結論。
7. 外部資料有內容但抽取結果全為零時，執行端須在 job 的 quality 欄記明確數量標記（如 `financial_dropped_all: 20`），保持產出流程可繼續；送 job 後的監看須主動回報該標記。Eval Flow 須要求實作、測試與審查核對這條契約，不以 WARNING log 代替 quality 欄。
8. 發現第二根因時，先量化影響，對照既有需求。超出確認範圍時只提出建議，待使用者裁示才納入，不自行擴張 scope。

## 範圍

本 Spec 只處理 Eval Flow 模板。需求 6–8 透過角色指令、驗證策略、審查與流程 gate 落地；模板不直接處理特定公司的財務 job。
