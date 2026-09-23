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
