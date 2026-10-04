#!/usr/bin/env python3
"""Record an index checkpoint and print a reviewed-to-current diff; never approves code."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(['git', '--literal-pathspecs', *args], check=True,
                          text=True, capture_output=True).stdout


def contract_hash(paths):
    digest = hashlib.sha256()
    for name in sorted(paths):
        path = Path(name)
        digest.update(name.encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def valid_paths(paths):
    if not paths or any(Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
        raise ValueError('files must be nonempty repository-relative paths')
    return sorted(set(paths))


def capture(path, files, contracts):
    data = {'schema': 1, 'tree': git('write-tree').strip(), 'files': valid_paths(files),
            'contracts': valid_paths(contracts), 'contract_hash': contract_hash(contracts),
            'review_session': None}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')
    return data


def mark_reviewed(path, session):
    data = json.loads(path.read_text())
    if not session.strip() or data['tree'] != git('write-tree').strip() or data['contract_hash'] != contract_hash(data['contracts']):
        raise ValueError('index/contract changed during review, or reviewer session missing')
    data['review_session'] = session
    path.write_text(json.dumps(data, indent=2) + '\n')


def diff(path, files, contracts):
    files, contracts = valid_paths(files), valid_paths(contracts)
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError('invalid checkpoint structure')
        if (data.get('schema') != 1 or not data.get('review_session') or
            data.get('files') != files or data.get('contracts') != contracts or
            data.get('contract_hash') != contract_hash(contracts)):
            raise ValueError('unreviewed checkpoint or changed scope/contract')
        tree = data['tree']
        if not isinstance(tree, str) or len(tree) != 40 or any(c not in '0123456789abcdef' for c in tree):
            raise ValueError('invalid tree')
        git('cat-file', '-e', tree + '^{tree}')
        return 'delta', git('diff', tree, git('write-tree').strip(), '--', *files)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return 'full', git('diff', '--cached', '--', *files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'reviewed', 'diff'))
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--files', nargs='+')
    parser.add_argument('--contracts', nargs='+')
    parser.add_argument('--session')
    args = parser.parse_args()
    try:
        if args.action == 'reviewed':
            mark_reviewed(args.checkpoint, args.session or '')
        elif not args.files or not args.contracts:
            parser.error('--files and --contracts required')
        elif args.action == 'capture':
            capture(args.checkpoint, args.files, args.contracts)
        else:
            mode, output = diff(args.checkpoint, args.files, args.contracts)
            print(f'[review-delta] mode={mode}', file=sys.stderr)
            sys.stdout.write(output)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'[review-delta] {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
