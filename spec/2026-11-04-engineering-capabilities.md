# 工程能力補強

來源：使用者批准既有計畫：「好，按照這個計畫幫我執行吧」。計畫範圍與裁決由主 flow 派工紀錄提供。

## 交付契約

1. 七能力：系統理解、原因調查、設計比較、影響分析、實作、對抗驗證、經驗結構修正。system-investigator 提供理解及原因兩模式；新增 design-architect、adversarial-verifier；補強 impact-analyzer、code-writer、retro。各定義觸發、輸入、輸出、權限、停止與證據。
2. Tier 0 由主 flow 執行；Tier 1 按具體疑點派工；Tier 2 必須處理理解、設計和影響，但不固定派七個角色。接入 Router、三 tier、安裝器和兩 harness 設定，沿用相應既有模型政策。
3. 控制 token：主 flow 保留決策摘要與證據位置；writer 只收本次契約相關約束與定位；不複製完整對話。調查有效時重用；修正 session 有效時續用；必要時才比較多方案。
4. 修復 dispatch 越界判斷：既有 dirty 範圍外檔案被子程序再次修改須偵測；未碰的既有 dirty 檔案不得誤報。以真實子程序回歸。
5. 沿用 evals 執行能力行為與功能、bug、重複事故、恢復整合案例；包含真實資料流、失效歷史理由、設計契約、跨程序消費端、dirty 重用，分別驗有缺陷與合法案例的漏報及誤報。舊失敗須攔截，合法情況須通過。
6. 保存版本、模型、提示、權限及實測證據，量測可靠性、主 flow／writer／全 agent token 和派工修正耗時；無資料標未知。有限次 live 實測並明列限制，不假造基準或通過。驗目前 CLI 原生 hook smoke。
7. 相關行為有證據、獨立審查和完整相關測試通過；限制與未知明示。

## 既有事實

- 越界比較只以路徑集合差判斷，既有 dirty 路徑再次變更不會出現在差集（.agent-flow/scripts/dispatch.py:285）。
- 本 repo 的共用角色來源與模型配置分別位於 .agent-flow/roles/ 與 .agent-flow/harnesses/models.json（.agent-flow/HARNESS.md:7）。
- 原生 hook 是否受信任須依執行證據確認（.agent-flow/CODEX_ADAPTER.md:11）。

## 舊契約轉換

- dispatch 舊契約只回報派工後新出現的範圍外 dirty 路徑；新契約回報派工期間狀態或內容改變的範圍外路徑。原本已 dirty 且未變的路徑仍不回報；允許範圍內不回報。非 Git 或無法取得狀態維持原 fail-open 行為。`tests/test_dispatch.py::test_b1_to_b4_out_of_scope_detection` 的 B4 未被碰觸既有 dirty 檔斷言仍有效，不作廢；現有測試不作廢，補真實子程序再次覆寫既有 dirty 檔案例。
- 舊 Tier 2 對系統理解、設計及影響不設共同必做內容；新契約要求主 flow 完成並保留決策摘要及證據位置，按需要派角色。Tier 0 與 Tier 1 保持既有分級與授權，新增方法依問題觸發；既有測試若明確斷言 Tier 2 無此三項要求，須依新契約更新，無作廢測試已確認。
- 快照偽代碼：在子程序前及後收集 Git dirty 路徑、各路徑索引狀態及工作樹內容／類型；比較兩次值，取不同的路徑並排除允許清單；狀態不可讀時保留現有未知語義。不得把不變的 dirty 路徑計作越界。rename 的來源與目標維持可識別；任一可觀察索引或工作樹改動都需報告。

## 方法來源與選用

參考 https://github.com/cursor/plugins/tree/main/pstack/skills ：how 追執行路徑；why 區分歷史證據與推論；architect 先定使用契約與邊界；arena 以相同標準比較候選；blast-radius 追跨邊界消費端並實證關鍵安全前提；interrogate 對真實程式重現反例；correct 將重複錯誤先尋求結構約束，再考慮測試及文件。這些方法依本專案問題及 token 預算按需使用，不沿用其固定多模型派工或模型設定。

## 評測計畫與停止條件

七項能力各設植入可重現缺陷及容易誤判的乾淨合法案例。成功條件是觀察到正確行為與可核對的實際證據：缺陷案例指出並驗證具體錯誤，合法案例不虛報；重要來源不存在則標未知，不以章節或關鍵字出現判定品質。涵蓋功能、bug、重複事故及恢復四項整合；評分器先用已知有缺陷及合法產物測漏報／誤報。保存完整 prompt、環境、版本、模型與權限。

預算：每種 live 情境先各跑一次（四個整合情境，最多四次），每次 timeout 120 秒；另做一個原生 hook blocked smoke，若因權限無法觸發 hook，最多再以本 session 已授權 edits 模式重跑一次。除非為診斷已觀察的失敗，不追加 live 次數；不支援美元上限的 Codex 明記成本未知。一次樣本不足估計穩定可靠性，只報觀察結果，資料不足者標未知。主 flow token 無來源記未知，不聲稱總用量下降。

6.4 的真實續用需先建立 thread，再以同一 ID 恢復；若由該評測 fixture 執行，額外最多兩次有界 CLI 呼叫（各逾時不超過 40 秒），同一情境只執行一輪。這是實證續用所需的最小增量；實際呼叫數及未知成本均須留痕。拒絕或逾時記未知，不視為通過。

## 評測歷史資料修正

verification fixture 的首次版本在同一提交中讓 producer 輸出 `total_cents`、consumer 讀 `total`，但 checker 把舊理由推為兩者曾共用 `total`；實際歷史不足以支持該判定。依使用者裁示，建立可查的兩段歷史：先由 producer 與 consumer 共用 `total`，再遷移 producer 為 `total_cents`，保留舊 consumer。checker 以指定歷史版本與實際程式結果核對，而非由提交標題猜測。原始 live FAIL 留存，這項修正不改使用者行為契約。
