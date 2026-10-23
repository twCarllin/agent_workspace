#!/usr/bin/env python3
"""A read-only question must not enter the implementation workflow.

綁定欄位：result、run/<id>.json 的 run_id，以及 Git 工作樹變更清單。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from _common import Checker, changed_paths, load_result, manifests  # noqa: E402


def main(fixture, result_path):
    check = Checker()
    result = load_result(result_path)
    answer = check.result_text(result)
    check.check("回答非空", isinstance(answer, str) and bool(answer.strip()))
    check.check("未建立 run", not manifests(fixture))
    check.check("未修改檔案", not changed_paths(fixture), str(changed_paths(fixture)))
    return check.finish()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
