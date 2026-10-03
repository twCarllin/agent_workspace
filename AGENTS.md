向使用者回報時，用 ASD-STE100 簡化技術的中文。

## 專案

這是 Eval Flow 模板。共用核心在 `.agent-flow/`，skill 來源在 `skills/`，專案載入入口在 `.agents/skills/`。
安裝：`./init.sh --harness both --target <專案路徑>`。
驗證：`python3 -m unittest discover -s tests`。修改 Python 腳本須檢查相容入口與真實子程序路徑。
完成條件：相關行為有證據、独立審查完成、gate 通過；回報變更、驗證與限制。

<!-- agent-workspace codex instructions -->
## Eval Flow

Read `.agent-flow/HARNESS.md`, `.agent-flow/CODEX_ADAPTER.md`, and `.agent-flow/PRACTICES.md`.
For implementation, read `.agent-flow/ROUTER.md`, then load only the selected `.agents/skills/<name>/SKILL.md`. Diagnose bugs before routing; use eval-flow-resume for an interrupted run.
New Tier 1/2 manifests use `harness: "codex"` and `evidence_schema: 2`. Keep independent review and test evidence. Run the final verification with `python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd "<project test command>"`; prepare, commit with Run-Id, then finalize with run_commit.py.
Use the matching role, with goal, context, constraints, and done conditions. Respect project instructions and current session permissions.
<!-- /agent-workspace codex instructions -->
