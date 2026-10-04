# Flow efficiency

使用者確認實作前三項：增量重審、驗證結果按雜湊重用、Tier2分段驗證。

驗收：首次審完整task；重審可機械產生前次已審index到目前index的delta，保留跨檔上下文、契約與未解問題，baseline缺失/不可解析須full fallback，不得自行當已通過。相同run內相同指令、驗證輸入、環境的成功本地結果可明確--reuse；失敗、輸入/環境改變不得重用。快照使用實際內容、mode與symlink而非HEAD diff，純說明README.md/TODO.md/CHANGELOG.md與docs/*.md可排除；其他檔案含流程skill與設定均保留。舊schema2 snapshot仍能核對；新快照用明確kind避免改變舊語義。檢查執行前後輸入變動，變動不產生可重用證據。Tier2實作期間相關測試；提交前一次全套；live只受影響案例且不與本地快取混用。記elapsed/reused以檢查效果。

保留獨立審查、HITL、失敗阻擋、提交快照。ClaudeCLI延期，不改模型/權限。既有TODO.md與run/gate_hits.log、run/tier0.jsonl保留不提交。只改本地工具，不部署。
