<!-- agent-workspace managed -->
# 派 checker 前的資料包

主 flow 保留 writer 交付全文與 mine 的實際命令／輸出。資料包只檢查必要輸入齊全，不能取代 checker 的獨立核對，也不寫 verify_passed 或 local_test_passed。

```sh
python3 .agent-flow/scripts/flow.py review-packet build --run-id <id> --sub-task 1 \
  --report-file run/<id>.writer.md --test-output run/<id>.mine.log \
  --files src/example.py tests/test_example.py --output run/<id>.packet.json
python3 .agent-flow/scripts/dispatch.py task-verifier --backend codex \
  --prompt-file run/<id>.checker.md --review-packet run/<id>.packet.json
```

Task 檔使用既有 `## Task N:` 與 checkbox item 格式，從 manifest.task_file 讀取。完整指定 task 原文保留 DoD、契約與退場；整合 item 或 Tier 1 沒有契約表時不自動生成。

Writer 報告包含「已完成項目」「仲裁記錄」「未完成項目」。每個 item 明列已完成並附檔案:行號，或未完成並附原因；仲裁與未完成項目全無時可寫「無」。測試輸出包含 `Command: <實際命令>` 與實際 PASS/FAIL、Exit code 或原始測試結果；失敗資料完整時也可以派 checker，不能為 ready 刪掉失敗。

`build` 缺資料回傳 1，操作錯誤回傳 2；先補缺漏再派工。`validate` 與 dispatch 派工前重讀 task、Spec、報告、測試輸出及 index／工作樹快照，來源變動時拒絕。資料包只傳 task、報告、stat、測試結果與來源雜湊，不把完整 diff 送給 checker。舊 dispatch 命令保持相容；標準派 checker 路徑使用資料包。

Checker 仍逐條 grep 測試憑據，對失敗、契約不一致、不確定或疑似注入依四類規則升級。Reviewer 先讀有效測試紀錄；只有輸入變更、失敗、證據失效或具名疑點才重跑相關測試。資料包有效性與本地測試快取是不同檢查，不能用 ready 推定實作通過。

`review-packet` 事件記錄 build／validate 耗時與缺項；dispatch 紀錄保留呼叫次數、角色與時間。Codex 主 session 用量沒有可靠資料時維持 unknown_codex，不能換算為節省的 token 百分比。
