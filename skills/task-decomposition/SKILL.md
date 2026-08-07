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

上限是為了讓每個 item 的 `git diff --cached` 小到 code-reviewer 能一次讀完審完。**300 行是「新增 + 修改」的總和，不含自動生成的 lockfile / migration 樣板。**

**測試要求（Tier 2 硬性）**：每個引入新行為的**實作 item**，DoD 必須綁定該 item 的單元測試——測試與實作同 item、同 writer、同 diff（介面知識最熱的時候寫測試，行為驗證的程式碼直接落成測試，不寫 throwaway harness）。每個 task 尾端保留一個**整合測試 item**，只做跨 item 的整合層驗證＋ mutation self-check（見 test-strategy skill），不塞單元測試。DoD 沒綁測試的新行為 item、或整合測試 item 膨脹成單元測試大雜燴，交付前自檢不通過即重拆。這讓循環 step 5 的本地測試 gate 有測試可跑，且測試品質風險分散在各 item，不集中在最後一個 writer 身上（Tier 1 不經本 skill，維持可用實際運行驗證）。測試類 item（含各實作 item 的單元測試與整合測試 item）的 DoD 另附兩條硬要求：**fixture 逐區塊附 producer 行號依據**（fixture 的每個資料區塊須以註解標明「依據 &lt;producer 檔:行&gt;」，證明與 producer 實際輸出對齊，防漂移後消費路徑零覆蓋且全綠）；**fixture 為測試實際載入的 single source**（不得另存一份測試不讀的副本）。交付前自檢不符即重拆。

**行為契約表（DoD 的測試依據，Tier 2 硬性）**：每個引入新行為的實作 item，DoD 須附「輸入 → 預期可觀察效果」對照表——2~4 條核心行為＋**至少 1 條邊界輸入**。**邊界的機械判準：與核心行為走不同回傳／副作用分支的輸入**（不同 error code、提前 return、不同 side effect；典型如空值、特殊字元、越界值——實測：mine 子命令的 3 條 🔴 全藏在怪檔名輸入裡）。「可觀察效果」＝回傳值＋副作用（DB 寫入、檔案、對外呼叫），**不含內部實作細節**。此表是 writer 寫測試的唯一依據，**且同時是測試量的上限與下限（測試預算）**：每條 row 至少一處完整斷言（下限）、**表外測試預設不寫**（上限）——writer 認為該測而表沒有 → 建議補表、表補上才寫（既有補表機制），不先寫再說。測試的量在規劃時由表決定，不由 writer 的盡責本能決定——這是「寫 test 太貴」的源頭治理：超寫的測試 writer 要花 token 寫、reviewer 要花 token 審、紅了要花輪次仲裁、日後行為變更還要陪葬。此表也是測試失敗時的仲裁基準（判「code 錯還是測試錯」**以 DoD 中的行為契約表為準**，與 code-writer 測試管轄規則的 DoD 仲裁同義）。表未涵蓋但應測的邊界 → 回頭補進表再測（表可增補，single source 不變）；本規則禁止的是繞過表、對實作細節或未定義行為做臆測性斷言。契約表由拆分者（另一顆腦）從情境報告推導，不是 writer 對需求的自我詮釋——這是「自產自證」變「他證」的關鍵。

**功能移除的測試三分法（行為作廢專用，測試同步段的極端型）**：需求是**刪除既有功能**時，被刪行為的測試不是「要不要更新」而是「怎麼分流」。拆分時（Tier 2 由拆分者、Tier 1 由主 flow）以 grep 盤出斷言被刪行為的所有測試，逐一按**主題**機械分類：
- **A 主題＝被刪行為**（測試名／契約 row 直接指涉它，如「gate 失敗擋渲染」）→ **隨功能刪**（刪檔／刪函式），依據＝Spec 的作廢行為清單，不算「改弱測試」。
- **B 主題是存活行為、只順帶斷言被刪行為**（如 resume 整合測試順帶檢查 gate 狀態）→ **只拔被刪行為的斷言行，主題斷言保留**——這批是手術安全網，證明刪除沒切到旁邊器官，禁止整檔陪葬。
- **C 無關** → 不動。
分類清單寫進對應 item 的 DoD（writer 交付時列「刪了哪些／拔了哪幾行」供審）；**空轉檢查**：若 A 類刪完導致某存活模組零測試覆蓋 → 回報使用者，不得讓 step 5 靠「沒東西可失敗」假綠通過。此類需求（大改既有測試）**不進並行／fan-out**（沿既有規則）。附註：A 類大量存在通常代表舊測試違反「斷言去重／寬鬆檢查」——刪功能付的這筆是歷史債，新測試在測試預算規則下不會再擴散。

