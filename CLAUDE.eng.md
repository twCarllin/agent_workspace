# CLAUDE.md

## Deployment Rules (Highest Priority)

- **Forbidden** to deploy directly to remote without local testing first
- Any code change must be verified locally before commit and deploy

## Eval Flow

**This flow uses model: claude-sonnet-4-6**.
When there is a new task:

### Preflight: Multi-dimensional Risk Analysis (must be completed before the first `code-writer` invocation)

- Use the **task-risk-analysis** skill to think through task risks across 6 dimensions (technical, security, data, performance, deployment, business maintenance), one by one
- Each dimension must be explicitly labeled: 🔴 critical / 🟡 moderate / 🟢 minor / no risk
- Produce a "Risk Analysis Report" containing: the judgment for each dimension, risk description, and corresponding countermeasure
- **Decision rules**:
  - If any 🔴 critical risk exists → **must not enter step 1**. The task.md must be modified first (add preconditions / split subtasks / clarify description), then re-analyze until no 🔴 remains
  - 🟡 moderate risk → must be clearly recorded in task.md so that `code-writer` is aware of it during implementation
  - 🟢 minor / no risk → may proceed directly to step 1
- The risk analysis result must be attached to the corresponding sub_task's `risk_analysis` field in `eval_state.json`

Then execute the following loop (each round's result is written to `eval_state.json`):

1. Call the `code-writer` subagent to produce code
2. `git add` the changed files into the staging area (so `code-reviewer` / `eval-scorer` can read them via `git diff --cached`)
3. Call the `code-reviewer` subagent to review and parse 🔴 critical issues
   - If 🔴 exists: fix according to suggestions (or call `code-writer`), then `git add` again and call `code-reviewer` to verify
4. Once 🔴 is cleared, call the `task-verifier` subagent to confirm feature completeness
   - Compare task.md vs the actual diff (subtasks completed, DoD met, no scope drift)
   - If gaps are found, fix them and return to step 3
5. Call the `eval-scorer` subagent to score independently (reads `git diff --cached`); append the result to `eval_state.json`

### Subagent Invocation Principles (Save Tokens)

- When **code-reviewer / task-verifier / eval-scorer** need to read code changes, **the prompt must instruct them to use `git diff --cached`** (Bash tool); do NOT use Read to load full files one by one. `git diff` only returns the changed portion, consuming far fewer tokens than reading entire files.
- **When auto-mode is ON**: these 3 agents may run in the background (`run_in_background: true`); Bash will be auto-approved.
- **When auto-mode is OFF**: these 3 agents must run in the foreground so the user can approve Bash permissions. Do NOT run them in the background (background agents cannot trigger permission prompts, which causes Bash to be denied).
- For agents that don't need Bash, such as **retro / task-reviewer**: they can be run in the background at any time.

6. Evaluate the score:
   - **score >= 6** → git commit, clear `eval_state.json`, finish
   - **score < 6 and rounds < 2** → generate an improvement brief based on the scoring report, return to step 1
   - **score < 6 and rounds == 2** → read `eval_state.json`, generate a full report, and report back to the user
7. **Conditionally** call the `retro` subagent:
   - If `code-reviewer` reported 🔴 critical issues → call retro before commit (after fixes)
   - If score < threshold (multiple improvement rounds needed) → call retro before final commit
   - If `code-reviewer` had no 🔴 and the score passed in one shot → **do NOT call retro** (no retrospective needed)

### eval_state.json Format

```json
{
  "task_id": "short task description",
  "threshold": 6,
  "sub_tasks": [
    {
      "id": 1,
      "name": "subtask name",
      "status": "passed | failed | in_progress",
      "warning": false,
      "risk_analysis": {
        "technical": "🟢 no risk | 🟡 ... | 🔴 ...",
        "security": "...",
        "data": "...",
        "performance": "...",
        "deployment": "...",
        "business_maintenance": "...",
        "blocking": false
      },
      "rounds": [
        {
          "round": 1,
          "quality_score": 0,
          "dimensions": {
            "Clarity": 0,
            "Completeness": 0,
            "Testability": 0,
            "Non-functional": 0,
            "Technical_constraints": 0
          },
          "deduction_reasons": [
            {
              "points_lost": 1,
              "dimension": "Completeness",
              "reason": "missing handling of boundary condition X",
              "evidence": "src/foo.ts:42"
            }
          ],
          "brief_sent_to_writer": "improvement summary (filled when score < threshold)"
        }
      ]
    }
  ],
  "status": "in_progress | completed | failed"
}
```

### eval_state.json Operation Rules

- **When starting a task**: create `eval_state.json` and fill in `task_id` and the `sub_tasks` structure
- **After risk analysis is complete**: fill the 6-dimension results into the corresponding sub_task's `risk_analysis`; if any 🔴 exists, set `blocking: true` — the task must be fixed and re-analyzed
- **After each scoring round**: append the `eval-scorer` result to the corresponding sub_task's `rounds` array
- **When quality_score < 10 (even if it passes the threshold)**: the round's `deduction_reasons` array must list every deduction reason
  - Each entry must contain `points_lost` (points deducted), `dimension` (which dimension was deducted), `reason` (specific reason), and `evidence` (file:line or evidence)
  - The sum of all `points_lost` must equal `10 - quality_score` (e.g., 8 points → total deductions = 2)
  - When score = 10, `deduction_reasons` is an empty array `[]`
- **When score < threshold**: fill in `brief_sent_to_writer` for that round with the improvement summary
- **When a sub_task passes**: set that sub_task's `status` to `"passed"`
- **When a sub_task fails after 2 rounds**: set `status` to `"failed"` and `warning` to `true`
- **When all subtasks complete and pass**: set the top-level `status` to `"completed"`; clear the file after commit
- **If any subtask is failed**: set the top-level `status` to `"failed"` and report back to the user

## Task Principle

- Task files are placed under the `task/` folder, named by date: `task/YYYY-MM-DD.md`
- Each time a task is added or read, use **today's date** as the filename (e.g., `task/2026-04-18.md`)
- The old `task.md` is kept only as a historical record; do not add new tasks to it
- Call subagents to complete tasks
- Mark the creation time of each task
- Tasks that can be parallelized should be marked with [P]
- Once a task is completed, mark it as [x]
- **After new tasks are added to a task file, you must call the `task-reviewer` subagent to review them**, confirming descriptions are clear, the breakdown is reasonable, and technical constraints are noted, before execution begins
- **After all subtasks of a task are completed, you must call the `task-verifier` subagent to verify** that the implementation matches the description, before commit

## Subagent Principle

- After work is completed, if the task came from a task file, mark the task as complete in the corresponding task file once eval-scoring is done

## Deployment Preparation

- Before deployment, check potential risks and inform the user; only deploy after confirmation
- Before deployment, check the impact of any DB-related operations; only deploy after confirmation
