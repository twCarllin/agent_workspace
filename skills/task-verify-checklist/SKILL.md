---
name: task-verify-checklist
description: 任務完成度驗證框架（子任務完成度、DoD 逐條比對、Scope 偏移檢查）
user-invocable: false
---

# 任務完成度驗證 Checklist

## 1. 子任務完成度 (Completion)
- task.md 中列出的每個 `[ ]` / `[x]` 子任務，逐一確認
- 對每個標記 `[x]` 的子任務，從 git diff 或檔案中找到對應的實作證據
- 對每個仍為 `[ ]` 的子任務，判斷是「刻意跳過」還是「遺漏」
- 特別注意「驗證」類子任務（build、test、grep 確認），確認有實際執行的證據

## 2. 驗收標準逐條比對 (Definition of Done)
- 讀取 task.md 的「驗收標準 (Definition of Done)」區塊
- 每一條標準都要有可驗證的證據（diff 中的程式碼、build 輸出、grep 結果）
- 若某條標準無法從 diff 中驗證（需要 UI 操作），標記為「需人工驗證」
- 若某條標準明確未達成，標記為「未通過」並說明缺少什麼

## 3. Scope 偏移檢查 (Scope Drift)
- 比對 git diff 的實際變更範圍 vs task.md 的「涉及檔案」清單
- 有沒有改到「涉及檔案」以外的檔案？（過度擴展）
- 有沒有「涉及檔案」清單中的檔案完全沒被改到？（遺漏）
- 檢查「不做的事」清單中的每一條，確認沒有被違反

## 4. 技術限制遵守 (Constraints Compliance)
- task.md 的「技術限制與風險」區塊中標註的限制，是否都被遵守
- 特別注意 🔴 和 🟡 標記的風險項目
- DB migration、API 變更等高影響操作是否符合 CLAUDE.md 規則
