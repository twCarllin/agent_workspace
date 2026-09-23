<!-- agent-workspace codex instructions -->
## Eval Flow

For implementation requests, read `.agent-flow/ROUTER.md` before routing the task.
When the Router selects Tier 1, Tier 2, or B, load `.agents/skills/eval-flow/SKILL.md` and follow its state and evidence rules. For a bug, diagnose before routing; for an interrupted run, load `.agents/skills/eval-flow-resume/SKILL.md`.
Read `.agent-flow/CODEX_ADAPTER.md` whenever a flow instruction names Claude Code tools, agents, permissions, or worktree behavior.
For each new Codex run, set manifest `harness: "codex"` and `evidence_schema: 2` (Tier 1/2). Use `run_verify.py` for the final full-suite command. After commit, run `run_commit.py finalize <run_id>`.
Use the matching project Codex agents for delegated roles. Record a named question when asking an advisor. The user request and applicable higher-priority instructions take precedence over the workflow.
<!-- /agent-workspace codex instructions -->
