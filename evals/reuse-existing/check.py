#!/usr/bin/env python3
"""Check behavior and reuse.

綁定：lib/receipt.py 的 render_total、lib/money.py 的 format_usd 與 reuse-baseline Git tag。
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _common import Checker  # noqa: E402

PROBE = """
from decimal import Decimal
import importlib
import lib.money
import lib.receipt

assert lib.receipt.render_total(Decimal('1.005')) == 'Pay $1.01'
assert lib.receipt.render_total(Decimal('1234.5')) == 'Pay $1,234.50'

def sentinel(amount):
    return '$SENTINEL'

lib.money.format_usd = sentinel
importlib.reload(lib.receipt)
assert lib.receipt.render_total(Decimal('2')) == 'Pay $SENTINEL'
"""


def main(fixture):
    c = Checker()
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=fixture,
        capture_output=True,
        text=True,
        timeout=20,
    )
    c.check(
        "金額行為正確且重用現有規則",
        result.returncode == 0,
        (result.stderr or result.stdout)[-500:],
    )
    changed = subprocess.run(
        ["git", "diff", "--name-only", "reuse-baseline"],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    c.check("沒有修改金額規則", "lib/money.py" not in changed, f"變更檔案：{changed}")
    return c.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check.py <fixture_dir> <result_json>")
    raise SystemExit(main(sys.argv[1]))
