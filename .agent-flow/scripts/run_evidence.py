"""Read run evidence and validate it without hook output or telemetry."""

import glob
import hashlib
import json
import os
import subprocess

from flow_rules import (
    RuleViolation,
    adaptive_tier1,
    plan_timestamp,
    validate_self_review,
    MANIFEST_RE,
    validate_credentials,
    validate_state,
    validate_manifest_basic,
    validate_manifest_tier,
    validate_archive,
    require_archive,
)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, dict):
            raise RuleViolation(f"{path} 內容不是 JSON 物件")
        return value
    except (OSError, json.JSONDecodeError) as e:
        raise RuleViolation(f"{path} 無法讀取或非合法 JSON（{e}）")


def load_json_quiet(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def find_unique_tier1_inprogress():
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


def validate_evidence_snapshot(manifest, source):
    if manifest.get("evidence_schema") != 2 or manifest.get("tier") in ("B", "hotfix"):
        return  # Existing runs keep their original evidence contract.
    commands = manifest.get("verification_commands") or []
    latest = commands[-1] if commands else {}
    if latest.get("exit_code") != 0 or not latest.get("snapshot"):
        raise RuleViolation(
            f"{source} 缺通過的收尾驗證快照；依 tier 與專案要求用 run_verify.py 重新驗證"
        )
    try:
        import verification_snapshot

        kind = latest.get("snapshot_kind")
        if kind is None:
            current = verification_snapshot.snapshot()
        elif kind == "inputs-v1":
            current = verification_snapshot.input_snapshot()
        elif kind == "inputs-v2":
            current = verification_snapshot.input_snapshot_v2()
        else:
            raise RuleViolation(f"{source} 未知驗證快照格式：{kind}")
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuleViolation(f"{source} 無法核對驗證快照：{error}")
    if current != latest["snapshot"]:
        raise RuleViolation(f"{source} 驗證後程式樹已變更；請重新驗證")


def review_contract_snapshot(manifest):
    """Bind explicit contract inputs even when Git ignores their paths."""
    contract = {
        key: manifest.get(key)
        for key in ("task_file", "spec_path", "spec_inline", "plan_authorization")
    }
    if not (contract["spec_path"] or contract["spec_inline"]):
        raise RuleViolation("缺自查需求來源")
    if manifest.get("plan_recorded_at") and not (
        isinstance(contract["plan_authorization"], str)
        and contract["plan_authorization"].strip()
    ):
        raise RuleViolation("缺自查授權來源")
    for key in ("task_file", "spec_path"):
        path = contract[key]
        if key == "spec_path" and path is None:
            continue
        if not isinstance(path, str) or not path.strip():
            raise RuleViolation(f"缺自查來源：{key}")
        try:
            with open(path, "rb") as stream:
                contract[key + "_digest"] = hashlib.sha256(stream.read()).hexdigest()
        except OSError as error:
            raise RuleViolation(f"無法讀取自查來源：{key} {path}（{error}）") from error
    return hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def review_source_snapshot(manifest):
    """Bind actual files, including pure documentation, independently of HEAD."""
    names = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    digest = hashlib.sha256()
    for raw_path in sorted(set(names.split(b"\0")) - {b""}):
        path = os.fsdecode(raw_path)
        if path == "eval_state.json" or path.startswith("run/"):
            continue  # Evidence updates must not invalidate their own binding.
        if not os.path.lexists(path):
            continue
        metadata = os.lstat(path)
        digest.update(raw_path + b"\0" + str(metadata.st_mode).encode() + b"\0")
        if os.path.islink(path):
            digest.update(os.fsencode(os.readlink(path)))
        elif os.path.isfile(path):
            with open(path, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        else:
            raise RuleViolation(f"無法綁定自查來源：{path}")
    tree = subprocess.run(
        ["git", "write-tree"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return {
        "source_digest": digest.hexdigest(),
        "index_tree": tree,
        "contract_digest": review_contract_snapshot(manifest),
    }


def validate_review(manifest, source):
    """All completion paths use the same self-review authorization and binding."""
    if manifest.get("checked_by") == "self":
        validate_self_review(manifest)
        validate_evidence_snapshot(manifest, source)
        latest = manifest["verification_commands"][-1]
        expected = {
            "snapshot": latest["snapshot"],
            "snapshot_kind": latest.get("snapshot_kind"),
            "plan_recorded_at": plan_timestamp(manifest),
        }
        expected.update(review_source_snapshot(manifest))
        binding = manifest.get("self_review_snapshot")
        if not isinstance(binding, dict) or any(
            binding.get(key) != value for key, value in expected.items()
        ):
            raise RuleViolation(f"{source} 自查來源或計畫已變更；請重新自查")
        count = binding.get("verification_count")
        history = manifest["verification_commands"]
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 1 <= count <= len(history)
        ):
            raise RuleViolation(f"{source} 缺自查驗證綁定")
        if any(
            record.get("exit_code") != 0
            or record.get("snapshot") != binding["snapshot"]
            or record.get("snapshot_kind") != binding.get("snapshot_kind")
            for record in history[count - 1 :]
        ):
            raise RuleViolation(f"{source} 自查後驗證失敗或來源變更；請重新自查")
    elif adaptive_tier1(manifest):
        reviewer = manifest.get("checked_by")
        independent = isinstance(reviewer, str) and reviewer.startswith("reviewer:")
        if manifest.get("review_reasons") and not independent:
            raise RuleViolation(f"{source} 具名原因需要獨立 code-reviewer")
        if not reviewer or not str(manifest.get("review_evidence") or "").strip():
            raise RuleViolation(f"{source} 缺審查者或審查證據")


def check_item_plan(manifest):
    """Read the current task and verify its frozen HITL item scope."""
    import flow_rules
    import item_accounting

    if not flow_rules.requires_item_accounting(manifest):
        return
    task_path = manifest.get("task_file")
    if not isinstance(task_path, str) or not task_path:
        raise RuleViolation("缺 task_file：無法核對確認 item")
    try:
        with open(task_path, encoding="utf-8") as stream:
            task_text = stream.read()
    except OSError as error:
        raise RuleViolation(f"無法讀取 task_file：{task_path}（{error}）") from error
    item_accounting.validate_plan(manifest, task_text)


def check_items(manifest, files):
    """Check the frozen scope against task text and actual delivery paths."""
    import flow_rules
    import item_accounting

    if not flow_rules.requires_item_accounting(manifest):
        return
    check_item_plan(manifest)
    acceptance = manifest.get("partial_acceptance")
    unresolved = item_accounting.validate_results(
        manifest, files=files, allow_pending=acceptance is not None
    )
    if acceptance is not None:
        if not isinstance(acceptance, dict):
            raise RuleViolation("partial_acceptance 格式錯誤")
        item_accounting.validate_ruling(acceptance.get("ruling"))
        if not unresolved or acceptance.get("item_ids") != unresolved:
            raise RuleViolation("partial 清單須等於全部未交付 item")
    if manifest.get("status") == "completed" and unresolved:
        raise RuleViolation("partial 不可標為 completed")


def check_manifest(manifest_path, staged, allow_in_progress=False):
    m = load_json(manifest_path)
    run_id = MANIFEST_RE.match(manifest_path).group("run_id")
    validate_manifest_basic(m, manifest_path, allow_in_progress)
    check_items(m, staged)
    validate_evidence_snapshot(m, manifest_path)
    validate_review(m, manifest_path)
    if validate_manifest_tier(m, manifest_path):
        return
    archive_path = f"run/{run_id}.eval.json"
    if archive_path in staged or os.path.exists(archive_path):
        validate_archive(load_json(archive_path), run_id, archive_path)
    elif m.get("tier") in (1, "1"):
        validate_credentials(m, manifest_path)
    else:
        require_archive(manifest_path, archive_path)
