#!/usr/bin/env python3
"""Add a small money API to the fixture before asking the agent to use it."""

from pathlib import Path
import subprocess
import sys


def main(fixture):
    root = Path(fixture)
    (root / "lib").mkdir(exist_ok=True)
    (root / "lib/__init__.py").write_text("", encoding="utf-8")
    (root / "lib/money.py").write_text(
        "from decimal import Decimal, ROUND_HALF_UP\n\n\n"
        "def format_usd(amount: Decimal) -> str:\n"
        "    cents = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n"
        "    return f'${cents:,.2f}'\n",
        encoding="utf-8",
    )
    (root / "lib/receipt.py").write_text(
        '"""Receipt display helpers."""\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "lib"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture money helper"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "tag", "reuse-baseline"], cwd=root, check=True, capture_output=True
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: setup.py <fixture_dir>")
    main(sys.argv[1])
