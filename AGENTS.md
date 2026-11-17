向使用者回報時，用 ASD-STE100 簡化技術的中文。

## 工作範圍

- 只實作明確需求，以及完成需求所必需的修改。修改前，確認：「若不修改，哪項需求或驗收條件無法成立？」若無法指出，不得納入本次工作。
- 額外發現的問題，簡短記錄問題、觸發條件與影響，繼續完成原任務。不要直接修正，也不要為不影響本次完成的問題中斷工作要求決策。
- 時間尚遠、目前未觸發的失敗，不自動構成擴大範圍的理由；是否修改，依它與本次需求的關係判斷。
- 完成前檢查 diff，移除本次新增且無需求依據的修改，包括整理、抽象化、防禦邏輯與未來相容性修改。保留使用者及其他工作的既有變更。

## 專案

這是 Eval Flow 模板。共用核心在 `.agent-flow/`，skill 來源在 `skills/`，專案載入入口在 `.agents/skills/`。
安裝：`./init.sh --harness both --target <專案路徑>`。
驗證：`python3 -m unittest discover -s tests`。修改 Python 腳本須檢查相容入口與真實子程序路徑。
完成條件：相關行為有證據、適用的獨立審查或主 flow 自查完成、gate 通過；回報變更、驗證與限制。

<!-- agent-workspace codex instructions -->
## Eval Flow

For implementation, read `.agent-flow/ROUTER.md` and load the selected `.agents/skills/<name>/SKILL.md`. Diagnose bugs first; resume interrupted runs with eval-flow-resume. Pure questions do not start a run.
New Tier 1/2 manifests use `harness: "codex"` and `evidence_schema: 2`.
Use the selected skill for verification, review, and completion. Read `.agent-flow/CODEX_ADAPTER.md` for Codex-specific operations. Preserve project instructions and current session permissions.
<!-- /agent-workspace codex instructions -->
