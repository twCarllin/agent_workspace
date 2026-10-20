# Tier 1 初始化與計畫確認

## Tier 1 精簡路徑

新 `init-run` 的 `tier1_policy: "adaptive-v1"` 走本節。主 flow 自選實作與驗證方法，
不預設派 writer 或 checker。沒有此欄的舊 run 走末節；Tier 2 仍走完整路徑。

### 適用判斷（單一枚舉點）

- **HITL**：只有業務事實或使用者偏好未明、授權不足、不可還原操作、需求有多種解讀等
  需要使用者決定的問題才提問。已有清楚需求與授權就開始，不把計畫回報當成第二次授權。
  權限、公開契約與其他 Router 邊界變更仍走 Tier 2；部署或對外操作仍須原有授權。
- **獨立審查**：驗證不能涵蓋主要行為、影響面不明、存在具名疑點，或使用者要求時，
  先用 `require-review --reason` 記錄原因，直接派 reviewer 核對完整 staged diff、DoD
  與實際證據。不先派 checker；原因只增不減，不因後續測試綠燈改回自查。
- **主 flow 自查**：需求明確、變更可還原、驗證涵蓋主要行為，且無獨立審查原因時使用。
  自查是執行者檢查，不宣稱獨立審查；不以欄位齊全代表需求已滿足。

1. **精簡初始化**：完成共用進場檢查與 Router 分級，執行 `init-run`；保存使用者需求、
   分級理由、驗證命令與 task 路徑。不建 `eval_state.json`。
   **intent gate（不可鬆）**：`spec_path` 與 `spec_inline` 至少一個非空。
2. **直接建 task 檔**：主 flow 記錄執行範圍與可驗 DoD；單一來源引用需求，不重述規格。
   維持 ≤2 tasks、合計 ≤8 items、每 task ≤5 items；超出或風險上升時依 Router 處理。
   既有測試足夠就沿用，不按 DoD 條數新增測試。功能移除的測試分流依 task-decomposition。
3. **依授權開始**：無待裁示問題時執行 `start-run <id> --authorization '<已授權需求>'`，
   記錄 `plan_recorded_at` 與 `plan_authorization`、凍結 item 清單並推進 decomposed。
   不填 `hitl_confirmed_at`，不宣稱使用者逐項確認過計畫。需要 HITL 時先取得裁示，
   再用 `hitl-confirm` 記錄；**無人看管的 session（headless）不得自行確認** HITL。
4. **主 flow 直寫捷徑**：主 flow 判斷直接實作或委派何者合適；需要乾淨 context 或明確
   模組分工時才派 writer。委派時完整投放適用契約與知識前置（R-011），檔案與權限範圍明列。
   主 flow 直寫同守 `.agent-flow/CODE_QUALITY.md`。`executor_notes` 可記有用的選擇理由，
   不為每個 item 產生固定格式的空白說明。
5. **驗證與交付**：只 stage 本次檔案，選足以覆蓋需求的測試或實際運行驗證，以
   `run_verify.py` 記實際結果。依適用判斷記自查或獨立結論，完成 item 對帳，再用
   `flow.py finish` 驗證及提交；用法與欄位依 `.agent-flow/FLOW_CLI.md`。
   自查由 `review-run --checked-by self --evidence '<完成度與驗證範圍>' --passed` 記錄；
   須已有目前來源的有效成功驗證且無審查原因。來源變更或測試失敗後不可沿用。
   自查不代表可以跳過測試、偽造結果、覆蓋他人變更或擴張外部授權。

### 舊 run 相容路徑

缺 `tier1_policy` 的舊 Tier 1 沿用原有開始與審查契約：建立 task 後取得輕量 HITL，
使用 `hitl-confirm` 推進 phase；四項憑據直接記 manifest，不建 `eval_state.json`。
實作／staging、checker 四類升級、測試與收尾依共用循環 step 1–7。信任邊界或公開契約
理由仍直派 reviewer；獨立審查結論由 `review-run` 記錄，不得用 `self`。
同一連貫變更的一輪可讀 diff 可合併審查；相依 items 沿用同一 writer。
不以新政策為既有確認、審查或 item 交付結果補造紀錄。
