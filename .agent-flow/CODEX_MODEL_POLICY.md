<!-- agent-workspace managed -->
# Codex model policy

Writer and reviewer use different GPT-6 models for independent review.

| Role | Model | Reasoning effort |
|---|---|---|
| code-writer | gpt-6-sol | medium |
| code-reviewer | gpt-6-astra | medium |
| task-verifier | gpt-6-luna | high |
| task-decomposer | gpt-6-astra | medium |
| usage-analyzer | gpt-6-astra | low |
| impact-analyzer | gpt-6-astra | low |
| retro | gpt-6-sol | low |
