# 風險分析報告：Tier 2 [P] item worktree 並行

> run_id: `2026-07-25-tier2-p-worktree`
> Spec: `spec/2026-07-25-tier2-p-worktree.md`
> 本報告自足可讀，不依賴對話上下文。分析對象是一個「流程框架變更」run（prose skill／agent 定義＋少量 hook 調整），非典型應用功能。

## 1. 技術風險 (Technical Risk)：🟡 中等

- **🟡 未實戰地基上疊複合層**：parallel-run 的 worktree＋rolling merge 機制至今未實戰（memory 記錄），本 Spec 把它變成 Tier 2 fan-out 的底層。兩層未驗證邏輯同時上線，出錯時難分辨是底層還是新層。
  → 對策：D3 已明示「一起上、共同硬化」是使用者知情決定；設計上 A′ 讓 fan-out 在機械層面**就是** parallel-run（不是類似），驗證一份機制兩處受惠；首次實戰 run 由主 session 前景盯場（比照 parallel-run memory 的「首次並行盯 hook 與 Bash 批准」注意事項）。
- **🟡 fan-out 編排是 prose 驅動、無 hook 強制**：門檻判定（≥2 且各 ≥150 行）、prep／fan-out 切批、子 manifest 產生都由主 session 依 skill 文字執行，判錯（如把 depends item 誤入 fan-out）hook 不會攔。
  → 對策：skill 寫成機械可查的檢核步驟（比照 parallel-run 前置 2 的兩兩比對）；子 run 內既有 gate 照常兜底（disjoint 破壞會在 merge 機械檢查②實際交集重驗被抓）。
- 🟢 git worktree 本身是成熟原生機制，無第三方相依。

## 2. 安全風險 (Security Risk)：🟢 無風險

- 不處理使用者輸入、不涉及驗證／授權、不接觸敏感資料、無新環境變數。改動對象是本 repo 的流程 prose 與 hook script。

## 3. 資料風險 (Data Risk)：🟡 中等

- 無 DB、無 migration。「資料」在本 run 指**流程狀態檔**（manifest 家族、各 worktree 的 eval_state、BUGLOG 條目）。
- **🟡 BUGLOG 延遲 append 的遺失窗口**：沿用 parallel-run 的「條目隨回報帶回、merge 後統一 append」——子 run 完成到主 session append 之間若 session 死掉，條目只活在回報訊息裡。
  → 對策：沿用 parallel-run 既有規則不加劇（該窗口是已接受的設計）；批次中斷恢復時把「已 merge 但 BUGLOG 未 append」列入機械重建檢查項（子 manifest 已 merge 而 BUGLOG 無對應條目 → 補問）。
- **🟡 `parent_run_id` 新欄位的向後相容**：hook／stats 讀舊 manifest（無此欄）不可炸。
  → 對策：欄位設計為可選，無此欄視同無父 run（比照 `scout_report_path` 舊欄相容慣例）；hook 若增相容性檢查須帶測試。
- 🟢 孤兒 worktree：run failed 時原地凍結是既有設計（parallel-run 條 10），`git worktree list` 可機械盤點，無靜默遺失。

## 4. 效能風險 (Performance Risk)：🟢 輕微

- worktree 開銷（~200-500ms＋磁碟＋每支 10-20% 編排稅）已由 D2 門檻明確界定為「只在划算時付」；並行支數受 `[P]` item 數與 agent 併發上限自然封頂。無 N+1／鎖定／規模成長疑慮。

## 5. 部署風險 (Deployment Risk)：🟡 中等

- **🟡 觸及 hook gate（框架自身的強制層）**：`eval_gates.py` 等若需調整（`parent_run_id` 相容），改壞的兩個方向都危險——誤擋（所有 commit 被攔死）或誤放（gate 靜默失效、綠燈不再是證據）。這是本 run 判 Tier 2 的主因。
  → 對策：A′ 設計已把 hook 改動壓到接近零（子 run 走現行 gate 原樣）；任何 hook 改動必附測試（DoD 4）；部署前跑 `doctor.py` 健檢＋全套測試 baseline（DoD 6）。
- **🟡 自我修改：本 run 改的是自己正在跑的流程**：eval-flow skill 改完即生效，本 run 後半段會踩到自己改過的規則。
  → 對策：本 run **自身序列跑、不觸發自己的 fan-out**（新機制的首次執行留給下一個真實 Tier 2 需求）；比照 memory 慣例「部署外層前先收外層 in_progress run、清孤兒 agent」。
- 🟢 純本地 repo 變更，無遠端部署、無 downtime、rollback＝git revert。

## 6. 業務與維護風險 (Business & Maintenance Risk)：🟡 中等

- **🟡 三 skill＋兩 agent 的 prose 一致性**：eval-flow／parallel-run／task-decomposition 與 task-verifier／code-reviewer 互相引用，改動後任何殘留舊描述（如 `[P]` 共用樹段沒清乾淨）都是接手者的地雷。
  → 對策：DoD 5 已明列一致性驗收；分拆時把「舊段落清除」列為明確 item DoD，用 grep 驗證無殘留關鍵句。
- 🟢 「一功能一族 run」改變審計習慣（多 manifest、多 commit）：D1／D4 使用者已知情接受，`parent_run_id`＋trailer 維持可反查。
- 🟢 file-scoped diff 的同檔跨 sub_task 邊界：已在 Spec 4.3 明文標註為已知限制與 prompt 級處置，非隱藏債。

## 總結

| 面向 | 等級 |
|---|---|
| 技術 | 🟡 |
| 安全 | 🟢 無風險 |
| 資料 | 🟡 |
| 效能 | 🟢 |
| 部署 | 🟡 |
| 業務維護 | 🟡 |

**無 🔴 重大風險**——可進入前置 1.5／2。四個 🟡（未實戰地基、prose 編排無 hook 強制、狀態檔相容／BUGLOG 窗口、hook 改動與自我修改）於分拆 task 時帶入對應 item 備註，由 code-writer 實作時注意。
