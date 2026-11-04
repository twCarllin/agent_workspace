---
name: verification-recipe
description: 每專案一次建立真實入口驗證配方，產出憑據不進測試。
---

# 驗證配方（verify recipe）

## 目的

把「使用者會看到什麼」變成可重跑的證據。配方是一份操作說明，給之後沒看過本專案的 agent 冷讀；它不是測試，不進 test suite，不被 baseline 計數。

## 何時建立

- 專案有使用者入口（畫面、CLI、API）且可在本地啟動，而 `verify/` 下還沒有對應配方。
- 配方只建一次。之後的 run 只照配方的「操作」節跑，並補證據；入口或啟動方式變了才改配方。
- 不能本地啟動（無主控權、依賴外部環境）→ 不建配方；該入口的 item 交付用 `--observed-evidence pending-manual:<步驟>`。

## 建立步驟

1. **盤點**：讀 README、啟動腳本（`Makefile`／`package.json` scripts／`start-dev.sh`）、路由或指令註冊處。答四題：使用者從哪裡進；本地怎麼啟動；agent 怎麼操作（HTTP、CLI 參數、Playwright）；可觀察證據是什麼（回應原文、截圖、輸出檔、log 行）。
2. **寫配方** `verify/<app>.md`，五節固定：
   - **啟動**：一行指令、port、所需環境變數名稱（不寫值）。
   - **就緒檢查**：一個命令與預期輸出，確認可以開始操作。
   - **操作**：每個使用者入口一段，含真實參數或 selector；畫面入口用 Playwright（系統 Python 已有則直接用，沒有就列 pending-manual）。
   - **證據**：每段操作要留下什麼檔案或輸出，存到 `run/<run_id>.verify/`。
   - **清理**：停掉的程序、刪掉的暫存。
3. **實跑一次**：啟動 → 就緒檢查 → 跑一個入口 → 留證據 → 清理。任一步失敗就不算建立完成，不交付配方。
4. 配方與證據都不進版控：`verify/` 與 `run/` 由 harness 的 git exclude 管理，和其他開發工具檔一樣留在本地。

## 使用（每個 run）

- item 交付時：`--observed "<使用者會看到什麼>" --observed-evidence file:<證據路徑>` 或 `ran:<命令與結果摘要>`。
- 截圖類證據主 flow 要打開看一眼，再記自查；自動操作成功不等於人看得到。
- 不新增測試檔來取代配方；既有自動化功能測試照常是 step 5 硬 gate。

## 不做

- 不自建平行 runtime（port、DB、secret 手搭一套）。既有啟動把手起不來就 pending-manual。
- 不為配方寫單元測試。
- 不裝新的瀏覽器工具到專案內；使用者層級已有的才用。