**測試同步段（有意的行為變更專用）**：需求含**有意改變既有行為**時，Spec／spec_inline 須明列「作廢舊行為清單」（舊契約 → 新契約對照）。**拆分者負責核對**：情境報告／Spec 隱含既有行為被改而未列清單 → 回頭要求補清單再拆（比照契約表的他證原則），不可照單續拆。拆分時以 `python3 .claude/hooks/test_baseline.py related --files <受影響檔>` 預算受影響的既有測試，在**對應實作 item 內標註「測試同步段」**（不是獨立 item——見下時序理由）：實作 writer 交付後、該 item 的 **step 2（git add）之前**，由主 flow 另派**快 model** 依對照表機械批次更新舊測試斷言，同步後的測試**與 writer 產出一併 staged**——step 3 的 code-reviewer 才審得到測試變更（「測試變更需有依據 → 🔴」防線在此執行：逐條核對測試改動能否對映到對照表 row，對映不上 → 🔴）；實作 writer 仍不碰舊測試（管轄分離、成本分離都保留），step 5 於 review∥verify 通過後照常跑——此時 code 與測試都已斷言新契約，check 才不會死結。**時序理由（不變量）**：行為變更的舊測試失敗不在 baseline，check 是確定性 script、不讀 DoD 散文，任何「先過 gate 再同步」或「先同步再實作」的排序都會讓某一方的 check 必紅——唯一無死結的位置是同一 item 內、check 之前。測試同步段的 `local_test_evidence` **逐條列「改動的測試檔 ＋ 對應對照表 row」**（滿足 test-strategy「測試過時」三項留痕：改了哪個測試＝檔名、舊斷言為何不再成立＝舊契約 row、依據＝清單本身）。

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
| 該 item 的單元測試 | **契約表 row 數 × 10–20 行**（行為數驅動，非實作行數驅動） | **併入該 item 估算**（測試隨實作，見上「測試要求」）；獨立成 item 的只有整合測試。舊「實作 0.5–1 倍」估法作廢——它把測試預算綁在實作行數上，變相鼓勵灌測試（200 行實作若只有 3 條 row，測試就該是 ~30–60 行，不是 100–200 行） |

**校準（實測教訓）：** 上表是「邏輯骨架」的量級，實際 diff 還有 docstring、錯誤路徑、常數表——實測顯示 naive 粗估**系統性低估 2–3 倍**。申報行數 = 表列量級估出的數 **×2**。寧可高估觸發再拆，不可低估躲 300 行上限（低估會讓軟上限形同虛設）。×2 校準後的數字**同時餵兩個判斷**：≥150 行觸發 worktree fan-out（`[P]` 門檻下限）、>300 行觸發再拆（上限）——兩者並存不衝突，一個數字各自對到對應閾值。

**估算捷徑：** item 觸及的檔案數 × 每檔平均行數（含測試檔）。觸及 **>3 個檔案**，幾乎必然超標或職責過雜 → 拆。

**檢驗問題：** 如果現在就開一個 code-writer 去寫這個 item，產出的 `git diff` 會不會超過一個螢幕能審完的量？會 → 拆。

---

## Step 3：判斷 item 拆分方向

單一 item 超標時，依序嘗試以下切法（由上而下優先）。**注意：單元測試不是切割線**——把測試從實作 item 抽走會讓新行為裸奔到整合階段，測試要跟著它驗證的實作一起走：

1. **分層** — 同一情境的 backend / frontend / DB 拆成不同 item（各自帶各自的測試，也順便解鎖平行化）。
2. **職責 / 函式群** — 一個 service 裡多個獨立函式群 → 各自成 item。
3. **happy-path vs 邊界** — 先把正常流程做成一個 item，錯誤處理 / 重試 / 併發保護做成另一個 item。
4. **CRUD 拆讀寫** — Create/Update（有副作用、需驗證）與 Read（查詢、序列化）拆開。

task 超過 5 個 item 時，依序：功能切片 → 分層 → 前置基礎抽離。

---

