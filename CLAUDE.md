<!-- agent-workspace claude instructions -->
## Eval Flow

Read `.agent-flow/HARNESS.md`, `.agent-flow/CLAUDE_ADAPTER.md`, and `.agent-flow/PRACTICES.md`.
For implementation, read `.agent-flow/ROUTER.md`, then load only the selected `.agents/skills/<name>/SKILL.md`. Diagnose bugs before routing; use eval-flow-resume for an interrupted run.
New Tier 1/2 manifests use `harness: "claude"` and `evidence_schema: 2`. Keep independent review and test evidence. Run the final verification with `python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd "<project test command>"`; prepare, commit with Run-Id, then finalize with run_commit.py.
Use the matching role, with goal, context, constraints, and done conditions. Respect project instructions and current session permissions.
<!-- /agent-workspace claude instructions -->
