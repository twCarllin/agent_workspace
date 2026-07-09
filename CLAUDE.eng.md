# CLAUDE.md

## Deployment Rules (Highest Priority)

- **Forbidden** to deploy directly to remote without local testing first
- Any code change must be verified locally before commit and deploy


## Difficulty Tiering (Router — the first step for every incoming request)

Determine the tier first, then decide which path to take. The axes are not "lines of code" but the three things the gates protect: **risk** (auth / payments / schema / deployment), **ambiguity** (is the requirement clear), and **size** (will it exceed 1 task).

| Tier | Entry conditions (**all** must hold) | Path |
|---|---|---|
| **0 Tweak** | ≤10 lines, single file, no new behavior (pure styling / copy / parameter change) | Change directly, create no files |
| **1 Well-defined feature** | Unambiguous requirement (DoD stateable in one sentence) + single usage path (single role, no branching scenarios) + estimated ≤1 task (≤5 items / ≤300 lines each) + **touches none of: auth/permissions, payments/transactions, DB schema changes, deployment/environment config** | Take the "Tier 1 Lightweight Path" |
| **2 Full feature** | Any of the above fails: ambiguous OR large OR multi-role/multi-scenario OR touches any high-risk area above | Take the full "Eval Flow (Tier 2)" |

- **Tier 0 commit ownership**: after a Tier 0 change, report what was changed and **do not commit on your own** (per global rules, the user decides when to commit)

### Anti-abuse Rules (prevent the agent from self-downgrading to save tokens)

