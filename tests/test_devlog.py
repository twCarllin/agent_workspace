"""devlog.py 唯讀敘事 render 的行為測試。

執行：python3 -m unittest tests.test_devlog -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS_DIR = str(Path(__file__).resolve().parents[1] / ".claude" / "hooks")
DEVLOG_PATH = os.path.join(HOOKS_DIR, "devlog.py")


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class DevlogRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_mode_finds_manifests_under_non_default_dir(self):
        """清單模式（無 run_id）在非字面 "run" 的 --dir（此處為 tmp 下的絕對路徑）下
        仍須找到合法 manifest，且排除 `.eval.json` 干擾檔（MANIFEST_RE 排除生效）。"""
        write(os.path.join(self.run_dir, "list-a.json"), {"run_id": "list-a", "tier": 1})
        write(os.path.join(self.run_dir, "list-b.json"), {"run_id": "list-b", "tier": 2})
        write(os.path.join(self.run_dir, "list-a.eval.json"), {"run_id": "list-EVAL-LEAK", "sub_tasks": []})
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("list-a", result.stdout)
        self.assertIn("list-b", result.stdout)
        self.assertNotIn("list-EVAL-LEAK", result.stdout)

    def test_nonexistent_run_id_exits_nonzero_with_stderr_and_no_stdout(self):
        """[邊界] run_id 不存在 → exit code 非 0、stderr 提示、stdout 無輸出。"""
        os.makedirs(self.run_dir, exist_ok=True)
        result = subprocess.run(
            [sys.executable, DEVLOG_PATH, "nonexistent-run-id", "--dir", self.run_dir],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
