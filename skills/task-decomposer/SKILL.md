---
name: task-decomposition
version: 1.0
description: 依「使用情境報告」與 Spec，把工作拆成可執行、可平行、可驗收的 task 與 item，並強制拆分粒度（每 task ≤ 5 個 item、每 item ≤ 300 行 code）。觸發語：「把這個 Spec 拆成 task」、「分拆 task」、「這個功能怎麼拆」、「拆 sub_tasks」。不適用於：尚未產出使用情境報告前（先跑 usage-scenario-analysis）、單檔 ≤10 行的 UI 微調（走難易度分級直接改）。
---

# Task 分拆框架

> 本 skill 由 **`task-decomposer` subagent** 載入使用（Eval Flow 前置 3）。主 flow 不直接跑此 skill，而是委派該 agent，由 agent 涵蓋本 skill 作為指令內容。

**把 Spec 拆成「小到可以一次寫對、獨立可驗收」的單位。粒度失控是 eval flow 失敗與 scope 偏移的頭號成因。**

輸入：run manifest `run/<run_id>.json`（由 `eval_state.json.run_id` 定位）的 `usage_report_path`（已被使用者確認的**使用情境報告**）與 `spec_path`（**Spec**）。**一律從 manifest 讀路徑，不自行以日期 / 檔名重組**——`usage_report_path` 為 `null` 代表 usage 尚未完成，此時直接中止並回報。
輸出：`task/YYYY-MM-DD.md` 內的 task 清單，每個 task 展開為 ≤5 個 item，每個 item 對映一個使用情境、可獨立 `git diff` 審查。

---

## 硬性上限（違反即須再拆，不可協商）

| 層級 | 上限 | 超過時的動作 |
|---|---|---|
| **每個 task** | 最多 **5 個 item** | 拆成多個 task（通常沿功能切片或分層切） |
| **每個 item** | 預估最多 **300 行 code** | 拆成多個 item（沿檔案 / 職責 / happy-path vs 邊界切） |

上限是為了讓每個 item 的 `git diff --cached` 小到 code-reviewer / eval-scorer 能一次讀完並打準分。**300 行是「新增 + 修改」的總和，不含自動生成的 lockfile / migration 樣板。**

---

## Step 1：以使用情境為切割主軸

先把使用情境報告的每個情境列出來。**預設一個核心情境 → 一個 task**，因為情境天然對映「一段可獨立驗收的行為」。

- happy-path 情境 → 主 task
- 邊界 / 異常情境 → 若處理邏輯 <100 行，併入該情境的主 task 當獨立 item；若成體系（例如整套錯誤處理 / 重試 / 併發控制）→ 獨立 task
- 跨情境的共用基礎（DB schema、共用 client、型別定義）→ 抽成前置 task，標為其他 task 的依賴

**檢驗問題：** 這個 task 對應的使用情境，能不能在不碰其他情境的情況下 demo 給使用者看？不能 → 切割線畫錯了。

---

## Step 2：估算每個 item 的行數

在寫 code 前估行數，用「檔案 × 職責」的粗估法。以下為單一 item 的參考量級：

| 產出類型 | 粗估行數 | 備註 |
|---|---|---|
| 新增 DB model / migration | 30–80 | schema 複雜則獨立成 item |
| 新增 API endpoint（route + handler + validation） | 80–150 | 一個 endpoint 一個 item |
| 新增 service / 商業邏輯模組 | 100–250 | 超過 → 沿函式職責再拆 |
| 新增前端元件（表單 / 表格 / 互動） | 100–250 | 元件 + 狀態 + API 串接常超標，拆分層 |
| 設定 / wiring / DI 註冊 | 20–50 | 可併入相鄰 item |
| 該 item 的測試 | 另計 | **測試永遠是獨立 item**，不塞進實作 item |

**估算捷徑：** item 觸及的檔案數 × 每檔平均行數。觸及 **>3 個檔案**，幾乎必然超標或職責過雜 → 拆。

**檢驗問題：** 如果現在就開一個 code-writer 去寫這個 item，產出的 `git diff` 會不會超過一個螢幕能審完的量？會 → 拆。

---

## Step 3：判斷 item 拆分方向

單一 item 超標時，依序嘗試以下切法（由上而下優先）：

1. **測試 vs 實作** — 把測試抽成獨立 item。這是最常見、最乾淨的一刀。
2. **分層** — 同一情境的 backend / frontend / DB 拆成不同 item（也順便解鎖平行化）。
3. **職責 / 函式群** — 一個 service 裡多個獨立函式群 → 各自成 item。
4. **happy-path vs 邊界** — 先把正常流程做成一個 item，錯誤處理 / 重試 / 併發保護做成另一個 item。
5. **CRUD 拆讀寫** — Create/Update（有副作用、需驗證）與 Read（查詢、序列化）拆開。