- **High-risk areas are hard exclusions, not weighted factors**: touching any of auth/permissions, payments/transactions, schema changes, or deployment config **forces Tier 2**, with no discretion
- The Tier 1/2 decision must be written to the manifest as `tier` and `tier_rationale` (why this tier), for later audit
- **Upgrade escape hatch**: if any of the following occurs during Tier 1 execution → **abort and upgrade to Tier 2**, then backfill the missing preflights (produce a Spec, run usage analysis, run formal risk analysis):
  - Decomposition exceeds 5 items (hard limit)
  - An item is estimated to far exceed 300 lines and cannot reasonably fit within ≤5 items (in a Tier 1 context this means the feature isn't actually small and should take the full flow; this is not a demand to force-split)
  - Requirement ambiguity emerges (DoD unclear, multiple usage paths discovered)
  - A 🔴 risk emerges
- Upgrades are irreversible: once upgraded to Tier 2, never downgrade back to Tier 1


## Eval Flow (Tier 2 Full Path)

When the Router classifies a request as **Tier 2** (a full Spec to implement), execute this flow. **Models are not assigned at the flow level**; each agent decides per its task nature (see "Model Assignment Principles" below).

### Preflight 0: Initialization (entry point, must be the first action)

- Receive the **Spec** to implement in this run (source: the output of Stage A intent→spec, or a path manually specified by the user)
- Determine the `run_id`: `YYYY-MM-DD-<spec-slug>` (e.g., `2026-07-06-partial-settlement`), the correlation key linking all files of this run
- **Create the run manifest** `run/<run_id>.json` (**cold provenance file — committed to git alongside the code, never deleted**), filling in:
  - `run_id`, `created_at`
  - `spec_path`: the actual path to this Spec (the entry point **records** the Spec here)
  - `usage_report_path`, `task_file`: set to `null` for now
  - `status`: `"in_progress"`
- **Create `eval_state.json`** (**hot scoring scratchpad, cleared after commit**), filling in `run_id` (pointing back to the manifest), `threshold`, and empty `sub_tasks`
- **Gate (hard)**: until the manifest's `spec_path` is written, **do not enter Preflight 1 (risk analysis)**. A Spec that hasn't been recorded means the whole pipeline has no input source
- All subsequent steps locate `run/<run_id>.json` via `eval_state.json.run_id` and read `spec_path` / `usage_report_path` from the manifest — **never reconstruct dates / filenames**

### Preflight 1: Multi-dimensional Risk Analysis (must complete before the first code-writer invocation)

- Use the **task-risk-analysis** skill: read the Spec pointed to by the manifest's `spec_path` in `run/<run_id>.json`, and think through task risks across the 6 dimensions (technical, security, data, performance, deployment, business maintenance) one by one
- Each dimension must be explicitly labeled: 🔴 critical / 🟡 moderate / 🟢 minor / no risk
- Produce a "Risk Analysis Report" containing: the judgment for each dimension, risk description, and corresponding countermeasure
- **Decision rules**:
  - Any 🔴 critical risk → **must not enter any subsequent step (including usage scenario analysis)**. The **Spec** must be revised first (add preconditions / narrow scope / clarify descriptions), then re-analyzed until no 🔴 remains
  - 🟡 moderate risk → record it in the risk report, and carry it into the corresponding item's notes during "task decomposition" so code-writer is aware during implementation
  - 🟢 minor / no risk → proceed to the next step, "usage scenario analysis"
- The risk analysis report is first produced at the **Spec level**; after "task decomposition" completes and `sub_tasks` are created, map the corresponding risks into each sub_task's `risk_analysis` field in `eval_state.json`

### Preflight 2: Usage Scenario Analysis (must complete before task decomposition)

- Call the **`usage-analyzer` subagent**. It reads the Spec, produces the usage scenario report, and its own definition plus the `usage-scenario-analysis` skill govern the report contents, scenario ids, boundary inventory, and file location.
- **Flow-level gate**: the report requires **user confirmation**; do not enter Preflight 3 before confirmation (usage-analyzer writes back `manifest.usage_report_path` only after confirmation).

### Preflight 3: Task Decomposition (must complete before the first code-writer invocation)

- Call the **`task-decomposer` subagent**. It reads the usage report and Spec, splits the work into tasks and items, writes `task/YYYY-MM-DD.md`, writes back `manifest.task_file`, and hands off to `task-reviewer` for review. Decomposition granularity, limits, and the five required elements live in its definition and the `task-decomposition` skill.
- **Flow-level gate**: if `manifest.usage_report_path` is `null`, this step must not start (task-decomposer will self-abort).
- After task-decomposer delivers (including passing task-reviewer review), expand each task into `eval_state.json`'s `sub_tasks`, then enter the loop below.

Then execute the following loop (each round's result is written to `eval_state.json`):

> **Upgrade escape hatch inside the loop (also applies to Tier 2)**: if a 🔴 critical risk emerges during the loop, or requirement ambiguity is discovered (DoD unclear, holes in the Spec) → abort the loop, return to Preflight 1 to revise the Spec and re-run risk analysis; if usage scenarios or the decomposition are affected, also re-run Preflights 2/3.

1. Call the `code-writer` subagent to produce code
2. `git add` the changed files into the staging area (so code-reviewer / eval-scorer can read them via `git diff --cached`)
3. Call the `code-reviewer` subagent to review and parse 🔴 critical issues
   - If 🔴 exists: fix according to suggestions (or call `code-writer`), then `git add` again and call `code-reviewer` to verify
4. Once 🔴 is cleared, call the `task-verifier` subagent to confirm feature completeness
   - Compare task.md vs the actual diff (subtasks completed, DoD met, no scope drift)
   - If gaps are found, fix them and return to step 3
5. **Local test verification (hard gate, corresponds to "Deployment Rules")**: run the tests (or, if no test framework exists, actually run the feature to verify)
   - Pass → set that sub_task's `local_test_passed` to `true` (the hook enforces this field at commit time)
   - Failure → fix and return to step 3; scoring and commit must not proceed until this step passes
6. Call the `eval-scorer` subagent to score independently (reads `git diff --cached`); append the result to `eval_state.json`
   - **With multiple sub_tasks**: the staging area accumulates changes from earlier sub_tasks; the prompt must restrict code-reviewer / eval-scorer to the files of the current sub_task only (`git diff --cached -- <paths of this sub_task>`) to avoid cross-contaminating the scoring scope
7. Evaluate the score:
   - **score >= threshold** → wrap-up sequence (**hook-enforced**, see "Hard Gate Enforcement"): ① archive `eval_state.json` as `run/<run_id>.eval.json` (a permanent record of per-round scores and deduction reasons), fill the manifest with `status: "completed"`, and **clear `eval_state.json`** ② `git add` the manifest `run/<run_id>.json`, the eval archive, the usage report, and the task file together ③ git commit with a `Run-Id: <run_id>` trailer at the end of the message (the Spec↔usage↔task↔commit provenance is looked up via `git log --grep "Run-Id: <run_id>"`); finish
   - **score < threshold and rounds < 2** → generate an improvement brief from the scoring report, return to step 1
   - **score < threshold and rounds == 2** → read `eval_state.json`, generate a full report, and report back to the user
8. **Conditionally** call the `retro` subagent:
   - code-reviewer reported 🔴 critical issues → call retro before commit (after fixes)
   - score < threshold (multiple improvement rounds needed) → call retro before the final commit
   - code-reviewer had no 🔴 and the score passed in one shot → **do NOT call retro** (no retrospective needed)

### Model Assignment Principles

- Models are specified in each agent definition file's frontmatter `model` field (single source of truth); this document does not duplicate the list
- Assignment rule: **reasoning/judgment-dense planning and review (decomposition, scenario inventory, review) → strong model; mechanical, high-volume execution → fast model**. One wrong judgment at the planning stage costs far more in full-flow reruns than the unit price of a strong model
- Exception: Preflight 1 risk analysis is a skill executed by the main flow; it has no frontmatter to specify a model and uses the main session model

### Subagent Invocation Principles (Save Tokens)

- When **code-reviewer / task-verifier / eval-scorer** need to read code changes, **the prompt must instruct them to use `git diff --cached`** (Bash tool); do NOT use Read to load full files one by one. `git diff` only returns the changed portion, consuming far fewer tokens than reading entire files.
- **auto-mode definition**: the user has **explicitly** enabled it in this session (e.g., "turn on auto-mode", "run fully automated"). If not explicitly stated, treat it as OFF — never infer it.
- **When auto-mode is ON**: these 3 agents may run in the background (`run_in_background: true`); Bash will be auto-approved.
- **When auto-mode is OFF**: these 3 agents must run in the foreground so the user can approve Bash permissions. Do NOT run them in the background (background agents cannot trigger permission prompts, which causes Bash to be denied).
- Agents that don't need Bash, such as **retro / task-reviewer**: may run in the background at any time.
- **usage-analyzer / task-decomposer** (planning agents, no Bash needed): may produce output in the background. But both have a checkpoint after their output and must not continue automatically from the background:
  - `usage-analyzer` is followed by the **user confirmation gate** (Preflight 2, the user rules on each open question) before `usage_report_path` is written back
  - `task-decomposer` is followed by **`task-reviewer` review** before entering the loop (review criteria live in its definition/skill); in Tier 1 the main flow does a lightweight plan confirmation instead

### Run Manifest Format (`run/<run_id>.json`)

Cold provenance file. Created in Preflight 0, paths backfilled by each preflight step, committed to git alongside the code, **never deleted**.

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "created_at": "2026-07-06 14:30",
  "tier": 2,
  "tier_rationale": "multi-role + touches payments → forced Tier 2",
  "spec_path": "spec/2026-07-06-partial-settlement.md",
  "spec_inline": null,
  "usage_report_path": null,
  "task_file": null,
  "status": "in_progress | completed | failed"
}
```

- `tier` / `tier_rationale`: written after the Router decision (for audit; must be updated if Tier 1 upgrades to Tier 2)
- `spec_path` / `spec_inline`: Tier 2 uses `spec_path` (Spec file); Tier 1 uses `spec_inline` (the original one-sentence requirement). **At least one must be non-empty**; if both are empty, do not proceed (intent gate)
- `usage_report_path`: written after user confirmation in Tier 2 Preflight 2 (`null` → task decomposition must not start); fixed to `"skipped"` for Tier 1
- `task_file`: written after decomposition / task-file creation
- `status`: set to `"completed"` during the step 7 wrap-up (before commit). The manifest↔commit link is not recorded as a `commit_sha`; it is looked up via the commit message's `Run-Id: <run_id>` trailer (`git log --grep`)

### eval_state.json Format

Hot scoring scratchpad. Linked to the manifest via `run_id`; archived as `run/<run_id>.eval.json` after commit, then cleared.

```json
{
  "run_id": "2026-07-06-partial-settlement",
  "threshold": 6,
  "sub_tasks": [
    {
      "id": 1,
      "name": "subtask name",
      "status": "passed | failed | in_progress",
      "warning": false,
      "local_test_passed": false,
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

- **Preflight 0 (initialization)**: create the manifest `run/<run_id>.json` (fill `run_id`, `created_at`, `spec_path`; the rest `null`; `status: "in_progress"`) and `eval_state.json` (fill `run_id`, `threshold`, empty `sub_tasks`). Do not proceed until the manifest's `spec_path` is filled
- **After usage scenario analysis / after task decomposition**: `usage_report_path` and `task_file` are written back by `usage-analyzer` and `task-decomposer` in their respective steps (timing and conditions in the agent definitions). While the former is `null`, task decomposition must not start
- **After risk analysis**: fill the 6-dimension results into the corresponding sub_task's `risk_analysis`; if any 🔴 exists, set `blocking: true` — the Spec must be revised and re-analyzed
- **After the local test passes (step 5)**: set that sub_task's `local_test_passed` to `true` (defaults to `false`; at commit time the hook checks that this field is `true` for every sub_task in the archive)
- **After each scoring round**: append the `eval-scorer` result to the corresponding sub_task's `rounds` array
- **When quality_score < 10 (even if it passes the threshold)**: the round's `deduction_reasons` array must list every deduction
  - Each entry must contain `points_lost` (points deducted), `dimension` (which dimension), `reason` (specific reason), and `evidence` (file:line or evidence)
  - The sum of all `points_lost` must equal `10 - quality_score` (e.g., score 8 → total deductions = 2)
  - When score = 10, `deduction_reasons` is an empty array `[]`
- **When score < threshold**: fill in that round's `brief_sent_to_writer` with the improvement summary
- **When a sub_task passes**: set that sub_task's `status` to `"passed"`
- **When a sub_task fails after 2 rounds**: set `status` to `"failed"` and `warning` to `true`
- **When everything completes and passes**: set `eval_state.json`'s top-level `status` to `"completed"` and **first archive it as `run/<run_id>.eval.json`** (preserving scoring history and deduction reasons), clear `eval_state.json`, set the manifest `status` to `"completed"`, and **then** commit (the archive and manifest go into git in the same batch; the order is hook-enforced — committing while `eval_state.json` still exists is blocked)
- **If any sub_task is failed**: set both the manifest's and `eval_state.json`'s `status` to `"failed"` and report back to the user
  - **Failure wrap-up**: leave the staging area as-is (changes from passed sub_tasks stay staged); **do not unstage, do not partially commit, do not clear `eval_state.json`** — the user decides what happens next (continue, partial commit, or abandon). At this point the hook blocks any `git commit` from Claude (`eval_state.json` still exists) — this is expected; the user can partial-commit from their own terminal (the hook only intercepts Claude's Bash tool)

### Hard Gate Enforcement (hook)

The following gates are enforced by a PreToolUse hook (`.claude/hooks/gate-check.sh` → `eval_gates.py`, configured in `.claude/settings.json`) that intercepts Claude's `git commit` — no longer relying on the prose constraints in this document alone:

1. **Archive gate**: `eval_state.json` still exists → block the commit (prevents skipping the archive step; also blocks during failure wrap-up, which is expected)
2. **Intent gate**: a staged `run/<run_id>.json` has both `spec_path` and `spec_inline` empty, or `status` is not `"completed"` → block
3. **Test gate**: the staged manifest's `run/<run_id>.eval.json` is not staged in the same batch, or any sub_task is not `passed` / `local_test_passed` is not `true` → block
4. **Invariant validation**: any round where the sum of `deduction_reasons.points_lost` ≠ `10 - quality_score`, or the archive's `run_id` doesn't match the manifest → block

When blocked, the hook reports the reason on stderr; fix the state per the message and retry. Self-check at any point in the flow: `python3 .claude/hooks/eval_gates.py --validate eval_state.json`. The hook only intercepts Claude's Bash tool and does not affect git operations in the user's own terminal. The corresponding prose in this document is descriptive; the hook is the actual line of defense.

## Tier 1 Lightweight Path

For small features that are well-defined, single-path, and touch no high-risk area. **Skips the Spec file and usage analysis, but still keeps provenance and still enforces the size limits.** Risk is screened by the Router's exclusion conditions (anything touching a high-risk area never reaches Tier 1), so the 6-dimension analysis is not run separately.

1. **Lightweight initialization**: create the manifest `run/<run_id>.json`, filling `tier: 1`, `tier_rationale`, **`spec_inline`** (the original one-sentence requirement, replacing `spec_path`), `usage_report_path: "skipped"`; create `eval_state.json` (`run_id` + `threshold` + empty `sub_tasks`)
   - **Intent gate (non-negotiable)**: at least one of `spec_path` and `spec_inline` must be non-empty; if both are empty, do not proceed
2. **Create the task file directly**: skip the `task-decomposer` subagent, but the limits stay — **1 task, ≤5 items (hard), each item targeting ≤300 lines (soft)**. More than 5 items, or work far exceeding 300 lines that can't fit within 5 items → trigger the upgrade escape hatch (back to Tier 2)
3. **Lightweight HITL**: before writing code, report the "1 task / N items" plan to the user for one confirmation (prevents silently coding on a misjudged tier). Enter the loop only after confirmation
4. **Shared loop**: enter Eval Flow steps 1–8 (code-writer → review → verify → local test → score → commit). Wrap up as in step 7: first archive and clear `eval_state.json` and mark the manifest `completed`, then `git add` the manifest / task file together and commit (message carries the `Run-Id: <run_id>` trailer)
   - A sub_task's `risk_analysis` may simply read `"screened by router (Tier 1)"` — no per-dimension entries needed

## Task Principle

- Task files live in the `task/` folder, named by date: `task/YYYY-MM-DD.md`
- Usage scenario reports live in the `usage/` folder, named by run_id: `usage/<run_id>.md` (mirroring the task folder convention)
- Run manifests live in the `run/` folder: `run/<run_id>.json` (cold provenance, committed to git)
- Whenever adding or reading tasks, use **today's date** for the filename (e.g., `task/2026-04-18.md`)
- The old `task.md` is kept only as a historical record; do not add new tasks to it
- Call subagents to complete tasks
- Mark the creation time of each task
- Tasks that can be parallelized should be marked with [P]
- Once a task is completed, mark it as [x]
- **After new tasks are added to a task file, you must call the `task-reviewer` subagent to review them**, confirming descriptions are clear, the breakdown is reasonable, and technical constraints are noted, before execution begins
  - Breakdown reasonableness is reviewed against the **task-decomposition** skill's limits (≤5 items hard, ≤300 lines/item soft, etc. — details in the skill), not restated here
- **After all subtasks of a task are completed, you must call the `task-verifier` subagent to verify** that the implementation matches the description, before commit

## Subagent Principle

- After work is completed, if the task came from a task file, mark the task as complete in the corresponding task file once eval-scoring is done

## Deployment Preparation

- Before deployment, check potential risks and inform the user; only deploy after confirmation
- Before deployment, check the impact of any DB-related operations; only deploy after confirmation
