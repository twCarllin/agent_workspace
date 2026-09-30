<!-- agent-workspace managed -->
# Codex model policy

All Codex exec roles use gpt-6.1-sol with low reasoning effort. Writer and reviewer run in separate sessions.

| Role | Model | Reasoning effort |
|---|---|---|
| code-writer | gpt-6.1-sol | low |
| code-reviewer | gpt-6.1-sol | low |
| task-verifier | gpt-6.1-sol | low |
| task-decomposer | gpt-6.1-sol | low |
| usage-analyzer | gpt-6.1-sol | low |
| impact-analyzer | gpt-6.1-sol | low |
| retro | gpt-6.1-sol | low |
