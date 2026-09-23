#!/usr/bin/env python3
"""Eval Flow gate 檢查。

兩種模式：
  --hook            PreToolUse hook：stdin 讀 hook JSON。
                    Bash → 攔 `git commit`，跑 commit gate；
                    Task/Agent → 依 manifest.phase 狀態機攔亂序的 subagent 呼叫
  --validate <path> 獨立驗證單一 eval_state / eval 歸檔檔的不變量

exit 0 = 放行；exit 2 = block（stderr 說明原因，回饋給 Claude 修正）。
"""
import glob
import json
import os
import re
import subprocess
import sys

GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-[A-Za-z0-9-]+(?:[= ]\S+)?\s+)*commit\b")
# 衍生檔（.eval.json / .test_baseline.json）的排除寫進 pattern 本身（單一判定點），
# 不散落在各呼叫點用 endswith 補丁——新增衍生檔種類時只改這裡。
#
# 本 pattern 的合法匹配對象：
#   - run/<run_id>.json                       一般主 manifest
#   - run/<run_id>-item-<id>.json             Tier 2 fan-out 子 manifest
#       └ run_id 群組捕捉結果含「-item-<id>」後綴；子 manifest 是獨立合法 manifest，
#         與主 manifest 平行受同一 gate 管轄；各子 run 各自歸檔自己的 .eval.json。
#
# 負向後查排除的衍生檔（不屬於 manifest）：
#   - *.eval.json          （主 run 歸檔）
#   - *.test_baseline.json （測試基線快照）
#   - *-item-<id>.eval.json（子 run 歸檔，同樣被「(?<!\.eval)」正確排除）
#
# 子 manifest 額外欄位：
#   parent_run_id（可選）— 指向父 run_id（契約定義於 eval-flow / parallel-run skill）。
#   本檔 gate 目前不消費此欄（故多帶此欄不影響任何判定、不會 KeyError）；
#   未來任何消費點須以 .get() 讀取，以相容無此欄的舊版 manifest。
#
# !! 本 pattern 是「以檔名識別 manifest 身分」的唯一判定點 !!
# 新增子 manifest 命名規則或衍生檔種類時，必須先在此更新 pattern 與上方說明，
# 不可在呼叫點用 endswith / startswith 補丁繞過（違反單一判定點原則）。
MANIFEST_RE = re.compile(
    r"^run/(?P<run_id>[^/]+?)(?<!\.eval)(?<!\.test_baseline)\.json$"
)

# commit message 的 `Run-Id: <run_id>` trailer——收尾 commit 的必填項（eval-flow SKILL.md
# step 6 ③ 與 Tier 1 精簡路徑第 5 點）。冷溯源檔不再進版控後，這是把一次 commit 對應回
# 某個 run 的唯一可機械解析線索；gate 憑此從**工作目錄**定位 manifest，不再依賴它被 staged。
#
# 解析對象是 **Bash 指令原文**（hook 收到的 `tool_input.command`），不是 git 已解析的
# message，故 trailer 那一行的尾端可能殘留 shell 語法（`-m "…"` 的收尾引號、heredoc
# 分隔符等）。因此：
#   - 捕捉組收斂為 run_id 實際字元集 `[A-Za-z0-9._-]`（日期-slug 命名），遇引號自然停住
#   - **不加行尾 `$` 錨點**——加了會讓上述常見寫法整條匹配失敗，靜默退化成「定位不到」
RUN_ID_TRAILER_RE = re.compile(r"^[ \t]*Run-Id:[ \t]*([A-Za-z0-9._-]+)", re.MULTILINE)

TEST_FILE_NAME_RE = re.compile(r"^(test_.*|.*_test)\.py$")
TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec"}

