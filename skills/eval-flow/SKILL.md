---
name: eval-flow
description: Tier 1／2 實作流程。新 Tier 1 依授權開始、自選方法與驗證，有具體問題才獨立審查或 HITL；Tier 2 與舊 run 走完整循環。Router 判為 Tier 1／2、「跑 Eval Flow」或「照流程實作」時載入；Tier 0 與非實作問答不適用。
---

# Eval Flow（Tier 1／2 執行細節）

本入口保留共用控制與步驟導覽。**開始當前階段前，必須完整讀取該階段的必讀文件**；不得只讀標題或以摘要代替規則。只載入目前階段，不預設讀所有 references。同階段文件已完整讀取且規則仍在 context 時沿用；context 遺失或文件變更才重載。標 `（R-NNN）` 的規則修改前，先讀 `retro/RETRO.md` 對應條目。寫流程文件時查 `references/glossary.md`；執行 run 不需載入術語表。

## 路徑選擇

新 Tier 1／2 manifest 記目前 `harness` 與 `evidence_schema: 2`。新 adaptive Tier 1 直接讀 `references/tier1.md`；Tier 2、舊 run、跨 harness 操作才讀 `.agent-flow/HARNESS.md`。實際產碼、派工或品質爭議才讀 `.agent-flow/PRACTICES.md` 的適用節。派工輸入含目標、背景、限制與完成條件。

| Router 判定 | 必讀文件與時機 |
|---|---|
| Tier 1 | 初始化前必讀 [Tier 1 路徑](references/tier1.md)，依政策開始與交付 |
| Tier 2 | 初始化前必讀 [Tier 2 前置](references/tier2-prep.md)，依原順序完成前置與 HITL gate 後進循環 |
| Tier B／Hotfix／併發／[P] fan-out | 進入適用特殊路徑前必讀 [特殊路徑](references/rare-paths.md) |

## 共用：進場檢查（全 tier，執行任何步驟之前）

- **進場檢查（建 manifest 之前）**：跑 `git status --porcelain`。非空時先判定本次修改範圍；能保留既有變更且歸屬明確時直接繼續，將隔離方式記在 manifest `dirty_tree_ruling`。只有歸屬衝突或必須覆寫既有變更時才問使用者。乾淨樹免記。

初次先執行 `flow.py preflight --harness <目前 harness>` 檢查環境；manifest 已存在時才加 `--run-id <id>`；未知項目不能當成已通過。新 adaptive Tier 1 初始化與收尾依 `references/tier1.md` 的命令路徑；Tier 2、舊 run 或需手動操作狀態欄位時才讀「資料格式與操作規則」。

## Tier 1 精簡路徑

初始化與寫 code 前必讀 [Tier 1 路徑](references/tier1.md)，依 manifest 政策選新路徑或舊 run 相容路徑。

## Tier 2 完整路徑

前置開始前必讀 [Tier 2 前置](references/tier2-prep.md)。模型由 agent 定義承載，見下方「Model 指派原則」。

依前置文件順序完成；**HITL gate 未過不可進入循環**。前置完成後進入下方 Tier 2 與舊 Tier 1 的共用循環。

## 循環（Tier 2 與舊 Tier 1）

以下步驟適用 Tier 2 與舊 Tier 1；adaptive Tier 1 只在採用對應操作時讀該階段規則，不把完整 checklist 當成必跑流程。

循環發現第二根因時，先依 test-strategy「外部答案解析與第二根因」處置，再判斷下方升級逃生門是否適用。

> **循環中的升級逃生門（Tier 2 也適用）**：循環執行中若冒出 🔴 重大風險、或發現需求歧義（DoD 講不清、Spec 有洞）→ 中止循環，先修改 **Spec** 釐清範圍；若牽動使用情境或影響面，補派具名問題給 `usage-analyzer`／`impact-analyzer`；若影響拆分，重跑前置 1（分拆 task）。

開工前把這份 checklist 複製進回報，逐步打勾（每步細則依下方必讀導覽載入）：

```
- [ ] step 1: 派工 code-writer（gate: 知識前置＋契約前置）
- [ ] step 2: git add 進 staging（gate: file-scoped）
- [ ] step 3: 舊 Tier 1 派 checker；Tier 2 直接派 reviewer 審查（gate: 兩節缺一退件）
- [ ] step 4: 審查結果處置（gate: 引文核實）
- [ ] step 5: 本地測試驗證（gate: 依 test-strategy 選適用驗證；程式測試無新增穩定失敗）
- [ ] step 6: 收尾順序（gate: hook 強制）
- [ ] step 7: 有條件派 retro（gate: 僅升級輪）
```

