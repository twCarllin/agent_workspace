# CLAUDE.md

## Definitions

- **auto-mode**: when Claude Code runs with `--dangerously-skip-permissions` or `--enable-auto-mode`(where Bash commands are auto-approved without human-in-the-loop confirmation). When the mode is unclear, assume auto-mode is **OFF**.

## Deployment Rules (Highest Priority)

- **Forbidden** to deploy directly to remote without local testing first
- Any code change must be verified locally before commit and deploy
- Before deploying, confirm the build succeeds
- Deployment commands are only executed when the user explicitly requests it

## Database Operation Principles

- Use an isolated test database for testing; do not touch dev or prod data

## Eval Flow

**This flow uses model: claude-sonnet-4-6**.
When I request review + fix, execute the following loop (each round's result is written to `eval_state.json`). The score threshold and the inner-loop iteration cap are read from `eval_state.json` — they are **not hardcoded** in this document.

1. Call the `code-writer` subagent to produce code
2. `git add` the changed files into the staging area (so `code-reviewer` / `eval-scorer` can read them via `git diff --cached`)
3. Call the `code-reviewer` subagent to review, and parse 🔴 critical issues
   - If 🔴 exists: fix according to suggestions (or call `code-writer`), then `git add` again and call `code-reviewer` to verify.
   - **Inner-loop guard**: increment `review_iterations` each time `code-reviewer` is invoked in this round. If it exceeds `max_review_iterations` (default 3) without 🔴 clearing, **stop the eval flow**, write the current state to `eval_state.json`, and escalate to the user with the outstanding 🔴 list.
4. Once 🔴 is cleared, call the `task-verifier` subagent to confirm feature completeness against the current subtask
   - Compare task.md vs actual diff (current subtask completed, DoD met, no scope drift)
   - **If gaps are found, return to step 1** with the gap list as an additional brief — *not* step 3 — so the new code goes through the full review chain again. Record the gaps in `task_verifier_gaps`.
5. Call the `eval-scorer` subagent to score independently (reads `git diff --cached`); append the result to `eval_state.json`

### Subagent Invocation Principles (Save Tokens)

- When **code-reviewer / task-verifier / eval-scorer** need to read code changes, **the prompt must instruct them to use `git diff --cached`** (Bash tool); do NOT use Read to load full files one by one. `git diff` only returns the changed portion, consuming far fewer tokens than reading entire files.
- **When auto-mode is ON**: these 3 agents may run in the background (`run_in_background: true`); Bash will be auto-approved.
- **When auto-mode is OFF**: these 3 agents must run in the foreground so the user can approve Bash permissions. Do NOT run them in the background (background agents cannot trigger permission prompts, which causes Bash to be denied).
- For agents that don't need Bash, such as **retro / task-reviewer**: they can be run in the background at any time.

6. Evaluate the score:
   - **score >= threshold** → git commit, clear `eval_state.json`, finish
   - **score < threshold and rounds < 2** → generate an improvement brief based on the scoring report, return to step 1
   - **score < threshold and rounds == 2** → read `eval_state.json`, generate a full report, and report back to the user
7. **Conditionally** call the `retro` subagent:
   - If `code-reviewer` reported 🔴 critical issues at any point → call retro before commit (after fixes). Set `retro_triggered: true`.
   - If score < threshold in any round (multiple improvement rounds needed) → call retro before final commit. Set `retro_triggered: true`.
   - If `code-reviewer` had no 🔴 and the score passed in one shot → **do NOT call retro** (no retrospective needed).

### eval_state.json Format

```json
{
  "task_id": "short task description",
  "threshold": 6,
  "max_review_iterations": 3,
  "sub_tasks": [
    {
      "id": 1,
      "name": "subtask name",
      "status": "passed | failed | in_progress",
      "warning": false,
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
          "review_iterations": 0,
          "critical_issues_found": [],
          "task_verifier_gaps": [],
          "retro_triggered": false,
          "brief_sent_to_writer": "improvement summary (filled when score < threshold)"
        }
      ]
    }
  ],
  "status": "in_progress | completed | failed"
}
```

### eval_state.json Operation Rules

- **When starting a task**: create `eval_state.json` and fill in `task_id`, `threshold`, `max_review_iterations`, and the `sub_tasks` structure
- **After each scoring round**: append the `eval-scorer` result to the corresponding sub_task's `rounds` array, including `review_iterations`, `critical_issues_found`, `task_verifier_gaps`, and `retro_triggered`
- **When the inner review loop hits the cap**: append the partial round with `quality_score: null` and the outstanding 🔴 list in `critical_issues_found`, then halt
- **When score < threshold**: fill in `brief_sent_to_writer` for that round with the improvement summary
- **When a sub_task passes**: set that sub_task's `status` to `"passed"`
- **When a sub_task fails after 2 rounds**: set `status` to `"failed"` and `warning` to `true`
- **When all subtasks complete and pass**: set the top-level `status` to `"completed"`; clear the file after commit
- **If any subtask is failed**: set the top-level `status` to `"failed"` and report back to the user

## Task Principles

- Task files are placed under the `task/` folder, named by the file's **creation date**: `task/YYYY-MM-DD.md`
- When adding a new task, append to today's file (e.g., `task/2026-04-18.md`); create the file if it doesn't exist
- **A task stays in its original file for its entire lifecycle**, even if it spans multiple days. Do not move tasks between files when they're completed late.
- The old `task.md` is kept only as a historical record; do not add new tasks to it
- Call subagents to complete tasks
- Mark the creation time of each task
- Tasks that can be parallelized should be marked with [P]
- Once a task is completed, mark it as [x]
- **After new tasks are added, you must call the `task-reviewer` subagent to review them**, confirming descriptions are clear, the breakdown is reasonable, and technical constraints are noted, before execution begins
- Per-subtask verification is handled by `task-verifier` **inside Eval Flow step 4**. No separate end-of-task `task-verifier` call is required — the eval loop already covers it.

## Subagent Principles

- After work is completed, if the task came from a task file, mark the task as complete in the corresponding task file once eval-scoring is done

## Deployment Preparation

- Before deployment, check potential risks and inform the user; only deploy after confirmation
- Before deployment, check the impact of any DB-related operations; only deploy after confirmation
