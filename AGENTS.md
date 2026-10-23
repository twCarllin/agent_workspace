向使用者回報時，用 ASD-STE100 簡化技術的中文。

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