# phase 狀態機：manifest.phase 依前置步驟推進，subagent 呼叫需達到對應 phase
# 2026-09-22 tier2-slimming（Spec §3.2）：5→3 值域收斂，risk_done／usage_confirmed 兩值
# 移除；舊 manifest 讀到這兩值時由 manifest_phase() 映射為 init（向後相容，見該函式）。
PHASES = ["init", "decomposed", "completed"]
PENDING_STATUSES = {"in_progress", "ready_to_commit"}
AGENT_MIN_PHASE = {
    "usage-analyzer": "init",   # 具名問題隨時可觸發（前置 2 改觸發式，Spec §3.1 D2）
    "impact-analyzer": "init",  # 具名問題隨時可觸發（前置 2.5 改觸發式，Spec §3.1 D2）
    "task-decomposer": "init",  # 分拆隨時可做（前置 3 改條件派工，Spec §3.1）
    "code-writer": "decomposed",  # 前置 3（task 分拆）完成才可進循環
}


# hook 模式下被擋時附上；流程細節不在常駐 context，被擋常代表 skill 未載入或已被 compact
SKILL_HINT = "（流程細節住在 eval-flow skill：若尚未載入或 context 被 compact，先載入 skills/eval-flow/SKILL.md，再依檔案狀態修正）"
_hint_enabled = False


def log_gate_hit(msg):
    """gate 命中遙測：append 到 run/gate_hits.log（stats.py 彙總用）。
    只在 run/ 已存在時寫（不在非 flow 專案留檔）；失敗不影響攔截本身。"""
    if not os.path.isdir("run"):
        return
    try:
        from datetime import datetime
        first_line = msg.splitlines()[0][:200]
        with open("run/gate_hits.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{first_line}\n")
    except OSError:
        pass


def block(msg):
    if _hint_enabled:
        log_gate_hit(msg)
    hint = f"\n[gate-check] {SKILL_HINT}" if _hint_enabled else ""
    print(f"[gate-check] BLOCK: {msg}{hint}", file=sys.stderr)
    sys.exit(2)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        block(f"{path} 無法讀取或非合法 JSON（{e}）")


def _validate_credentials(obj, source):
    """驗四項憑據（per-subtask 與 Tier 1 manifest 共用單一判定點）。"""
    if obj.get("local_test_passed") is not True:
        block(f"{source} local_test_passed 非 true：本地測試 gate 未通過，須先完成 step 5 驗證\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-test <id> --passed --evidence \"指令＋結果摘要\"`；Tier 1 直接填 manifest 同名欄")
    evidence = obj.get("local_test_evidence")
    if not (isinstance(evidence, str) and evidence.strip()):
        block(f"{source} local_test_evidence 為空：須記錄驗證證據（跑了什麼指令、看到什麼結果）\n"
              f"→ 補救：同上，`set-test <id> --passed --evidence \"...\"` 的 --evidence 不可省；Tier 1 直接填 manifest 同名欄")
    reds = obj.get("review_reds")
    if not (isinstance(reds, int) and not isinstance(reds, bool)) or reds < 0:
        block(f"{source} review_reds 未留痕或非合法非負整數：step 3 須記錄 🔴 數（非負整數）\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-review <id> <reds 數字>`；Tier 1 直接填 manifest 同名欄")
    if obj.get("verify_passed") is not True:
        block(f"{source} verify_passed 非 true：reviewer 完成度節尚未通過\n"
              f"→ 補救：Tier 2 `python3 .claude/hooks/eval_state.py set-verify <id>`（無 --passed 旗標）；Tier 1 直接填 manifest 同名欄")


def _validate_evidence_snapshot(manifest, source):
    if manifest.get("evidence_schema") != 2 or manifest.get("tier") in ("B", "hotfix"):
        return  # Existing runs keep their original evidence contract.
    commands = manifest.get("verification_commands") or []
    latest = commands[-1] if commands else {}
    if latest.get("exit_code") != 0 or not latest.get("snapshot"):
        block(f"{source} 缺通過的全套驗證快照；用 run_verify.py 重新驗證")
    try:
        import verification_snapshot
        current = verification_snapshot.snapshot()
    except (OSError, subprocess.CalledProcessError) as error:
        block(f"{source} 無法核對驗證快照：{error}")
    if current != latest["snapshot"]:
        block(f"{source} 驗證後程式樹已變更；請重新驗證")


