開始工作前，必須讀取並遵守 `.agent-flow/WORK_RULES.md`。

<!-- agent-workspace claude instructions -->
## Eval Flow

Read `.agent-flow/HARNESS.md`, `.agent-flow/CLAUDE_ADAPTER.md`, and `.agent-flow/PRACTICES.md`.
For implementation, read `.agent-flow/ROUTER.md`, then load only the selected `.agents/skills/<name>/SKILL.md`. Diagnose bugs before routing; use eval-flow-resume for an interrupted run.
Tier 0 follows `.agent-flow/ROUTER.md`: complete applicable verification, confirm classification, record the Tier 0 log, stage only this change, and commit directly; do not push automatically.
For Tier 1/2 only: New Tier 1/2 manifests use `harness: "claude"` and `evidence_schema: 2`. Keep actual verification evidence and independent review evidence when required. Run the final verification with `python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd "<project test command>"`; prepare, commit with Run-Id, then finalize with run_commit.py.
Use the matching role, with goal, context, constraints, and done conditions. Respect project instructions and current session permissions.
<!-- /agent-workspace claude instructions -->