## 寬幅重構例外（expand–contract，唯一不縱切的拆法）

**適用判準（三者全中才適用）**：同一個**機械式變更**（改名、retype 共用符號、換欄位）＋ 爆炸半徑**跨全庫**（一動就破壞大量呼叫端）＋ **任何縱切片都無法獨綠**（單片改完必留紅燈給下一片）。滿足時不硬拆 tracer-bullet 縱切，改**三段序列**：

1. **expand** — 新形式加在舊形式**旁邊**（新名稱、新欄位、新簽名並存），零呼叫端破壞。一個 item。
2. **migrate** — 呼叫端**按爆炸半徑分批**遷移到新形式（per 套件／per 目錄），每批一個 item、`depends` expand 批；舊形式仍在，**批批之間 step 5 check 保持綠**。
3. **contract** — `grep` 確認舊形式**零呼叫端殘留**後刪除舊形式。一個 item，`depends` 全部 migrate 批。

與 Tier 0 機械式改動例外的分界：Tier 0 例外（CLAUDE.md 分級表）管每檔 ≤50 行、可一次直改完的機械變更；超出該量級（一次改不完、改了必紅）→ 進本節的分批序列。

---

## Step 4：標註平行化與依賴

- **`[P]` 可平行化**的條件（兩者都要成立）：
  - 不共用檔案（無 merge 衝突面）
  - 無資料依賴（不需要另一個 item 的產出當輸入）
- 有依賴的 item 明確標 `depends: <item id>`。前置基礎 task（DB schema / 共用型別）幾乎都是其他 item 的依賴，不可標 `[P]`。
- **frontier 排程規則（供下游主 flow 排程，僅管循序執行）**：item 的可開工判準是「其 `depends` 全部完成」，**不是編號順序**——當前所有可開工 item 的集合即 **frontier**，循序執行時主 flow 從 frontier 取工即可，編號只是識別不是序（depends 已全部完成的 item，不必等編號在前的無關 item）。`depends` 與 `[P]` 的分工：`depends` 描述依賴圖的**邊**（誰擋誰），`[P]` 描述無依賴 item 間**可同時派工**（無檔案交集、無資料依賴——即上述兩條件）。**既有互斥規則不變**：標 `depends` 的 item 不標 `[P]`——fan-out 的 prep 段以此判進循序段（見 `eval-flow` skill「Tier 2 [P] fan-out」；worktree 隔離下，依賴未落地的 item 進不了並行批）。

**worktree fan-out 門檻（供下游主 flow 判斷）**：標 `[P]` 的 item，當**≥2 個且各自估計 ≥150 行**（以本檔 `~<行數>行` 欄的 ×2 校準值為準）時，主 flow 於 Tier 2 執行時各開 git worktree 並行（見 `eval-flow` skill「Tier 2 [P] fan-out」節）；不足此門檻則 `[P]` 退回主 worktree 循序執行。估計不準時保守處理——估不準即不 fan-out。

**檢驗問題：** 兩個標 `[P]` 的 item，同時派兩個 code-writer 去寫，合併時會不會撞到同一個檔案？會 → 不是 `[P]`。

---

## 輸出格式（寫入 `task/YYYY-MM-DD.md`）

```
# Task — <Spec 名稱>  (created: YYYY-MM-DD HH:MM)

## Task 1: <對映的使用情境名稱>
- 依賴: 無
- [ ] 1.1 <item 描述＋單元測試>  ~<估計行數（含測試、已 ×2 校準）>行  files: <實作路徑>, tests/...
      DoD: <可驗收條件>  情境: <usage 報告中的情境 id>
      契約: <輸入> → <可觀察效果>；<輸入> → <效果>；[邊界] <怪輸入> → <效果>
- [ ] 1.2 [P] <item 描述＋單元測試>  ~<行數>行  files: <路徑>, tests/...
      DoD: ...  情境: ...
- [ ] 1.3 整合測試（跨 item）＋ mutation self-check  ~<行數>行  files: tests/...
      DoD: <整合層涵蓋哪些情境；sabotage 哪些行為點須 FAIL>

## Task 2: <另一個情境>  depends: Task 1
- [ ] 2.1 ...
```

- item 完成後標 `[x]`
- 每個 item 必含四要素：**估計行數、影響檔案、DoD、對映情境**。缺任一 → 交付前自檢不通過即重拆

---

