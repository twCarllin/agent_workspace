---
name: review-checklist
description: 程式碼審查的 5 大範疇 checklist（安全性、效能、邏輯、可維護性、測試覆蓋）
user-invocable: false
---

# 程式碼審查 Checklist

## 1. 安全性 (Security)
- SQL injection、XSS、CSRF 等常見漏洞
- 敏感資料（API key、密碼）是否硬編碼
- 輸入驗證與 sanitization
- 認證與授權邏輯是否正確

## 2. 效能 (Performance)
- 不必要的迴圈巢狀或 N+1 查詢
- 記憶體洩漏風險
- 可以快取但沒有快取的重複計算
- 不必要的同步阻塞操作

## 3. 邏輯正確性 (Correctness)
- 邊界條件（空值、空陣列、overflow）
- 錯誤處理是否完整
- 非同步邏輯的 race condition
- 業務邏輯是否符合需求描述

## 4. 可維護性 (Maintainability)
- 函數/類別的單一職責原則
- 命名是否清楚表達意圖
- 魔法數字、魔法字串是否應提取為常數
- 重複程式碼（DRY 原則）

## 5. 測試覆蓋 (Test Coverage)
- 是否缺少關鍵測試案例
- 測試是否測了實作細節而非行為
- Mock 使用是否合理
- 有沒有明顯 bug
