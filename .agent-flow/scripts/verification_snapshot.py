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
