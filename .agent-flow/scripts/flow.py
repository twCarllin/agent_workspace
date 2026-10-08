#!/usr/bin/env python3
"""Local Flow operations. Evidence remains governed by existing Eval Flow gates."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_rules
import run_evidence
import run_commit

SCRIPTS = Path(__file__).resolve().parent
TERMINAL = {'completed', 'aborted', 'failed'}


def read(path):
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected JSON object')
    return value


def select_run(run_id=None):
    if run_id:
        path = run_commit.manifest_path(run_id)
        manifest = read(path)
        if manifest.get('run_id') != run_id:
            raise ValueError('manifest run_id does not match filename')
        return path, manifest
    candidates = []
    for path in sorted(Path('run').glob('*.json')):
        if not flow_rules.MANIFEST_RE.fullmatch(str(path)):
            continue
        manifest = read(path)
        if (manifest.get('run_id') == path.stem
                and manifest.get('status') in ('in_progress', 'ready_to_commit')):
            candidates.append((str(path), manifest))
    if len(candidates) != 1:
        raise ValueError(f'expected one active run, found {len(candidates)}; use --run-id')
    return candidates[0]


def records(path):
    if not Path(path).exists():
        return []
    result = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                result.append(item)
    return result


def status(run_id=None):
    _, manifest = select_run(run_id)
    run_id = manifest['run_id']
    state = None
    if Path('eval_state.json').exists():
        hot = read('eval_state.json')
        if hot.get('run_id') == run_id:
            state = hot
    archive = Path(f'run/{run_id}.eval.json')
    if state is None and archive.exists():
        state = read(archive)
        if state.get('run_id') != run_id:
            raise ValueError('archive run_id mismatch')
    tasks = state.get('sub_tasks', []) if state else []
    events = records(f'run/{run_id}.events.jsonl')
    dispatch = [item for item in records(f'run/{run_id}.dispatch.jsonl')
                if item.get('run_id', run_id) == run_id]
    error = manifest.get('finish_error') or manifest.get('failed_reason') or manifest.get('error_reason')
    if not error:
        commands = manifest.get('verification_commands', [])
        if commands and commands[-1].get('exit_code') not in (None, 0):
            error = f"verification failed: {commands[-1].get('command')} (exit {commands[-1]['exit_code']})"
    if not error:
        failed = [task for task in tasks if task.get('status') == 'failed']
        if failed:
            error = failed[0].get('failed_reason') or failed[0].get('error_reason') or f"task {failed[0].get('id')} failed"
        elif dispatch and dispatch[-1].get('exit_code') not in (None, 0):
            error = dispatch[-1].get('error') or dispatch[-1].get('stderr') or f"dispatch failed (exit {dispatch[-1]['exit_code']})"
    elapsed = None
    elapsed_now = None
    start = manifest.get('created_at')
    end = manifest.get('completed_at') or (events[-1].get('ts') if events else None)
    if start:
        try:
            created = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
            elapsed_now = max(0, (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds())
        except (ValueError, TypeError):
            pass
    if start and end:
        try:
            elapsed = max(0, (datetime.datetime.fromisoformat(end.replace('Z', '+00:00'))
                              - datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds())
        except (ValueError, TypeError):
            pass
    current = [task for task in tasks if task.get('status') != 'passed']
    commands = manifest.get('verification_commands', [])
    latest_verification = commands[-1] if commands else None
    recorded = manifest.get('status')
    next_action = ('done; push only when requested' if recorded == 'completed' else
                   'resume finish or finalize the existing commit' if recorded == 'ready_to_commit' else
                   'resolve recorded error' if error else
                   'resume the recorded task; complete review and verification evidence')
    return dict(run_id=run_id, status=recorded, phase=manifest.get('phase'),
                tasks=current, error_reason=error, recorded_elapsed_seconds=elapsed,
                elapsed_seconds=elapsed if recorded == 'completed' else elapsed_now,
                last_event=events[-1] if events else None,
                last_dispatch=dispatch[-1] if dispatch else None, latest_verification=latest_verification,
                review_evidence=dict(review_reds=manifest.get('review_reds'),
                                     verify_passed=manifest.get('verify_passed')), next_action=next_action)


def emit(value, as_json=False):
    if as_json:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)
    else:
        print(f"{value['run_id']}: {value['status']} / {value.get('phase')}\n"
              f"tasks: {json.dumps(value['tasks'], ensure_ascii=False)}\n"
              f"wall elapsed: {value['elapsed_seconds']} s; recorded elapsed: {value['recorded_elapsed_seconds']} s\n"
              f"reason: {value['error_reason']}\n"
              f"last event: {json.dumps(value['last_event'], ensure_ascii=False)}\n"
              f"last dispatch: {json.dumps(value['last_dispatch'], ensure_ascii=False)}\n"
              f"review: {json.dumps(value['review_evidence'], ensure_ascii=False)}\n"
              f"verification: {json.dumps(value['latest_verification'], ensure_ascii=False)}\n"
              f"next: {value['next_action']}", flush=True)


def call(*argv):
    result = subprocess.run(list(argv), text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end='', flush=True)
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr, flush=True)
    if result.returncode:
        raise ValueError(f"command failed (exit {result.returncode}): "
                         + (result.stderr or result.stdout or ' '.join(argv)).strip())
    return result.stdout.strip()


def git(*argv):
    result = subprocess.run(['git', *argv], text=True, capture_output=True)
    if result.returncode:
        raise ValueError(f'git failed (exit {result.returncode}): {result.stderr.strip()}')
    return result.stdout.strip()


def head():
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def matching_commit(manifest, completed=False):
    sha = head()
    if not sha:
        return False
    message = git('show', '-s', '--format=%B', sha)
    trailers = re.findall(r'^Run-Id:[ \t]*(\S+)[ \t]*$', message, re.MULTILINE)
    if trailers != [manifest['run_id']]:
        return False
    if completed:
        return sha == manifest.get('commit_sha')
    parents = git('show', '-s', '--format=%P', sha).split()
    expected = manifest.get('pre_commit_head')
    return parents == ([expected] if expected else [])


def scope_check(files):
    scope = set(files)
    if not scope:
        raise ValueError('--files requires an explicit file scope')
    for path in scope:
        if (Path(path).is_absolute() or '..' in Path(path).parts
                or str(Path(path)) != path or path.startswith('-') or Path(path).is_dir()):
            raise ValueError(f'invalid file scope: {path}')
    staged = set(git('diff', '--cached', '--name-only', '-z', '--no-renames').split('\0')) - {''}
    if staged != scope:
        raise ValueError(f'staged paths must equal scope; extra={sorted(staged-scope)}, missing={sorted(scope-staged)}')
    dirty = set(git('diff', '--name-only', '-z', '--no-renames').split('\0')) - {''}
    if dirty & scope:
        raise ValueError(f'working files differ from staged scope: {sorted(dirty & scope)}')
    return staged


def push():
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
    if not branch:
        raise ValueError('push requires a branch')
    git('remote', 'get-url', 'origin')
    call('git', 'push', 'origin', branch)


def validate_tasks(state, source):
    tasks = state.get('sub_tasks')
    if not isinstance(tasks, list) or not tasks or not all(isinstance(task, dict) for task in tasks):
        raise ValueError(f'{source}: sub_tasks must be a nonempty list of task objects')
    flow_rules.validate_state(state, source, require_passed=True)


def finish(args):
    path, manifest = select_run(args.run_id)
    lock = Path(git('rev-parse', '--git-common-dir')).resolve() / 'flow-finish.lock'
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(descriptor, f'{os.getpid()} {args.run_id}\n'.encode())
    os.close(descriptor)
    try:
        if manifest.get('status') == 'completed':
            if not matching_commit(manifest, completed=True):
                raise ValueError('completed run does not match current HEAD and trailer')
        elif manifest.get('status') == 'ready_to_commit' and matching_commit(manifest):
            run_commit.finalize(path, manifest)
        else:
            if manifest.get('status') not in ('in_progress', 'ready_to_commit'):
                raise ValueError('run is not active')
            if manifest.get('status') == 'ready_to_commit' and head() != manifest.get('pre_commit_head'):
                raise ValueError('HEAD changed after prepare; cannot create another commit')
            files = args.files or manifest.get('finish_files')
            if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
                raise ValueError('--files requires an explicit file scope')
            scope_check(files)
            hot = Path('eval_state.json')
            if hot.exists():
                state = read(hot)
                if state.get('run_id') != args.run_id:
                    raise ValueError('eval_state run_id mismatch; cannot verify or archive another run')
                validate_tasks(state, str(hot))
            command = args.verify_command or manifest.get('test_command')
            if not isinstance(command, str) or not command.strip():
                raise ValueError('provide --verify-command or manifest test_command')
            # Review evidence is checked before spending time on full verification.
            if not hot.exists() and manifest.get('tier') in (1, '1'):
                flow_rules.validate_credentials(manifest, path)
            elif not hot.exists():
                archive = read(f"run/{args.run_id}.eval.json")
                if archive.get('run_id') != args.run_id:
                    raise ValueError('archive run_id mismatch')
                validate_tasks(archive, 'archive')
            verify_args = [sys.executable, str(SCRIPTS / 'run_verify.py'), '--run-id', args.run_id, '--cmd', command]
            if args.reuse:
                verify_args.append('--reuse')
            call(*verify_args)
            scope_check(files)
            if hot.exists():
                if read(hot).get('run_id') != args.run_id:
                    raise ValueError('eval_state run_id changed during verification')
                call(sys.executable, str(SCRIPTS / 'eval_state.py'), 'archive')
            manifest = read(path)
            manifest['finish_files'] = files
            manifest.pop('finish_error', None)
            run_commit.save(path, manifest)
            run_commit.prepare(path, manifest)
            staged = scope_check(files)
            run_evidence.check_manifest(path, staged, allow_in_progress=True)
            message = args.message
            if re.search(r'^Run-Id:', message, re.MULTILINE):
                raise ValueError('--message must not contain a Run-Id trailer')
            call('git', 'commit', '-m', message + '\n\nRun-Id: ' + args.run_id)
            if not matching_commit(manifest):
                raise ValueError('new commit parent/trailer mismatch; cannot finalize')
            run_commit.finalize(path, manifest)
        if args.push:
            push()
        current = read(path)
        if 'finish_error' in current:
            current.pop('finish_error')
            run_commit.save(path, current)
    except (ValueError, OSError, SystemExit) as error:
        current = read(path)
        current['finish_error'] = str(error)
        run_commit.save(path, current)
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    import review_packet
    review_packet.parser_arguments(commands.add_parser('review-packet'))
    pre = commands.add_parser('preflight')
    pre.add_argument('--harness', choices=('codex', 'claude'), default='codex')
    pre.add_argument('--run-id')
    pre.add_argument('--live', action='store_true')
    pre.add_argument('--timeout', type=float, default=30)
    pre.add_argument('--json', action='store_true')
    for name in ('status', 'watch'):
        sub = commands.add_parser(name)
        sub.add_argument('--run-id')
        sub.add_argument('--json', action='store_true')
        if name == 'watch':
            sub.add_argument('--timeout', type=float, default=30)
            sub.add_argument('--interval', type=float, default=1)
    link = commands.add_parser('worktree-link')
    link.add_argument('--root', default='.')
    end = commands.add_parser('finish')
    end.add_argument('--run-id', required=True)
    end.add_argument('--message', required=True)
    end.add_argument('--files', nargs='+')
    end.add_argument('--verify-command')
    end.add_argument('--push', action='store_true')
    end.add_argument('--reuse', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'review-packet':
            return review_packet.execute(args)
        if args.command == 'preflight':
            import flow_preflight
            result = flow_preflight.preflight(harness=args.harness, run_id=args.run_id,
                                              live=args.live, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return {'ready': 0, 'blocked': 1, 'unknown': 2}.get(result.get('readiness'), 2)
        if args.command == 'worktree-link':
            import worktree_link
            created = worktree_link.ensure_links(args.root)
            print('已為 worktree 建立工具鏈連結：' + ', '.join(created) if created else '無需建立連結')
            return 0
        if args.command == 'finish':
            finish(args)
            return 0
        if args.command == 'status':
            emit(status(args.run_id), args.json)
            return 0
        if not (0 < args.timeout <= 3600 and 0.05 <= args.interval <= 60):
            raise ValueError('watch timeout must be 0..3600 seconds; interval 0.05..60 seconds')
        _, manifest = select_run(args.run_id)
        deadline, previous = time.monotonic() + args.timeout, None
        while True:
            value = status(manifest['run_id'])
            signature = json.dumps({key: item for key, item in value.items() if key != 'elapsed_seconds'}, sort_keys=True)
            if signature != previous:
                emit(value, args.json)
                previous = signature
            if value['status'] in TERMINAL or time.monotonic() >= deadline:
                return 0
            time.sleep(min(args.interval, max(0, deadline-time.monotonic())))
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f'[flow] {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
