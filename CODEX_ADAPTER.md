# Codex adapter for Eval Flow

The installed `.agent-flow/ROUTER.md` and `.agents/skills/` contain the shared process. This file defines how Codex executes instructions that name Claude Code facilities.

| Flow term | Codex execution |
|---|---|
| `CLAUDE.md` Router | `.agent-flow/ROUTER.md` |
| `skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` |
| `.claude/agents/<role>.md` | `.codex/agents/<role>.toml` |
| Claude `Task` / `Agent` | `python3 .claude/hooks/dispatch.py <role> --prompt-file <path> --backend codex` (runs `codex exec`); `.codex/agents/<role>.toml` supplies the model, reasoning effort and developer instructions. With manifest `harness: "codex"` the backend is selected automatically |
| `.claude/settings.json` gate | `.codex/hooks.json` `PreToolUse` gate |
| `CLAUDE_PROJECT_DIR` | The hook resolves the Git root from Codex's `cwd` |

The core Python scripts stay in `.claude/hooks/` because both platforms call the same state and gate code. The Git `commit-msg` hook validates the final commit message even when it came from `-F` or an editor. If the project already has a `commit-msg` hook or `core.hooksPath`, the installer preserves it and prints the integration step; add a call to `.claude/hooks/commit_message_gate.py "$1"` before relying on commit gating.

For Tier 1 and Tier 2, set `harness: "codex"` and `evidence_schema: 2` in the new manifest. Run the final full test command through `run_verify.py --run-id <run_id> --cmd "<command>"` so the commit gate can compare the source tree snapshot. Finish with `run_commit.py prepare <run_id>`, `git commit`, then `run_commit.py finalize <run_id>`. On resume, a `ready_to_commit` run with a matching HEAD trailer needs only `finalize`.

Codex subagents inherit permissions from their parent. Claude instructions about `run_in_background`, Claude Bash approvals, and `Agent isolation: "worktree"` do not apply. For parallel work, use independent Git worktrees and launch a Codex session in each worktree after installing this adapter there. Follow the `parallel-run` skill's dependency and merge order. If each worktree cannot have its own manifest, staging area, and active hooks, execute the items sequentially in one worktree.

`dispatch.py` checks the report envelope in-process for both backends (exit 2 on a blocking defect). The Claude `PostToolUse` envelope hook only covers the `Agent` tool path; a parent agent that still uses a Codex custom agent directly must check the required report sections and `Self-check:` line itself. Per-dispatch token counts are recorded in `run/<run_id>.dispatch.jsonl` for both backends; the main Codex session's usage remains `unknown_codex` because the transcript format is not a stable metering interface for this script. Do not convert unknown usage into zero.

Codex project hooks require review and trust in `/hooks` before they execute. Tool hooks cover supported local tool paths; the Git hook also applies to ordinary terminal commits. For a protected branch, rerun repository validation in CI.
