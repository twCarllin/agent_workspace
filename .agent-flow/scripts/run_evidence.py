"""Read run evidence and validate it without hook output or telemetry."""
import glob
import json
import os
import subprocess

from flow_rules import (RuleViolation, MANIFEST_RE, validate_credentials,
                        validate_state, validate_manifest_basic, validate_manifest_tier,
                        validate_archive, require_archive)


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
        raise RuleViolation(f"{source} 缺通過的收尾驗證快照；依 tier 與專案要求用 run_verify.py 重新驗證")
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



def check_manifest(manifest_path, staged, allow_in_progress=False):
    m = load_json(manifest_path)
    run_id = MANIFEST_RE.match(manifest_path).group("run_id")
    validate_manifest_basic(m, manifest_path, allow_in_progress)
    validate_evidence_snapshot(m, manifest_path)
    if validate_manifest_tier(m, manifest_path):
        return
    archive_path = f"run/{run_id}.eval.json"
    if archive_path in staged or os.path.exists(archive_path):
        validate_archive(load_json(archive_path), run_id, archive_path)
    elif m.get("tier") in (1, "1"):
        validate_credentials(m, manifest_path)
    else:
        require_archive(manifest_path, archive_path)
