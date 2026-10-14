# 增量審查與驗證重用

首輪仍獨立審完整 task。以下只減少重複工作，不改變驗收、HITL、修正輪數上限與失敗阻擋。

## 增量重審

主 flow 在派首輪 reviewer 前，用 `review_delta.py capture --checkpoint run/<id>.review.json --files <task檔案> --contracts <Spec及task檔>` 保存 index 與契約雜湊。reviewer 完成後，index 與契約未變才用 `review_delta.py reviewed --checkpoint <同檔> --session <真實reviewer session>` 標記已審。此標記只證明該版本已看過，不表示通過。

修正重審用 `review_delta.py diff --checkpoint <同檔> --files <同範圍> --contracts <同契約>`。`mode=delta` 時提供前次已審版本到目前 index 的差異；同一 reviewer 確有前次上下文且契約未變時沿用，只傳未解問題、delta 與新增證據；reviewer 可讀相關上下文與呼叫端。新 reviewer 或 context 遺失時提供相應完整契約與完整 task staged diff；契約變動原文必須明示。範圍／契約變更、checkpoint 缺失或失效則 `mode=full`，提供相應完整契約與該 task 的完整 staged diff，不能因 fallback 省略首輪；checkpoint 捕捉、標記與失效規則不放寬。

delta 為空不代表通過：有未解問題或缺少前次結論時不能自動放行。重審通過後的證據只適用該次 index；獨立性、引文核實與完成度檢查保持。

## 本地驗證

驗證方法與程式回歸範圍依 test-strategy「依變更選擇驗證」及「Commit 前收尾檢查與重開路徑」。只有新變更、失敗或證據失效時重跑；live CLI 僅跑本次受影響案例，依輸入與能力契約決定，不為湊數重跑其他平台。帳號受阻仍記 blocked。

`run_verify.py --reuse --run-id <id> [--sub-task <n>] --cmd '<本地指令>'` 明確請求重用。只使用同 run、同指令、同驗證輸入與環境的成功結果；失敗不重用。live 模型執行不可走本地快取；遠端／實際環境的操作證據重用邊界依 test-strategy「依變更選擇驗證」。強制重新執行時省略 `--reuse`。

新快照 `inputs-v2` 以檔案內容、mode、symlink 為準；忽略清單以 `verification_snapshot.py` 為唯一來源。純說明文件不觸發功能重驗，流程 skills、測試、程式與設定保持在驗證輸入中。既有 `inputs-v1` 與 legacy 快照沿用舊語義，不把既有結果靜默換成新格式。

指令執行期間輸入有變化，不記可重用的成功快照；修復後重新執行。記錄 `elapsed_seconds`、`reused` 與原始證據來源，快取命中也要留下憑據。提交 gate 仍核對最後成功證據與目前驗證輸入。

## 恢復與修正的剩餘工作

恢復中斷工作或開始修正前，主 flow 先對照現場證據，列出未完成 DoD、未解失敗，以及已完成且仍有效的證據；後續只處理剩餘工作。每次重驗先記錄具體理由，只因驗證輸入／實質行為改變、失敗、證據失效或具名疑點，重跑受影響驗證。item 切換、階段切換或恢復本身不構成重驗理由；有效證據沿用與提交快照仍依上節，不降低 gate。

適用且有效的 mutation 證據不因 item、階段或恢復而重做；抽樣、失敗後不能外推、不同 writer 的例外與停止條件，依 test-strategy「Mutation self-check」與 code-writer 新增測試檔自檢規則。新增或修改被測行為／斷言使證據失效時，仍須完成受影響的自檢。

按鈕定位等 UI 操作困難，依 test-strategy 的前端實機驗證邊界處理；已確認的資料或程式行為錯誤（例如帶入新資料後仍提交舊明細）仍須修復並取得必要行為驗證，不能用 UI best-effort 略過，也不能把執行紀錄中的「豁免」當作使用者授權。
