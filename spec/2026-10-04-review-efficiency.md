# 首次實測改善

使用者已確認六項更新，分兩批。維持 checker 獨立性、四类實質升級、既有測試/commit gate、unknown_codex 與 Claude CLI 延後。

## 第一批
1. review_packet.py 從 manifest.task_file 取得指定 Task 全文（DoD/契約/退場原文）、writer report、staged stat、writer mine 輸出組装資料。不自動宣稱審查/測試通過。
2. 組装時機械檢查必要檔案、分節、測試命令/結果與各item定位；缺資料非零、先補再派。資料齊全但checker存疑/失敗/注入/契約不符仍升級。dispatch可接受 --review-packet，派工前重驗來源/staging，失效不啟動CLI。舊派工兼容，標準指引採新入口。
3. reviewer/checker先讀有效證據。重跑只限輸入變更/失敗/具名疑點，不同命令不得互當證據。記packet檢查耗時、缺項與dispatch次數；未知tokens仍unknown。
## 第二批
4. 首次載入eval-flow只含入口與当前步驟指引，詳則按需載入；原文外移保留每個硬gate及升級規則投放路徑。
5. preflight提前識別nested repository。快照未追蹤/忽略nested repo可由既有Git排除範圍處理，不自行改exclude；未排除nested repo failclosed具體訊息。真正tracked gitlink/submodule須可驗證髒樹/工作樹變更，不可只hashHEAD。排除清單變化須使快照失效；禁止任意排除trackedcode。
6.標準收尾用flow finish，保留原prepare/commit/finalize的語義与中斷恢復。

## 介面骨架
packet build(manifest,taskID,report_path,test_output_path,files) -> {sources,task全文,report全文,stat,test輸出,missing,inputs_digest}；格式與來源核對不作審查判定。
packet validate(packet) -> 重讀來源与staging對比，missing/drift ->拒絕；否則只允許派checker，checker仍自行核對。
嵌套repo分類：gitlink由index mode160000辨識；一般nested由.git目錄/檔案辨識；僅對Git已忽略而未追蹤的repo允許跳過。

## 驗收
完整資料一次派checker；缺資料零模型呼叫；實作疑慮仍具升級指令。stale packet拒絕。測試證據無重跑也不假稱可用。nested repo未排除提前報問題、Git已批准exclude範圍保留；tracked來源改變必使snapshot失效。文件外移逐條原文一致、部署Codex生成角色一致、全套最後一次由run_verify。

## 實測後修正與量測（使用者 2026-10-04 確認）
- 修正文件搬移後 test_agent_refs 漏掃 references 的失敗，保留全部既有斷言。活躍技能與 reference 文件由共用 document_inventory.py 發現；安裝與文件一致性檢查共用來源，排除 _deprecated，技能 assets/scripts 部署方式保持。使用真實暫存文件驗證有效引用可見、無效引用仍阻擋。
- 沿用 stats.py 與現有驗證／packet 事件，列出實際執行、快取重用、相同命令重複執行、已記錄耗時與缺資料原因。不新增 gate；缺資料標無記錄、不當零。既有升級碼統計保留；沒有逐輪資料時不宣稱首次檢核通過率。
- 本次完成後先以 3 個真實工作觀察，不再擴充流程；由量測結果決定改善。不將入口字元減少等同總 token／時間節省。Claude CLI 實測仍延後。
- 獨立審查確認：快照前置拒絕不等於命令執行。驗證紀錄新增可選 executed 標記，僅 subprocess 真正啟動路徑為 true；stats 區分已執行、重用、前置拒絕與舊紀錄未知。舊有 error 且缺 executed 的紀錄不推定實跑；此欄純量測、不改 gate。