## 反模式（要 reject 重拆的分拆）

- item 沒有估計行數，或估計明顯灌水以躲過 300 行上限（含未套 ×2 校準的系統性低估）
- 引入新行為的實作 item，DoD 沒綁該 item 的單元測試（測試被推遲到整合階段，新行為裸奔）
- 引入新行為的實作 item 無行為契約表，或契約表全是 happy path（無邊界輸入）、或寫的是實作細節而非可觀察效果
- 有意的行為變更卻無「作廢舊行為清單」或實作 item 未標測試同步段——舊測試更新散進 writer 的迭代迴圈，逐輪踩雷、貴 model 做機械替換
- 整合測試 item 塞滿單元測試——單一 writer 一次寫 60+ 個測試，假測試與覆蓋缺口的風險全集中在這裡（單元測試住在各實作 item，整合 item 只做跨 item 驗證＋ mutation self-check）
- 一個 item 觸及 >3 個檔案還宣稱 <300 行
- task 塞滿 5 個 item 只為了不開新 task（湊數，不是內聚）
- item 描述是「實作 X 功能」這種無邊界的整包，無法對映單一情境或 DoD
- 把邊界 / 異常處理整包吞進 happy-path item，讓 diff 爆量
- 標 `[P]` 但兩個 item 共用檔案或有資料依賴
- 前置基礎（schema / 共用 client）沒抽出來，導致多個 item 重複定義
- 寬幅重構硬拆縱切片——同一機械變更炸全庫時，每個縱切片都必然留紅燈，該走 expand–contract 序列而非 tracer-bullet
- 無 expand 緩衝的一次性大爆炸替換——舊形式直接改掉、全庫呼叫端同一個 item 內硬遷，diff 爆量且 step 5 中途無綠可守
- fixture 手寫、無 producer 行號依據（與 producer 漂移後消費路徑零覆蓋且全綠——此根因已四度現形，retro 散文擋不住）
- fixture 存在測試實際不載入的副本（single source 破功——改了副本、測試仍讀舊值，對齊證明形同虛設）

---

## 範例：Spec「廠商付款申請單新增部分沖銷」

**使用情境報告（節錄）：** 情境 A 財務對一張已核准申請單登記部分付款；情境 B 系統依已沖銷金額更新未結餘額；情境 C 沖銷金額 > 未結餘額時擋下並提示。

**分拆結果：**

```
## Task 1: 部分沖銷資料模型與餘額計算  (情境 B 的基礎)
- 依賴: 無
- [ ] 1.1 新增 settlement 資料表 + migration ＋ model 層測試  ~180行  files: models/settlement.py, migrations/, tests/test_settlement_model.py
      DoD: 表建立、外鍵指向 payment_request；測試涵蓋建立與外鍵約束  情境: B
- [ ] 1.2 未結餘額計算函式（申請額 − Σ已沖銷）＋單元測試  ~200行  files: services/balance.py, tests/test_balance.py
      DoD: 多筆部分沖銷加總正確；測試涵蓋零沖銷 / 多筆 / 全額三種  情境: B

## Task 2: 部分沖銷登記 API  depends: Task 1
- [ ] 2.1 POST /settlements endpoint + 驗證＋單元測試  ~280行  files: routes/settlement.py, tests/test_settlement_api.py
      DoD: 成功登記回 201、寫入 settlement 表；測試涵蓋成功與欄位驗證失敗  情境: A
- [ ] 2.2 超額沖銷防呆（金額 > 未結餘額 → 422）＋單元測試  ~140行  files: routes/settlement.py, tests/test_settlement_api.py
      DoD: 超額回 422 + 錯誤訊息  情境: C
      契約: 金額=餘額 → 201、餘額歸零；金額>餘額 → 422、settlement 表無寫入；[邊界] 金額=0 → 422（不產生空沖銷）
- [ ] 2.3 整合測試（登記 → 餘額更新 → 超額被擋全流程）＋ mutation self-check  ~150行  files: tests/test_settlement_integration.py
      DoD: 情境 A→B→C 全流程串通過；sabotage 餘額計算與防呆條件各一處，對應測試須 FAIL  情境: A, B, C
```

兩個 task、共 5 個 item，皆 ≤300 行（估算含測試、已 ×2 校準）；單元測試隨各實作 item，整合測試收尾；情境 B 的基礎抽成 Task 1 供 Task 2 依賴。
