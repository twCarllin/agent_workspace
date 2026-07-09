#!/bin/bash
# PreToolUse hook（matcher: Bash）：把 stdin 的 hook JSON 交給 eval_gates.py 檢查
# exit 0 放行；exit 2 block（stderr 回饋給 Claude）
set -euo pipefail
exec python3 "$(dirname "$0")/eval_gates.py" --hook
