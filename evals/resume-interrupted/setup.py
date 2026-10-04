#!/usr/bin/env python3
"""S3 中斷現場：在 fixture 內造一個 Tier 2 run，task 1 已 passed、task 2 卡在 step reviewing、
staging 有未提交的實作檔。這是 TODO 第 15 節 Game day 的載體（fixture 演練，不 kill 真 run）。

綁定：manifest `status`／`phase`／`task_file`／`hitl_confirmed_at`；eval_state.json `sub_tasks[].status`／`step`／`files`
（鍵集對齊 .claude/hooks/eval_state.py 的 add-subtask 骨架）。
用法：python3 setup.py <fixture_dir>
"""
import json
import os
import subprocess
import sys

RUN_ID = "2026-10-01-greeting-module"


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def subtask(id_, name, status, step, files):
    return {"id": id_, "name": name, "status": status, "step": step, "files": files, "warning": False,
            "local_test_passed": status == "passed", "local_test_evidence": "pytest tests/test_greeting_core.py -q → 3 passed" if status == "passed" else None,
            "verification_commands": [], "review_reds": 0 if status == "passed" else None,
            "verify_passed": status == "passed", "review_dimensions": None,
            "checked_by": "checker" if status == "passed" else None}


def main(fixture):
    w(os.path.join(fixture, "spec", f"{RUN_ID}.md"),
      "# Spec — greeting 模組\n\n## §1 需求\n\n提供 `lib/greeting.py`：`greet(name)` 回 `Hello, <name>!`；"
      "`farewell(name)` 回 `Bye, <name>!`。兩者皆須有單元測試。\n\n## §2 不變量\n\n1. 空字串 name → 拋 ValueError。\n")
    w(os.path.join(fixture, "task", "2026-10-01.md"),
      f"Run-Id: `{RUN_ID}`（Tier 2；Spec：`spec/{RUN_ID}.md`）\n\n## Task 1：greet\n\n- [x] 1.1 `greet(name)`＋測試  files: lib/greeting.py, tests/test_greeting_core.py\n"
      "      DoD: `greet('Ann')=='Hello, Ann!'`；空字串拋 ValueError；pytest 綠\n\n"
      "## Task 2：farewell\n\n- [ ] 2.1 `farewell(name)`＋測試  files: lib/greeting.py, tests/test_greeting_farewell.py\n"
      "      DoD: `farewell('Ann')=='Bye, Ann!'`；空字串拋 ValueError；pytest 綠\n")
    w(os.path.join(fixture, "lib", "__init__.py"), "")
    greet_only = ("def _require(name):\n    if not name:\n        raise ValueError('name 不可為空')\n\n\n"
                  "def greet(name):\n    _require(name)\n    return f'Hello, {name}!'\n")
    w(os.path.join(fixture, "lib", "greeting.py"), greet_only)
    w(os.path.join(fixture, "tests", "test_greeting_core.py"),
      "import pytest\nfrom lib.greeting import greet\n\n\ndef test_greet():\n    assert greet('Ann') == 'Hello, Ann!'\n\n\n"
      "def test_greet_empty():\n    with pytest.raises(ValueError):\n        greet('')\n\n\ndef test_greet_type():\n    assert isinstance(greet('x'), str)\n")
    w(os.path.join(fixture, "tests", "test_greeting_farewell.py"),
      "import pytest\nfrom lib.greeting import farewell\n\n\ndef test_farewell():\n    assert farewell('Ann') == 'Bye, Ann!'\n\n\n"
      "def test_farewell_empty():\n    with pytest.raises(ValueError):\n        farewell('')\n")
    # task 1 已 commit（task/ 與 run/ 依 .gitignore 不進版控，與真實部署一致）；task 2 中斷在 step 3 審查中
    subprocess.run(["git", "add", "lib/__init__.py", "lib/greeting.py", "tests/test_greeting_core.py", "spec"],
                   cwd=fixture, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", f"ADD: greet(name)\n\nRun-Id: {RUN_ID}"], cwd=fixture, check=True, capture_output=True)
    # task 2 的實作＋測試只在 staging（首跑時 farewell 被誤放進 commit 1，恢復者一眼看出「staged 只有測試檔」——現場要真）
    w(os.path.join(fixture, "lib", "greeting.py"),
      greet_only + "\n\ndef farewell(name):\n    _require(name)\n    return f'Bye, {name}!'\n")
    subprocess.run(["git", "add", "lib/greeting.py", "tests/test_greeting_farewell.py"], cwd=fixture, check=True, capture_output=True)

    manifest = {
        "harness": os.environ.get("AGENT_FLOW_HARNESS", "claude"), "run_id": RUN_ID, "created_at": "2026-10-01 09:00", "evidence_schema": 2, "tier": 2,
        "tier_rationale": "理由碼：【未決重大決策】——farewell 的措辭由使用者裁示；不觸信任邊界",
        "spec_path": f"spec/{RUN_ID}.md", "spec_inline": None, "test_command": "python3 -m pytest tests/ -q",
        "phase": "decomposed", "hitl_confirmed_at": "2026-10-01 09:10 — 確認 2 tasks／2 items", "hitl_rulings": 1,
        "risk_report_path": None, "usage_report_path": None, "impact_report_path": None,
        "task_file": "task/2026-10-01.md", "estimated_active_minutes": 40, "executor_notes": [],
        "status": "in_progress", "failed_reason": None, "local_test_passed": None, "local_test_evidence": None,
        "verification_commands": [], "review_reds": None, "verify_passed": None,
    }
    w(os.path.join(fixture, "run", f"{RUN_ID}.json"), json.dumps(manifest, ensure_ascii=False, indent=2))
    state = {"run_id": RUN_ID, "sub_tasks": [
        subtask(1, "greet", "passed", "done", ["lib/greeting.py", "tests/test_greeting_core.py"]),
        subtask(2, "farewell", "in_progress", "reviewing", ["lib/greeting.py", "tests/test_greeting_farewell.py"]),
    ]}
    w(os.path.join(fixture, "eval_state.json"), json.dumps(state, ensure_ascii=False, indent=2))
    print(f"[setup] 中斷現場已造：run_id={RUN_ID} task1=passed task2=reviewing staged=tests/test_greeting_farewell.py")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：setup.py <fixture_dir>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
