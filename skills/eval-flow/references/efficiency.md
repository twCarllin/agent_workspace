# 增量審查與驗證重用

首輪仍獨立審完整 task。以下只減少重複工作，不改變驗收、HITL、修正輪數上限與失敗阻擋。

## 增量重審

主 flow 在派首輪 reviewer 前，用 `review_delta.py capture --checkpoint run/<id>.review.json --files <task檔案> --contracts <Spec及task檔>` 保存 index 與契約雜湊。reviewer 完成後，index 與契約未變才用 `review_delta.py reviewed --checkpoint <同檔> --session <真實reviewer session>` 標記已審。此標記只證明該版本已看過，不表示通過。

修正重審用 `review_delta.py diff --checkpoint <同檔> --files <同範圍> --contracts <同契約>`。`mode=delta` 時提供前次已審版本到目前 index 的差異；仍附契約全文、未解問題、先前完成度與新增測試證據，reviewer 可讀相關上下文與呼叫端。範圍／契約變更、checkpoint 缺失或失效則 `mode=full`，回到該 task 的完整 staged diff，不能因 fallback 省略首輪。

delta 為空不代表通過：有未解問題或缺少前次結論時不能自動放行。重審通過後的證據只適用該次 index；獨立性、引文核實與完成度檢查保持。

## 本地驗證

Tier 2 實作期間使用 test-strategy 的累積相關測試；最後一次才跑完整回歸。只有新變更、失敗或證據失效時重跑；live CLI 僅跑本次受影響案例，依輸入與能力契約決定，不為湊數重跑其他平台。帳號受阻仍記 blocked。

`run_verify.py --reuse --run-id <id> [--sub-task <n>] --cmd '<本地指令>'` 明確請求重用。只使用同 run、同指令、同驗證輸入與環境的成功結果；失敗不重用。live 模型執行不可走本地快取。強制重新執行時省略 `--reuse`。

新快照 `inputs-v1` 以檔案內容、mode、symlink 為準；忽略清單以 `verification_snapshot.py` 為唯一來源。純說明文件不觸發功能重驗，流程 skills、測試、程式與設定保持在驗證輸入中。舊快照沿用舊語義，不把既有結果靜默換成新格式。

指令執行期間輸入有變化，不記可重用的成功快照；修復後重新執行。記錄 `elapsed_seconds`、`reused` 與原始證據來源，快取命中也要留下憑據。提交 gate 仍核對最後成功證據與目前驗證輸入。
