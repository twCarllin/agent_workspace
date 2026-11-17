#!/usr/bin/env python3
"""Finish an Eval Flow run only after its commit exists.

prepare RUN_ID records the current HEAD after evidence and archive are ready.
commit RUN_ID checks the prepared target and calls Git before finalizing.
finalize RUN_ID verifies the real commit message and records the resulting SHA.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import flow_rules
import run_evidence
import eval_state


def git(*args):
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def manifest_path(run_id):
    path = f"run/{run_id}.json"
    if not flow_rules.MANIFEST_RE.fullmatch(path):
        raise ValueError("invalid run ID")
    return path


def save(path, manifest):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temp, path)


def head():
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def matching_commit(manifest, completed=False):
    sha = head()
    if not sha:
        return False
    message = git("show", "-s", "--format=%B", sha)
    trailers = re.findall(r"^Run-Id:[ \t]*(\S+)[ \t]*$", message, re.MULTILINE)
    if trailers != [manifest["run_id"]]:
        return False
    if completed:
        return sha == manifest.get("commit_sha")
    parents = git("show", "-s", "--format=%P", sha).split()
    expected = manifest.get("pre_commit_head")
    return parents == ([expected] if expected else [])


def scope_check(files):
    scope = set(files)
    if not scope:
        raise ValueError("--files requires an explicit file scope")
    for path in scope:
        if (
            Path(path).is_absolute()
            or ".." in Path(path).parts
            or str(Path(path)) != path
            or path.startswith("-")
            or (Path(path).is_dir() and not Path(path).is_symlink())
        ):
            raise ValueError(f"invalid file scope: {path}")
    staged = set(
        git("diff", "--cached", "--name-only", "-z", "--no-renames").split("\0")
    ) - {""}
    if staged != scope:
        raise ValueError(
            f"staged paths must equal scope; extra={sorted(staged-scope)}, missing={sorted(scope-staged)}"
        )
    dirty = set(git("diff", "--name-only", "-z", "--no-renames").split("\0")) - {""}
    if dirty & scope:
        raise ValueError(
            f"working files differ from staged scope: {sorted(dirty & scope)}"
        )
    return staged


def prepare(path, manifest):
    if manifest.get("status") not in ("in_progress", "ready_to_commit"):
        raise ValueError("run is not in progress")
    if os.path.exists("eval_state.json"):
        raise ValueError("archive eval_state.json before preparing the commit")
    staged = set(
        git("diff", "--cached", "--name-only", "-z", "--no-renames").split("\0")
    ) - {""}
    run_evidence.check_manifest(path, staged, allow_in_progress=True)
    manifest["prepared_index_tree"] = git("write-tree")
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
    parents = git("show", "-s", "--format=%P", sha).split()
    expected = manifest.get("pre_commit_head")
    if parents != ([expected] if expected else []):
        raise ValueError("HEAD is not the commit prepared by this run")
    committed = set(
        git(
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            "--no-renames",
            sha,
        ).split("\0")
    ) - {""}
    run_evidence.check_items(manifest, committed)
    manifest["status"] = (
        "partial" if manifest.get("partial_acceptance") else "completed"
    )
    manifest["phase"] = manifest["status"]
    manifest["commit_sha"] = sha
    manifest["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save(path, manifest)
    eval_state.append_event(
        manifest["run_id"],
        manifest["status"],
        argparse.Namespace(
            run_id=manifest["run_id"],
            commit_sha=sha,
            completed_at=manifest["completed_at"],
        ),
    )
    print(f"[run-commit] {manifest['run_id']} {manifest['status']} at {sha}")
    print(
        "[run-commit] run 已收尾。建議使用者 /clear 後再接下一個需求：同一 session 連跑多個 run，每次呼叫的 context 會持續累積"
    )


def commit(path, manifest, message, files):
    """Commit a prepared target, or recover its existing commit without repeating it."""
    import work_root

    if manifest.get("status") in ("completed", "partial"):
        if not matching_commit(manifest, completed=True):
            raise ValueError("completed run does not match current HEAD and trailer")
        return
    if manifest.get("status") != "ready_to_commit" or "pre_commit_head" not in manifest:
        raise ValueError("run needs prepare before commit")
    if matching_commit(manifest):
        finalize(path, manifest)
        return
    if head() != manifest["pre_commit_head"]:
        raise ValueError("HEAD changed after prepare; cannot create another commit")
    if (
        not manifest.get("prepared_index_tree")
        or git("write-tree") != manifest["prepared_index_tree"]
    ):
        raise ValueError(
            "staged index differs from prepare snapshot; prepare again after verification"
        )
    if not message.strip() or re.search(r"^Run-Id:", message, re.MULTILINE):
        raise ValueError(
            "message must be nonempty and must not contain a Run-Id trailer"
        )
    work_root.require_commit_hook(Path.cwd())
    staged = scope_check(files)
    run_evidence.check_manifest(path, staged)
    # Git invokes the target's real hook once. Never run custom hooks as a probe.
    result = subprocess.run(
        ["git", "commit", "-m", message + "\n\nRun-Id: " + manifest["run_id"]],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError(
            f"git commit failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    if result.stdout:
        print(result.stdout, end="")
    if not matching_commit(manifest):
        raise ValueError("new commit parent/trailer mismatch; cannot finalize")
    finalize(path, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "commit", "finalize"))
    parser.add_argument("run_id")
    parser.add_argument("--message")
    parser.add_argument("--files", nargs="+")
    args = parser.parse_args()
    import work_root

    work_root.check_cli(toolchain=True)
    try:
        path = manifest_path(args.run_id)
        manifest = run_evidence.load_json(path)
        if manifest.get("run_id") != args.run_id:
            raise ValueError("manifest run_id does not match filename")
        if args.action == "prepare":
            prepare(path, manifest)
        elif args.action == "commit":
            if args.message is None or not args.files:
                raise ValueError("commit requires --message and --files")
            commit(path, manifest, args.message, args.files)
        else:
            finalize(path, manifest)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"[run-commit] {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
