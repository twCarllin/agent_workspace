#!/usr/bin/env python3
"""Finish an Eval Flow run only after its commit exists.

prepare RUN_ID records the current HEAD after evidence and archive are ready.
finalize RUN_ID verifies the real commit message and records the resulting SHA.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def manifest_path(run_id):
    path = f"run/{run_id}.json"
    if not eval_gates.MANIFEST_RE.fullmatch(path):
        raise ValueError("invalid run ID")
    return path


def save(path, manifest):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temp, path)


def prepare(path, manifest):
    if manifest.get("status") not in ("in_progress", "ready_to_commit"):
        raise ValueError("run is not in progress")
    if os.path.exists("eval_state.json"):
        raise ValueError("archive eval_state.json before preparing the commit")
    eval_gates.check_manifest(path, set(), allow_in_progress=True)
    manifest["status"] = "ready_to_commit"
    try:
        manifest["pre_commit_head"] = git("rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        manifest["pre_commit_head"] = None  # An initial Bootstrap commit has no parent.
    save(path, manifest)
    print(f"[run-commit] {manifest['run_id']} ready_to_commit")


def finalize(path, manifest):
    if manifest.get("status") != "ready_to_commit":
        raise ValueError("run is not ready_to_commit")
    sha = git("rev-parse", "HEAD")
    if sha == manifest.get("pre_commit_head"):
        raise ValueError("HEAD has not changed since prepare")
    message = git("log", "-1", "--format=%B")
    trailers = re.findall(r"^Run-Id:[ \t]*(\S+)[ \t]*$", message, re.MULTILINE)
    if trailers != [manifest["run_id"]]:
        raise ValueError("HEAD commit must have exactly one matching Run-Id trailer")
    manifest["status"] = "completed"
    manifest["phase"] = "completed"
    manifest["commit_sha"] = sha
    manifest["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save(path, manifest)
    print(f"[run-commit] {manifest['run_id']} completed at {sha}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finalize"))
    parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        path = manifest_path(args.run_id)
        manifest = eval_gates.load_json(path)
        if manifest.get("run_id") != args.run_id:
            raise ValueError("manifest run_id does not match filename")
        if args.action == "prepare":
            prepare(path, manifest)
        else:
            finalize(path, manifest)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"[run-commit] {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