| 目前步驟 | 執行前必讀 |
|---|---|
| step 1–2 | [實作與 staging](references/writing.md) |
| step 3–4 | [獨立檢核與處置](references/review.md)；step 3 派獨立審查前再讀 `.agent-flow/REVIEW_PACKET.md` |
| step 5–7 | [測試、收尾與回顧](references/testing-finish.md)；step 5 載入 test-strategy，step 6 讀 `.agent-flow/FLOW_CLI.md`「收尾」節 |

以上文件保留實際步驟 1–7 的單一規則枚舉。在本循環中不可因根入口僅有導覽而跳過適用的知識／契約前置、獨立審查、引文核實、四類升級、修正上限、step 5 與 commit gate。需要獨立審查時，**寫的人 ≠ 審的人**，資料包 ready 與快取命中均不代表審查通過。

## 派工機制（headless CLI；規則為單一枚舉點）

派工前必讀 [派工與證據控制](references/dispatch-control.md) 的「派工機制」與「Subagent 呼叫原則」節，使用角色契約與目前 session 已授權模式。修正／重取沿用原 session，越界與信封退件依原規則處置。

## Model 指派原則

模型設定或派工選擇時，必讀 [派工與證據控制](references/dispatch-control.md) 同名節；可執行設定的唯一來源是 `.agent-flow/harnesses/models.json`，不同平台不共用模型 ID。

## Subagent 呼叫原則（省 token）

派工前必讀 [派工與證據控制](references/dispatch-control.md) 同名節；不自行推定 auto-mode，也不因背景執行略過 HITL。

## 主 flow 憑據紀律（回報必附證據）

主 flow 的每句進度宣稱須同句附可驗證憑據；沒有憑據視為未發生。step 記意圖，憑據證明動作。sabotage／mutation／重現實驗先實跑取得輸出，再寫結果並同句附命令與輸出尾行；未跑只能寫待跑（R-013）。派工或爭議處置時才讀 [派工與證據控制](references/dispatch-control.md) 的完整紀律。

## 資料格式與操作規則

Tier 2、舊 run 或新 Tier 1 須手動操作狀態欄位時，讀 [資料格式](references/formats.md) 的適用節；派工時再讀 [派工與證據控制](references/dispatch-control.md)。一律用 `eval_state.py` helper，不手動 Edit 狀態；首輪 set-review 與 checked-by 按原規則記錄，不由資料包自填通過。新 Tier 1 的標準命令與順序在 `references/tier1.md`。

## Gate 的硬性執行（hook）

遭 gate 攔截時必讀 [Gate 規則](references/gates.md)。不能用快取或資料包繞過證據。

## 效率與驗證重用

修正重審或請求 `--reuse` 時，必讀 [增量審查與驗證重用](references/efficiency.md)。首輪仍完整獨立審查，過期證據不可重用。

## 中斷恢復（Resume）

中斷續跑時必讀 eval-flow-resume skill，按 manifest／eval_state 與實際憑據對賬，不靠記憶。ready_to_commit 核對實際 commit 後接續 finalize。

## 其他路徑

以下情況才讀 [特殊路徑](references/rare-paths.md)，不預載所有路徑。

## Tier B Bootstrap 路徑（骨架工作，無業務邏輯）

判需求為 Tier B（空專案或新模組純骨架、無業務邏輯）時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整路徑（Bootstrap 清單、精簡風險分析、選型 HITL、DoD 與收尾）。

## Hotfix 通道（先止血、後補債；債是硬性的）

使用者明確宣告緊急（線上事故／資損進行中）時，讀 `.agents/skills/eval-flow/references/rare-paths.md` 取得完整通道（止血、精簡溯源、commit、補債、欠帳 gate）。

## 單一 run 原則與併發（worktree 隔離）

需要併發或插單前，依「其他路徑」入口讀隔離與裁決規則。

## Tier 2 [P] fan-out（worktree 並行）

符合原門檻時，依「其他路徑」入口讀完整 fan-out 協定，不用背景旗標代替 worktree 隔離。
