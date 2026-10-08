"""Shared Eval Flow decisions. No filesystem or hook side effects."""
import re


class RuleViolation(ValueError):
    """An existing flow rule was not satisfied."""


MANIFEST_RE = re.compile(
    r"^run/(?P<run_id>[^/]+?)(?<!\.eval)(?<!\.test_baseline)\.json$"
)

PHASES = ["init", "decomposed", "completed"]
PENDING_STATUSES = {"in_progress", "ready_to_commit"}


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


def validate_credentials(obj, source):
    """驗四項憑據（per-subtask 與 Tier 1 manifest 共用單一判定點）。"""
    if obj.get("local_test_passed") is not True:
        raise RuleViolation(f"{source} local_test_passed 非 true：本地測試 gate 未通過，須先完成 step 5 驗證\n"
              f"→ 補救：用 run_verify.py --run-id <run_id> --cmd '<驗證命令>' 執行驗證；Tier 2 逐 task 加 --sub-task <id>")
    evidence = obj.get("local_test_evidence")
    if not (isinstance(evidence, str) and evidence.strip()):
        raise RuleViolation(f"{source} local_test_evidence 為空：須記錄驗證證據（跑了什麼指令、看到什麼結果）\n"
              f"→ 補救：以 run_verify.py 執行並記錄實際驗證，補齊必要仲裁說明")
    reds = obj.get("review_reds")
    if not (isinstance(reds, int) and not isinstance(reds, bool)) or reds < 0:
        raise RuleViolation(f"{source} review_reds 未留痕或非合法非負整數：step 3 須記錄 🔴 數（非負整數）\n"
              f"→ 補救：Tier 2 用 eval_state.py set-review；Tier 1 用 review-run <run_id> <reds> --checked-by <角色> --evidence '<獨立審查憑據>'")
    if obj.get("verify_passed") is not True:
        raise RuleViolation(f"{source} verify_passed 非 true：reviewer 完成度節尚未通過\n"
              f"→ 補救：獨立審查通過後，Tier 2 用 eval_state.py set-verify；Tier 1 用 review-run 加 --passed 記錄結果")


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
        raise RuleViolation(f"{source} 缺 run_id")
    for st in state.get("sub_tasks", []):
        if require_passed:
            name = st.get("name") or st.get("id")
            if st.get("status") != "passed":
                raise RuleViolation(f"{source} sub_task「{name}」status 非 passed（{st.get('status')}）\n"
                      f"→ 補救：該 sub_task 走完循環後 `python3 .agent-flow/scripts/eval_state.py set-status <id> passed`（status 可選 passed／failed／in_progress）")
            validate_credentials(st, f"{source} sub_task「{name}」")



def validate_manifest_basic(m, manifest_path, allow_in_progress=False):
    if not (m.get("spec_path") or m.get("spec_inline")):
        raise RuleViolation(f"{manifest_path} intent gate 未過：spec_path 與 spec_inline 皆空")
    allowed_statuses = ("in_progress", "ready_to_commit", "completed") if allow_in_progress else ("ready_to_commit", "completed")
    if m.get("status") not in allowed_statuses:
        raise RuleViolation(f"{manifest_path} status 非 completed/ready_to_commit（{m.get('status')}），不可 commit")


def validate_manifest_tier(m, manifest_path):
    if m.get("tier") == "hotfix":
        if not isinstance(m.get("debt"), list):
            raise RuleViolation(f"{manifest_path} 為 hotfix 但缺 debt 欄位（欠帳清單，如 [\"test\", \"retro\"]）")
        return True  # hotfix 不走循環評分，豁免 eval 歸檔檔要求；欠帳由 debt gate 追討

    if m.get("tier") == "B":
        if m.get("bootstrap_verified") is not True:
            raise RuleViolation(
                f"{manifest_path} 為 Tier B 但 bootstrap_verified 非 true："
                f"DoD 兩條（本地 build/run 跑得通、測試框架＋示範測試會跑）未驗證，不可 commit"
            )
        return True  # Tier B 不走循環評分，豁免 eval 歸檔檔要求

    return False


def validate_archive(archive, run_id, archive_path):
    if archive.get("run_id") != run_id:
        raise RuleViolation(f"{archive_path} 的 run_id（{archive.get('run_id')}）與 manifest 不一致")
    validate_state(archive, archive_path, require_passed=True)


def require_archive(manifest_path, archive_path):
    raise RuleViolation(f"{manifest_path} 的 {archive_path} 不存在：須先歸檔 eval_state 再 commit\n"
          f"→ 補救：`python3 .agent-flow/scripts/eval_state.py archive` 產出 {archive_path}"
          f"（歸檔檔是冷溯源檔，留在工作目錄即可，不需 git add）")