def validate_state(state, source, require_passed=False):
    """逐筆驗 sub_task 的 status 與四項憑據。

    **一筆代表什麼，2026-09-22 起改變**（Q2）：新 run 的一筆＝一個 **task**（審查與測試
    都以 task 為單位）；既有 19 份 `run/*.eval.json` 歸檔的一筆＝一個 **item**（舊語義）。
    兩者的欄位在**同一層**（status／憑據四欄都在頂層），故本函式對新舊形狀共用同一套判定、
    無需分支——差別只在「一筆代表什麼」，那影響的是 `stats.py` 的分母語義，不是這裡。
    `eval_state` 不存 item 層資料（Q10），故本函式也不該新增任何 `items` 相關判定。
    """
    # rounds 品質不變量已隨 eval-scorer 移除；舊格式歸檔（含 rounds）寬容放行
    if not state.get("run_id"):
        block(f"{source} 缺 run_id")
    for st in state.get("sub_tasks", []):
        if require_passed:
            name = st.get("name") or st.get("id")
            if st.get("status") != "passed":
                block(f"{source} sub_task「{name}」status 非 passed（{st.get('status')}）\n"
                      f"→ 補救：該 sub_task 走完循環後 `python3 .claude/hooks/eval_state.py set-status <id> passed`（status 可選 passed／failed／in_progress）")
            _validate_credentials(st, f"{source} sub_task「{name}」")


