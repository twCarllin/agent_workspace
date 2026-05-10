---
name: task-risk-analysis
description: 任務多面向風險分析框架（技術、安全、資料、效能、部署、業務維護），用於 task 執行前的風險審視
user-invocable: false
---

# 多面向風險分析 Checklist

任務在執行前，必須從以下 6 個面向逐一思考，每個面向若有風險須明確指出，並標註嚴重等級（🔴 重大 / 🟡 中等 / 🟢 輕微）。

## 1. 技術風險 (Technical Risk)
- 是否使用了團隊不熟悉的技術、套件或框架
- 第三方相依（套件、API、服務）是否穩定、是否有 breaking change 風險
- 實作複雜度是否與任務價值匹配（避免 over-engineering）
- 是否有循環相依、架構耦合的疑慮

## 2. 安全風險 (Security Risk)
- 是否處理使用者輸入？是否有 SQL injection、XSS、CSRF 風險
- 是否涉及驗證 / 授權邏輯變更
- 是否會接觸敏感資料（密碼、token、PII）；是否有外洩、log 誤錄的疑慮
- 新增的環境變數、API key 是否有安全管理機制

## 3. 資料風險 (Data Risk)
- 是否涉及 DB schema 變更（migration）；是否符合 CLAUDE.md 的資料庫規則
- 是否有資料遺失、截斷、型別不相容的風險
- 是否有資料一致性問題（多表更新、跨服務資料同步）
- migration 是否冪等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS）；是否可 rollback

## 4. 效能風險 (Performance Risk)
- 是否會造成 N+1 查詢、全表掃描、大量資料載入
- 是否引入同步阻塞操作或長時間鎖定
- 在資料規模成長後是否仍可運作（scalability）
- 是否需要新增 index、cache 或 batch 處理

## 5. 部署風險 (Deployment Risk)
- 是否需要特定的部署順序（先 DB → 再後端 → 再前端）
- 是否會造成 downtime；是否有 zero-downtime 部署策略
- 是否需要相依服務同步更新（前後端契約變更）
- 是否有 rollback 計畫；rollback 後資料是否仍一致
- 是否符合「禁止未經本地測試直接部署」的部署規則

## 6. 業務與維護風險 (Business & Maintenance Risk)
- 是否會影響既有功能（regression 風險）
- 是否有向後相容性問題（API 簽章、資料格式變更）
- 變更是否會增加技術債或讓未來維護更困難
- 對使用者是否有可見影響（行為變更、UI 改動）；是否需要溝通或文件更新

## 輸出原則

- **有風險 → 標註等級並提出對應對策**：例如「🔴 此 migration 會修改既有欄位型別 → 應拆成新增新欄位 + 資料搬移 + 移除舊欄位三步」
- **🔴 重大風險未解決前不可進入執行階段**，必須回頭修改 task 描述、補上前置條件或拆分子任務
- **🟡 中等風險** 須在 task.md 中明確記錄，由執行者在實作時注意
- **🟢 輕微風險** 可作為 review 時的提醒
- **無風險面向也要明確標註「無風險」**，避免遺漏思考
