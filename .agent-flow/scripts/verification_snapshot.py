"""Hash the source tree state that a verification command observed."""
import hashlib
import os
import subprocess


def snapshot():
    digest = hashlib.sha256()
    tracked = subprocess.run(["git", "diff", "HEAD", "--binary"], check=True, capture_output=True).stdout
    digest.update(tracked)
    names = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        check=True, capture_output=True,
    ).stdout
    for raw_path in sorted(path for path in names.split(b"\0") if path):
        path = os.fsdecode(raw_path)
        if not os.path.isfile(path):
            continue
        digest.update(raw_path + b"\0")
        with open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def input_snapshot():
    """Hash actual verification inputs, independently of Git HEAD and index."""
    import stat

    digest = hashlib.sha256()
    names = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True, capture_output=True,
    ).stdout
    for raw_path in sorted(set(names.split(b"\0")) - {b""}):
        path = os.fsdecode(raw_path)
        if path == "eval_state.json" or path.startswith(("run/", "task/")):
            continue
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            continue  # Deleted tracked inputs are absent from the actual tree.
        link = stat.S_ISLNK(metadata.st_mode)
        pure_doc = path in ("README.md", "TODO.md", "CHANGELOG.md") or (
            path.startswith("docs/") and path.endswith(".md"))
        if pure_doc and not link:
            continue
        digest.update(raw_path + b"\0" + str(stat.S_IMODE(metadata.st_mode)).encode() + b"\0")
        if link:
            data = os.fsencode(os.readlink(path))
            digest.update(b"link\0" + str(len(data)).encode() + b"\0" + data)
            resolved = os.path.realpath(path)
            if os.path.commonpath((os.getcwd(), resolved)) != os.getcwd():
                raise OSError(f"External verification symlink: {path}")
            if os.path.isfile(resolved):
                target = os.stat(resolved)
                digest.update(b"target\0" + str(stat.S_IMODE(target.st_mode)).encode()
                              + b"\0" + str(target.st_size).encode() + b"\0")
                with open(resolved, "rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"file\0" + str(metadata.st_size).encode() + b"\0")
            with open(path, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        else:
            raise OSError(f"Unsupported verification input: {path}")
    return digest.hexdigest()


def check_nested_repositories():
    """Reject nested inputs that cannot be safely represented by this snapshot."""
    tracked = subprocess.run(
        ['git', 'ls-files', '--stage', '-z'], check=True, capture_output=True).stdout
    for entry in tracked.split(b'\0'):
        if entry.startswith(b'160000 '):
            path = os.fsdecode(entry.split(b'\t', 1)[1])
            raise OSError(f'Tracked gitlink verification is unsupported: {path}; '
                          'verify the checkout with an explicit supported snapshot strategy. '
                          'Git ignore rules cannot exclude tracked inputs.')
    names = subprocess.run(
        ['git', 'ls-files', '--others', '--exclude-standard', '-z'],
        check=True, capture_output=True).stdout
    for raw_path in sorted(set(names.split(b'\0')) - {b''}):
        path = os.fsdecode(raw_path).rstrip('/')
        if os.path.isdir(path) and os.path.lexists(os.path.join(path, '.git')):
            raise OSError(f'Untracked nested repository: {path}; obtain approval to '
                          'exclude this directory with Git ignore policy, or move it '
                          'outside the project. No directory or ignore policy was changed.')


def input_snapshot_v2():
    """v1 actual inputs plus explicit nested repository and ignore-policy checks."""
    check_nested_repositories()
    digest = hashlib.sha256(b'inputs-v2\0' + input_snapshot().encode())
    # Local and global ignore policy affects which untracked inputs are observed.
    # Include policy bytes in the digest, but never publish their contents.
    exclude = subprocess.run(['git', 'rev-parse', '--git-path', 'info/exclude'],
                             check=True, capture_output=True).stdout.rstrip(b'\n')
    config = subprocess.run(['git', 'config', '--path', '--get', 'core.excludesfile'],
                            capture_output=True)
    if config.returncode not in (0, 1):
        raise OSError('Unable to read effective Git ignore policy')
    global_path = config.stdout.rstrip(b'\n') if config.returncode == 0 else os.fsencode(
        os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), 'git/ignore'))
    for label, raw_path in ((b'local', exclude), (b'global', global_path)):
        digest.update(label + b'\0' + raw_path + b'\0')
        try:
            with open(os.fsdecode(raw_path), 'rb') as stream:
                digest.update(b'present\0')
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        except FileNotFoundError:
            digest.update(b'absent\0')
    return digest.hexdigest()