task 超過 5 個 item 時，依序：功能切片 → 分層 → 前置基礎抽離。

---

## Step 4：標註平行化與依賴

- **`[P]` 可平行化**的條件（兩者都要成立）：
  - 不共用檔案（無 merge 衝突面）
  - 無資料依賴（不需要另一個 item 的產出當輸入）
- 有依賴的 item 明確標 `depends: <item id>`。前置基礎 task（DB schema / 共用型別）幾乎都是其他 item 的依賴，不可標 `[P]`。

**檢驗問題：** 兩個標 `[P]` 的 item，同時派兩個 code-writer 去寫，合併時會不會撞到同一個檔案？會 → 不是 `[P]`。

---

## 輸出格式（寫入 `task/YYYY-MM-DD.md`）

```
# Task — <Spec 名稱>  (created: YYYY-MM-DD HH:MM)

## Task 1: <對映的使用情境名稱>
- 依賴: 無
- [ ] 1.1 <item 描述>  ~<估計行數>行  files: <路徑>
      DoD: <可驗收條件>  情境: <usage 報告中的情境 id>
- [ ] 1.2 [P] <item 描述>  ~<行數>行  files: <路徑>
      DoD: ...  情境: ...
- [ ] 1.3 <item 的測試>  ~<行數>行  files: tests/...
      DoD: <測試涵蓋哪些情境>

## Task 2: <另一個情境>  depends: Task 1
- [ ] 2.1 ...
```

- item 完成後標 `[x]`
- 每個 item 必含四要素：**估計行數、影響檔案、DoD、對映情境**。缺任一 → task-reviewer 打回

---

## 反模式（要 reject 重拆的分拆）

- item 沒有估計行數，或估計明顯灌水以躲過 300 行上限
- 一個 item 同時包含實作 + 測試（測試必須獨立）
- 一個 item 觸及 >3 個檔案還宣稱 <300 行
- task 塞滿 5 個 item 只為了不開新 task（湊數，不是內聚）
- item 描述是「實作 X 功能」這種無邊界的整包，無法對映單一情境或 DoD
- 把邊界 / 異常處理整包吞進 happy-path item，讓 diff 爆量
- 標 `[P]` 但兩個 item 共用檔案或有資料依賴
- 前置基礎（schema / 共用 client）沒抽出來，導致多個 item 重複定義

---

## 範例：Spec「廠商付款申請單新增部分沖銷」

**使用情境報告（節錄）：** 情境 A 財務對一張已核准申請單登記部分付款；情境 B 系統依已沖銷金額更新未結餘額；情境 C 沖銷金額 > 未結餘額時擋下並提示。

**分拆結果：**

```
## Task 1: 部分沖銷資料模型與餘額計算  (情境 B 的基礎)
- 依賴: 無
- [ ] 1.1 新增 settlement 資料表 + migration  ~60行  files: models/settlement.py, migrations/
      DoD: 表建立、外鍵指向 payment_request  情境: B
- [ ] 1.2 未結餘額計算函式（申請額 − Σ已沖銷）  ~40行  files: services/balance.py
      DoD: 多筆部分沖銷加總正確  情境: B
- [ ] 1.3 [P] 餘額計算單元測試  ~80行  files: tests/test_balance.py
      DoD: 涵蓋零沖銷 / 多筆 / 全額三種  情境: B

## Task 2: 部分沖銷登記 API  depends: Task 1
- [ ] 2.1 POST /settlements endpoint + 驗證  ~120行  files: routes/settlement.py
      DoD: 成功登記回 201、寫入 settlement 表  情境: A
- [ ] 2.2 超額沖銷防呆（金額 > 未結餘額 → 422）  ~50行  files: routes/settlement.py
      DoD: 超額回 422 + 錯誤訊息  情境: C
- [ ] 2.3 [P] endpoint 整合測試  ~150行  files: tests/test_settlement_api.py
      DoD: 涵蓋情境 A 成功、C 被擋  情境: A, C
```

兩個 task、各 3 個 item，皆 ≤300 行，測試獨立，情境 B 的基礎抽成 Task 1 供 Task 2 依賴。

---

## 適用範圍

用於「已有使用者確認的使用情境報告 + Spec，要拆成可執行 sub_tasks」的場景。不適用：
- **尚未產出使用情境報告** — manifest 的 `usage_report_path` 為 `null` 時中止，先跑 `usage-scenario-analysis`，這個 skill 吃它的輸出
- **Tier 0（≤10 行微調）或 Tier 1（明確小功能）** — 不呼叫本 skill。Tier 0 直接改；Tier 1 直接建 task 檔（仍守 ≤5 items／各 ≤300 行的同一組上限，只是免正式分拆流程）
- 純除錯 / 單點修復（已知單一檔案單一函式）— 直接開一個 item 即可，不需整套分拆