def check_manifest(manifest_path, staged, allow_in_progress=False):
    m = load_json(manifest_path)
    run_id = MANIFEST_RE.match(manifest_path).group("run_id")

    if not (m.get("spec_path") or m.get("spec_inline")):
        block(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空")
    allowed_statuses = ("in_progress", "ready_to_commit", "completed") if allow_in_progress else ("ready_to_commit", "completed")
    if m.get("status") not in allowed_statuses:
        block(f"{manifest_path} status 非 completed/ready_to_commit（{m.get('status')}），不可 commit")
    _validate_evidence_snapshot(m, manifest_path)

    if m.get("tier") == "hotfix":
        if not isinstance(m.get("debt"), list):
            block(f"{manifest_path} 為 hotfix 但缺 debt 欄位（欠帳清單，如 [\"risk\", \"test\", \"retro\"]）")
        return  # hotfix 不走循環評分，豁免 eval 歸檔檔要求；欠帳由 debt gate 追討

    if m.get("tier") == "B":
        if m.get("bootstrap_verified") is not True:
            block(
                f"{manifest_path} 為 Tier B 但 bootstrap_verified 非 true："
                f"DoD 兩條（本地 build/run 跑得通、測試框架＋示範測試會跑）未驗證，不可 commit"
            )
        return  # Tier B 不走循環評分，豁免 eval 歸檔檔要求

    tier = m.get("tier")
    archive_path = f"run/{run_id}.eval.json"

    if archive_path in staged or os.path.exists(archive_path):
        # 歸檔檔存在（staged 或工作目錄）：Tier 1（向後相容）＋ Tier 2（現行）共用此路徑
        # （單一判定點）。冷溯源檔不再進版控後，歸檔檔的常態是「在工作目錄、未 staged」，
        # 故判定由 staged 成員資格放寬為「staged 或工作目錄存在」——語義仍是「歸檔已完成」。
        archive = load_json(archive_path)
        if archive.get("run_id") != run_id:
            block(f"{archive_path} 的 run_id（{archive.get('run_id')}）與 manifest 不一致")
        validate_state(archive, archive_path, require_passed=True)
    elif tier == 1 or tier == "1":
        # Tier 1 豁免歸檔檔，改驗 manifest 自身四欄憑據（與 validate_state 共用 _validate_credentials）
        _validate_credentials(m, manifest_path)
    else:
        block(f"{manifest_path} 的 {archive_path} 不存在：須先歸檔 eval_state 再 commit\n"
              f"→ 補救：`python3 .claude/hooks/eval_state.py archive` 產出 {archive_path}"
              f"（歸檔檔是冷溯源檔，留在工作目錄即可，不需 git add）")


def manifest_phase(manifest):
    """讀 manifest.phase；舊 manifest 無此欄時由既有欄位推導（向後相容）。

    2026-09-22 tier2-slimming（Spec §3.2 向後相容，硬性）：舊值域含 risk_done／
    usage_confirmed，新值域（PHASES）已移除這兩值。顯式值分支與推導分支都必須把
    這兩值映射為 init，且映射須發生在 PHASES.index()（見 check_task_gate）之前——
    不可用 try/except 兜底：吞例外會讓 phase 判定靜默走偏，等同 gate 不套用
    （R-005 同型事故：worktree gate 曾因未執行到的路徑靜默放行）。
    推導分支的 usage_report_path 非空不再視為 usage_confirmed（該值已離開值域，
    且 usage_report_path 語義已改為「具名問題觸發，長期 null 屬正常」，Spec §3.1 D2）——
    無顯式 phase 且無 task_file 時一律落回 init。
    """
    phase = manifest.get("phase")
    if phase in ("risk_done", "usage_confirmed"):
        return "init"
    if phase in PHASES:
        return phase
    if manifest.get("task_file"):
        return "decomposed"
    return "init"


def load_json_quiet(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def check_other_runs(current_run_id):
    """欠帳 gate ＋ 單一 run gate：掃本工作區的其他 manifest。
    僅 status == "in_progress" 視為佔用；"aborted"（使用者/主 flow 決定放棄）與
    "failed"（流程內判定失敗）皆非 in_progress，不擋新 run（1a 消費點一）。"""
    for path in sorted(glob.glob("run/*.json")):
        if not MANIFEST_RE.match(path):
            continue
        other = load_json_quiet(path)
        if not isinstance(other, dict):
            continue
        other_id = other.get("run_id")
        if other.get("debt"):
            block(
                f"{path} 有未清欠帳 debt={other.get('debt')}（hotfix 遺留）："
                f"須先還清（補 risk 分析／回歸測試／retro，還一項移除一項）才可啟動新 run"
            )
        if other_id != current_run_id and other.get("status") in PENDING_STATUSES:
            block(
                f"本工作區已有另一個未完成的 run（{path}）："
                f"一個 worktree 同時只允許一個 run。先收尾／封存該 run，"
                f"要並行請開 git worktree，中斷續跑依 eval-flow-resume skill"
            )


def _git_diff_cached_paths(*extra_args):
    """`git diff --cached --name-only -z [extra_args]` 取得 staged 檔案路徑清單。

    依規格用 `-z`：輸出以 NUL 分隔、不對含空白／特殊字元的路徑做 C-quote 逃逸，
    避免以空白 split 或字串拼接誤判檔名邊界（見 git-diff(1) --name-only／-z 說明）。
    失敗（非 git repo 等）回傳 None，由呼叫端自行決定 fail-open。
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z", *extra_args],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.split("\0") if p]


def check_manifest_deletion():
    """1b 防刪除 gate：staged 變更中出現 manifest（`MANIFEST_RE` 匹配）的刪除 → 擋 commit。
    以 `--diff-filter=D` 精確取得刪除清單（而非用一般 staged 清單猜測狀態）；
    加 `--no-renames`：git 預設會把「刪舊檔＋加新檔」偵測為 rename 並只回報新路徑，
    使舊 manifest 路徑不會出現在 `--diff-filter=D` 結果中（實測驗證）——manifest 改名
    等同讓原 run_id 的紀錄從其路徑消失，須視同刪除攔截，不留 rename 繞過本 gate 的縫。
    歸檔檔／baseline 檔不受 `MANIFEST_RE` 匹配，本 gate 不觸及（單一判定點鐵律）。
    非 git repo 等情況 fail-open（不擋）。"""
    deleted = _git_diff_cached_paths("--no-renames", "--diff-filter=D")
    if deleted is None:
        return
    for path in deleted:
        if MANIFEST_RE.match(path):
            block(
                f"{path} 被刪除：manifest 是冷溯源檔，永不可刪除。"
                f"這個 run 若要放棄，改標記 status: \"aborted\" 並填寫 failed_reason，不要刪檔\n"
                f"→ 補救：`git restore --staged {path}`（取消刪除的暫存），再視需要標 aborted"
            )


def check_abort_failed_narrow_exception(staged):
    """1d 窄例外：staged 檔案集合恰為一個 manifest（`MANIFEST_RE` 匹配）、
    其 `status` 為 `aborted` 或 `failed`、且 `failed_reason` 非空
    → 回傳 True（呼叫端據此放行整個 commit gate，豁免 gate 1 的 eval_state.json 攔截）。
    任一條件不成立 → 回傳 False，落回原判定（呼叫端照常往下跑其餘 gate）。"""
    if len(staged) != 1:
        return False
    (path,) = staged
    if not MANIFEST_RE.match(path):
        return False
    m = load_json_quiet(path)
    if not isinstance(m, dict):
        return False
    if m.get("status") not in ("aborted", "failed"):
        return False
    reason = m.get("failed_reason")
    return isinstance(reason, str) and bool(reason.strip())


def _manifest_path_from_command(command):
    """從 `git commit` 指令原文的 `Run-Id:` trailer 定位 manifest 路徑。

    回傳可用的 `run/<run_id>.json`，或 None（無 trailer／不成合法 manifest 路徑／檔案不存在）。
    路徑合法性一律交給 `MANIFEST_RE` 判定（以 pattern 判檔案身分的單一判定點鐵律，R-001）——
    不得在此另寫 endswith／startswith 補丁；亦不需另做路徑逃逸防護，pattern 的 `[^/]+?`
    已排除路徑分隔符。

    !! 判定基準：工作目錄（`os.path.exists`）!!
    與同一執行路徑上 `check_manifest_deletion()` 的 git 索引基準（`--diff-filter=D`）不同，
    依 R-009 於此明文標注兩者的發散情境與處置：
      - 索引已刪、工作區仍在（`git rm --cached`）→ 防刪除 gate 排在本函式之前並攔下，
        本函式不會被觸及（順序不可調換，見 run_hook 內註解）
      - 從未進版控、工作區存在 → 索引查不到、本函式查得到。這正是本函式存在的理由：
        冷溯源檔不再進版控後，「manifest 在工作目錄但不在索引」是常態而非異常
      - 工作區已刪、索引仍在 → 本函式回 None，落回 `check_inprogress_runs()` 安全網；
        安全網同樣掃工作目錄故亦查不到，gate fail-open。此與改造前「manifest 未 staged
        即完全不檢查」的行為一致，不新增亦不減少攔截面
    """
    m = RUN_ID_TRAILER_RE.search(command)
    if not m:
        return None
    path = f"run/{m.group(1)}.json"
    if not MANIFEST_RE.match(path):
        return None
    return path if os.path.exists(path) else None


def check_inprogress_runs():
    """安全網（攔截型）：未能從 trailer 或 staged 定位到任何 manifest 時，掃工作目錄
    `run/*.json`，發現 `status == "in_progress"` 的 run → 擋 commit。

    存在理由：改造前本 gate 以「staged 中有 manifest」為啟動條件，manifest 被
    `.gitignore` 擋住（或單純沒 add）時，四項憑據一項都不驗、commit 靜默放行且無訊息。
    冷溯源檔不再進版控後這會成為常態，故改以工作目錄的 run 狀態兜底。

    判定基準為工作目錄（基準發散說明見 `_manifest_path_from_command` docstring，R-009）。
    """
    for path in sorted(glob.glob("run/*.json")):
        if not MANIFEST_RE.match(path):
            continue
        m = load_json_quiet(path)
        if not isinstance(m, dict):
            continue
        if m.get("status") in PENDING_STATUSES:
            block(
                f"{path} 仍為 {m.get('status')}：該 run 尚未完成，不可在缺 Run-Id 的情況下 commit\n"
                f"→ 補救：走完 eval-flow step 5／6（填四欄憑據、status 設 ready_to_commit），並於 commit message 加 Run-Id；"
                f"若決定放棄該 run，改標 status: \"aborted\" 並填 failed_reason（不要刪檔）"
            )


def _managed_commit_hook_available():
    """The Git commit-msg hook validates the final message when command text cannot."""
    try:
        configured = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True
        )
        if configured.returncode == 0:
            return False  # An external hooksPath has not been wired by our installer.
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks/commit-msg"],
            capture_output=True, text=True, check=True,
        )
        path = result.stdout.strip()
        with open(path, encoding="utf-8") as stream:
            return "agent-workspace managed commit message gate" in stream.read()
    except (OSError, subprocess.CalledProcessError):
        return False


def is_test_file(path):
    if not path.endswith(".py"):
        return False
    if TEST_FILE_NAME_RE.match(os.path.basename(path)):
        return True
    return any(part in TEST_DIR_NAMES for part in path.split("/")[:-1])


def check_staged_test_lint(staged):
    """假測試 lint gate：flow 收尾 commit 時，staged 的 Python 測試檔須通過 test_lint.py。"""
    test_files = [p for p in sorted(staged) if is_test_file(p) and os.path.exists(p)]
    if not test_files:
        return
    lint = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_lint.py")
    if not os.path.exists(lint):
        return  # 部署未含 lint script 時不擋（防線以存在的工具為準）
    p = subprocess.run(
        [sys.executable, lint, *test_files], capture_output=True, text=True
    )
    if p.returncode != 0:
        detail = (p.stdout + p.stderr).strip()
        block(f"假測試 lint 未過（修測試或以行尾 `# testlint: allow` 豁免並留痕）：\n{detail}")


def _find_unique_tier1_inprogress():
    """掃 run/ 找唯一一個 tier==1 且 status==in_progress 的 manifest。
    回傳 (manifest_path, manifest_dict) 或 None（找不到或多個）。
    須重用 MANIFEST_RE（單一判定點，硬約束）。
    status=="aborted" 或 "failed" 的 tier-1 manifest 不符合 in_progress 判定，
    不會被選為當前 run（1a 消費點四）。"""
    found = []
    for path in sorted(glob.glob("run/*.json")):
        if not MANIFEST_RE.match(path):
            continue
        m = load_json_quiet(path)
        if not isinstance(m, dict):
            continue
        tier = m.get("tier")
        if (tier == 1 or tier == "1") and m.get("status") == "in_progress":
            found.append((path, m))
    return found[0] if len(found) == 1 else None


def check_task_gate(tool_input):
    agent = tool_input.get("subagent_type") or tool_input.get("agent_type") or ""
    required = AGENT_MIN_PHASE.get(agent)
    if not required:
        sys.exit(0)  # 非流程管制的 agent，不擋

    # 前置步驟（單一判定點）：取得 manifest_path、manifest、state
    # eval_state.json 存在 → Tier 2 常規路徑；否則 → Tier 1 豁免路徑
    if os.path.exists("eval_state.json"):
        state = load_json("eval_state.json")
        run_id = state.get("run_id")
        if not run_id:
            block(f"eval_state.json 缺 run_id，無法定位 manifest；呼叫 {agent} 被擋\n"
                  f"→ 補救：`python3 .claude/hooks/eval_state.py init --run-id <run_id>` 重建（run_id 須與 run/<run_id>.json 一致）")
        manifest_path = f"run/{run_id}.json"
        if not os.path.exists(manifest_path):
            block(f"{manifest_path} 不存在（前置 0 未完成），不可呼叫 {agent}")
        manifest = load_json(manifest_path)
    else:
        state = None
        # DoD (a)：找唯一 tier 1 in_progress manifest 作為當前 run 依據
        tier1 = _find_unique_tier1_inprogress()
        if tier1 is None:
            block(f"呼叫 {agent} 前須完成前置 0：eval_state.json 不存在（run 未初始化）\n"
                  f"→ 補救：`python3 .claude/hooks/eval_state.py init --run-id <run_id>`（Tier 1 不建 eval_state.json，若本 run 為 Tier 1 請改走精簡路徑）")
        manifest_path, manifest = tier1
        run_id = MANIFEST_RE.match(manifest_path).group("run_id")

    # 以下 gate 邏輯為單一共用路徑（Tier 1 與 Tier 2 不再各有一份）
    check_other_runs(run_id)

    if not (manifest.get("spec_path") or manifest.get("spec_inline")):
        block(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空，不可呼叫 {agent}")

    phase = manifest_phase(manifest)
    if PHASES.index(phase) < PHASES.index(required):
        block(
            f"phase 狀態機：呼叫 {agent} 需 manifest.phase >= {required}，"
            f"目前為 {phase}。請先完成缺少的前置步驟並更新 manifest.phase"
        )

    # task-decomposer 的 usage_report_path 擋人判定已移除（2026-09-22 tier2-slimming
    # Spec §3.2 末：前置 2 改具名問題觸發後，該欄長期 null 屬正常，不再是分拆前置條件）。

    if agent == "code-writer":
        if not manifest.get("task_file"):
            block(f"{manifest_path} task_file 為空：前置 3 未完成，不可呼叫 code-writer")
        # risk_analysis.blocking 遍歷已移除（Q8：前置 1 風險分析連同本刪除，生產者消失、
        # 此 gate 永遠不觸發；`risk_analysis` 欄位寫入路徑同步自 eval_state.py 移除）。

    sys.exit(0)


def _git_toplevel(path):
    """以 git rev-parse --show-toplevel 解析 path 所屬 git root；失敗回 None。
    capture_output=True 吸掉 stderr（非 git 目錄會輸出 fatal: not a git repository）。
    errors="replace"：路徑含非 UTF-8 位元組時不拋 UnicodeDecodeError（ValueError 子類，
    不在下方 except 涵蓋範圍內，逸出會使 hook 以非 2 的碼結束＝gate 靜默不套用）。
    兩側同屬一個 repo 時等量替換、比對仍相等 → 退回 CLAUDE_PROJECT_DIR（fail-safe）。
    跨 worktree 且僅一側含非 UTF-8 位元組時比對不相等，會回傳含 U+FFFD 的路徑、使
    run_hook 的 os.chdir 拋 OSError（fail-open）——此分支不另加防護：toplevel 是 cwd
    的祖先，payload.cwd 既為合法 UTF-8 字串，其祖先亦然，故實務上不可達。"""
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, errors="replace", timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve_root(payload):
    """解析 run_hook() 應 chdir 的工作區根目錄。H1 最小偏離設計：只有確認
    cwd 與 CLAUDE_PROJECT_DIR 屬不同 git worktree 時才改變行為，其餘一律回 CPD。
    """
    cpd_env = os.environ.get("CLAUDE_PROJECT_DIR")
    if not cpd_env:
        return _git_toplevel(payload.get("cwd") or os.getcwd()) or os.getcwd()
    cpd = cpd_env
    cwd = payload.get("cwd")

    # H1: 無 cwd 鍵 → 嚴格回 CPD（不落到 os.getcwd()；CPD 為 None 時已於上行退路）
    if cwd is None:
        return cpd

    # H1: 字串相等短路，跳過 git（覆蓋主工作區最熱路徑）
    if cpd == cwd:
        return cpd

    # 各跑一次 git rev-parse 吸收 symlink/尾斜線差異
    cwd_top = _git_toplevel(cwd)
    cpd_top = _git_toplevel(cpd)

    # 兩者皆成功且 toplevel 不相等 → 回 cwd 的 toplevel（唯一改變行為的分支）
    if cwd_top is not None and cpd_top is not None and cwd_top != cpd_top:
        return cwd_top

    # 其餘所有情況（任一失敗、或相等）→ 回 CPD
    return cpd


def run_hook():
    global _hint_enabled
    _hint_enabled = True  # 只在 hook 模式附提示；--validate 為人工自檢，不需要
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # 非預期輸入，不擋

    root = _resolve_root(payload)
    os.chdir(root)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name in ("Task", "Agent"):
        check_task_gate(tool_input)

    command = tool_input.get("command", "")
    if not GIT_COMMIT_RE.search(command):
        sys.exit(0)

    staged_list = _git_diff_cached_paths()
    if staged_list is None:
        sys.exit(0)  # 非 git repo 等情況，不擋
    staged = set(staged_list)

    # 1b 防刪除 gate：不變量優先，永遠先擋刪除。必須在 1d 窄例外之前執行——
    # `git rm --cached` 會保留工作區檔案內容，若窄例外先跑，load_json_quiet 會讀到
    # 工作區殘留的 aborted/failed 內容而誤判「非刪除」放行，讓 manifest 從版控消失
    # 卻繞過本 gate（2026-08-20 code-review 🔴，已修正：刪除判定看 git 索引狀態，
    # 不看工作區檔案是否存在，故必須先於任何依賴檔案內容讀取的判定）
    check_manifest_deletion()

    # 1d 窄例外：staged 恰一個 manifest 且 status∈{aborted,failed} 且 failed_reason 非空
    # → 放行整個 commit gate（豁免下方歸檔 gate 的 eval_state.json 存在攔截；
    # 不豁免上方防刪除 gate——窄例外只可能對「非刪除」的 staged manifest 生效）
    if check_abort_failed_narrow_exception(staged):
        sys.exit(0)

    if os.path.exists("eval_state.json"):
        block(
            "eval_state.json 仍存在。須先歸檔為 run/<run_id>.eval.json 並清除後才可 commit；"
            "若為失敗收尾（status: failed），依規則由使用者裁決，不可由 Claude commit\n"
            "→ 補救：`python3 .claude/hooks/eval_state.py archive`（會驗四項憑據、寫出歸檔檔並刪除 eval_state.json），"
            "再把 manifest 標 status: completed（歸檔檔是冷溯源檔，留在工作目錄即可，不需 git add）"
        )

    # 待驗 manifest ＝ staged 中匹配者（向後相容：舊 run，以及仍把 run/ 納入版控的專案）
    # ∪ commit message `Run-Id:` trailer 定位者（冷溯源檔不進版控後的主路徑）。
    manifests = [p for p in sorted(staged) if MANIFEST_RE.match(p)]
    trailer_path = _manifest_path_from_command(command)
    if trailer_path is not None and trailer_path not in manifests:
        manifests.append(trailer_path)

    # 兩條路徑都定位不到 → 安全網。刻意排在 1d 窄例外「之後」（R-008 的攔截型優先原則在此
    # 不適用且不可套用）：窄例外的成立條件是「staged 恰為一個 aborted／failed 的 manifest」，
    # 亦即該次 commit 不含任何 code、只為留痕放棄的 run；那條逃生門不該被另一個未收尾的 run
    # 卡死。兩者的 status 條件（aborted／failed vs in_progress）互斥，不存在互相遮蔽的情境。
    if not manifests:
        if _managed_commit_hook_available() and "--no-verify" not in command and "core.hooksPath" not in command:
            # Git's commit-msg hook receives the final message, including -F and editor input.
            # The tool hook still blocks an unarchived scratchpad above.
            return
        check_inprogress_runs()

    for path in manifests:
        check_manifest(path, staged)
    if manifests:
        check_staged_test_lint(staged)
    sys.exit(0)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--hook"]:
        run_hook()
    elif args[:1] == ["--validate"] and len(args) == 2:
        validate_state(load_json(args[1]), args[1])
        print(f"[gate-check] OK: {args[1]} 不變量檢查通過")
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
