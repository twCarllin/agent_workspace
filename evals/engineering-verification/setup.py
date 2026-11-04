#!/usr/bin/env python3
"""Create producer and stale consumer as separate processes."""

from pathlib import Path
import subprocess
import sys


def main(fixture):
    root = Path(fixture)
    (root / "producer.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        'Path(sys.argv[1]).write_text(json.dumps({"total": int(sys.argv[2])}))\n',
        encoding="utf-8",
    )
    (root / "consumer.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        'print(json.loads(Path(sys.argv[1]).read_text())["total"])\n',
        encoding="utf-8",
    )
    (root / "valid_consumer.py").write_text(
        "# Historical rule: producer and consumer share total_cents.\n"
        "import json, sys\nfrom pathlib import Path\n"
        'print(json.loads(Path(sys.argv[1]).read_text())["total_cents"])\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "producer.py", "consumer.py", "valid_consumer.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "Consumer reads total from producer output"],
        cwd=root,
        check=True,
    )
    producer = root / "producer.py"
    producer.write_text(
        producer.read_text(encoding="utf-8").replace('"total"', '"total_cents"'),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "producer.py"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Migrate producer output"],
        cwd=root,
        check=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: setup.py <fixture_dir>")
    main(sys.argv[1])
