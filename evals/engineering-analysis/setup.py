#!/usr/bin/env python3
"""Create executable order flow and a historical decision in an isolated fixture."""

from pathlib import Path
import subprocess
import sys


def main(fixture):
    root = Path(fixture)
    (root / "pricing.py").write_text(
        '"""Prices in cents."""\n\n'
        "def total(price, discount):\n"
        "    return price * 110 // 100 - discount\n",
        encoding="utf-8",
    )
    (root / "valid_pricing.py").write_text(
        '"""Same historical rule, still implemented in the correct order."""\n'
        'import json\nprint(json.dumps({"discount": (1000 - 200) * 110 // 100}))\n',
        encoding="utf-8",
    )
    (root / "receipt.py").write_text(
        'def render(total):\n    return f"receipt:{total}"\n', encoding="utf-8"
    )
    (root / "ledger.py").write_text(
        'def record(total):\n    return f"ledger:{total}"\n', encoding="utf-8"
    )
    (root / "app.py").write_text(
        "import json\nfrom pricing import total\nfrom receipt import render\n"
        "from ledger import record\n\n"
        "def run(price, discount):\n"
        "    value = total(price, discount)\n"
        '    return {"net": value, "receipt": render(value), "ledger": record(value)}\n\n'
        'if __name__ == "__main__":\n'
        '    print(json.dumps({"standard": run(1000, 0), "discount": run(1000, 200)}))\n',
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "pricing.py",
            "valid_pricing.py",
            "receipt.py",
            "ledger.py",
            "app.py",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "Apply discount before tax for every order"],
        cwd=root,
        check=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: setup.py <fixture_dir>")
    main(sys.argv[1])
