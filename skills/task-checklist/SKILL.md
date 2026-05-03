---
name: task-checklist
description: 任務描述的 4 大審查範疇（清楚程度、拆分必要性、技術限制、風險邊界）
user-invocable: false
---

# 任務描述審查 Checklist

## 1. 清楚程度 (Clarity)
- 任務目的是否明確？讀者能否在 30 秒內理解「要做什麼」與「為什麼」
- 是否有含糊詞彙（「優化一下」、「改善 UI」、「處理 bug」）而缺乏具體描述
- 輸入、輸出、影響範圍（檔案、模組、API）是否點出
- 是否有明確的驗收標準（Definition of Done）

## 2. 拆分必要性 (Decomposition)
- 任務是否太大，應拆成多個子任務（一般來說單一任務應能在半天～一天內完成）
- 是否混合了多個獨立關注點（例如：同時改 DB schema、API、前端 UI）
- 是否有可平行化的子任務（應標註 [P]）
- 拆分後的子任務之間依賴關係是否清楚

## 3. 技術限制與前置條件 (Technical Constraints)
- 是否牽涉到 DB migration？是否符合 CLAUDE.md 的資料庫規則（IF NOT EXISTS、不可損毀既有資料）
- 是否需要新套件、新環境變數、新權限設定
- 是否有既有程式碼或架構限制
- 是否需要考慮部署影響（本地測試、build 驗證、smoke test）
- 是否牽涉敏感資料或安全性議題

## 4. 風險與邊界 (Risks & Edge Cases)
- 是否提到重要的邊界條件或錯誤處理
- 是否有資料遷移風險、向後相容性問題
- 是否可能影響現有功能（regression 風險）
