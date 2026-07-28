#!/usr/bin/env bash
# tests/check_worktree_isolation.sh
# 驗證「worktree 天然隔離 → check_other_runs 只掃當前工作目錄」（DoD 3.3 / 假設 4）
# 安全保證：所有 worktree 操作在 mktemp 建出的拋棄式 git repo 內，絕不觸碰真實 run/
#
# ── 涵蓋範圍的界線（勿誤讀本腳本的綠燈）──────────────────────────────────────
# 本腳本以 `import eval_gates; eval_gates.check_other_runs(...)` **直接呼叫函式**，
# 先自行 `cd` 到目標目錄再呼叫，因此**完全不經 run_hook() 的 root 解析與 os.chdir**。
# 它驗證的是「函式在給定 CWD 下只掃該 CWD 的 run/」，**不涵蓋**「run_hook() 會把 CWD
# 換到哪裡」——後者才是 hook 實際跑起來時決定 gate 套用在哪個工作區的關鍵。
# root 解析（含 CLAUDE_PROJECT_DIR 與 payload.cwd 不一致、跨 worktree、子目錄等情境）
# 的端到端覆蓋住在 tests/test_eval_gates.py 的 RunHookWorktreeRootTest，該處以
# subprocess 執行 `eval_gates.py --hook`、stdin 餵構造 payload，且會被
# `python3 -m unittest discover -s tests` 執行到；本 .sh 不在 discover 範圍內。
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# 取得真實 repo 根目錄（腳本在 tests/ 下，往上一層即 repo root）
REAL_REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REAL_REPO/.claude/hooks"

if [[ ! -f "$HOOKS_DIR/eval_gates.py" ]]; then
    echo "FAIL: $HOOKS_DIR/eval_gates.py not found"
    exit 1
fi

# ── 建立拋棄式臨時目錄 ────────────────────────────────────────────────────────
TMPDIR_X="$(mktemp -d)"
SUB_WT="$TMPDIR_X/sub-wt"

cleanup() {
    # 先移除 sub-worktree 的 git 追蹤（在臨時 repo 內操作），再整體刪除
    if [[ -d "$TMPDIR_X/.git" ]]; then
        git -C "$TMPDIR_X" worktree remove --force "$SUB_WT" 2>/dev/null || true
    fi
    rm -rf "$TMPDIR_X"
}
trap 'cleanup' EXIT

echo "=== Worktree Isolation Test (DoD 3.3) ==="
echo "Temp repo : $TMPDIR_X"
echo "Real hooks: $HOOKS_DIR"
echo ""

# ── 初始化拋棄式 git repo ─────────────────────────────────────────────────────
git -C "$TMPDIR_X" init -q
git -C "$TMPDIR_X" config user.email "test@test.com"
git -C "$TMPDIR_X" config user.name "Test"
touch "$TMPDIR_X/README"
git -C "$TMPDIR_X" add README
git -C "$TMPDIR_X" commit -q -m "init"

# 建立 sub-worktree（detach 模式，不建新 branch）
git -C "$TMPDIR_X" worktree add -q --detach "$SUB_WT"

# ── Test 1：在 sub-worktree 建 in_progress 子 manifest ───────────────────────
echo "[Test 1] 在 sub-worktree 建 in_progress manifest..."
mkdir -p "$SUB_WT/run"
cat > "$SUB_WT/run/test-run-item-1.json" <<'MANIFEST'
{
  "run_id": "test-run-item-1",
  "status": "in_progress",
  "spec_inline": "test isolation"
}
MANIFEST
echo "PASS: sub-worktree manifest created: $SUB_WT/run/test-run-item-1.json"

# ── Test 2：sub-worktree 是 git 認可的獨立 worktree，其 manifest 不現於主 worktree ─
echo "[Test 2] 確認 sub-worktree 為獨立 worktree 且主 worktree run/ 不可見其 manifest..."
mkdir -p "$TMPDIR_X/run"
# 先證實兩者是 git 認可的獨立 worktree（各自工作目錄）——這才是隔離的來源，
# 否則「不同目錄無同名檔」只是在驗檔案系統、對 worktree 行為零訊號。
WT_COUNT="$(git -C "$TMPDIR_X" worktree list | wc -l | tr -d ' ')"
if [[ "$WT_COUNT" -ne 2 ]]; then
    echo "FAIL: 預期 2 個 worktree（主＋sub），git worktree list 實得 $WT_COUNT"
    exit 1
fi
if ! git -C "$TMPDIR_X" worktree list | grep -q "$SUB_WT"; then
    echo "FAIL: git worktree list 未列出 sub-worktree（$SUB_WT）"
    exit 1
fi
# 隔離結果：sub-worktree 未提交的 manifest 不出現在主 worktree 的工作目錄
if [[ -e "$TMPDIR_X/run/test-run-item-1.json" ]]; then
    echo "FAIL: 主 worktree run/ 含 sub-worktree manifest（跨 worktree 工作目錄污染）"
    exit 1
fi
echo "PASS: sub-worktree 為 git 獨立 worktree（worktree list 2 個），其 in_progress manifest 不現於主 worktree run/"

# ── Test 3：從主 worktree 呼叫 check_other_runs，不被 sub-worktree manifest 擋 ─
echo "[Test 3] 從主 worktree 呼叫 check_other_runs（預期 exit 0，不誤擋）..."
EXIT_CODE=0
(
    cd "$TMPDIR_X"
    HOOKS_DIR="$HOOKS_DIR" python3 -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_DIR'])
import eval_gates
eval_gates.check_other_runs('current-run')
"
) || EXIT_CODE=$?

if [[ $EXIT_CODE -eq 2 ]]; then
    echo "FAIL: check_other_runs exit=2 — sub-worktree in_progress manifest 誤擋主 worktree（隔離失效）"
    exit 1
elif [[ $EXIT_CODE -ne 0 ]]; then
    echo "FAIL: check_other_runs exit=$EXIT_CODE — 執行環境／匯入錯誤（非隔離問題，請查 python／eval_gates 匯入）"
    exit 1
fi
echo "PASS: check_other_runs exit=0 — sub-worktree in_progress manifest 未誤擋主 worktree"

# ── Test 4：主 worktree 自己有 in_progress manifest → 應被擋（exit 2） ────────
echo "[Test 4] 在主 worktree 建 in_progress manifest，呼叫 check_other_runs（預期 exit 2）..."
cat > "$TMPDIR_X/run/another-run.json" <<'MANIFEST'
{
  "run_id": "another-run",
  "status": "in_progress",
  "spec_inline": "test isolation"
}
MANIFEST

EXIT_CODE=0
(
    cd "$TMPDIR_X"
    HOOKS_DIR="$HOOKS_DIR" python3 -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_DIR'])
import eval_gates
eval_gates.check_other_runs('current-run')
" 2>/dev/null
) || EXIT_CODE=$?

if [[ $EXIT_CODE -ne 2 ]]; then
    echo "FAIL: check_other_runs exit=$EXIT_CODE（預期 2）— 同一 worktree in_progress manifest 應擋"
    exit 1
fi
echo "PASS: check_other_runs exit=2 — 同一 worktree in_progress manifest 正確被擋"

echo ""
echo "=== Summary: 4/4 passed. Worktree 隔離（假設 4）驗證通過。==="
exit 0
