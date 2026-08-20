"""init.sh 的 settings.json 合併（PreToolUse＋SessionStart）端到端與冪等測試。

依 retro 約束（跨進程執行契約）：以 subprocess 跑真實 `bash init.sh`（不重新實作合併邏輯），
在隔離的臨時目錄結構下執行——`HOME` 導向臨時目錄，避免寫到開發機真實 ~/.claude/skills。

執行：python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRE_EXISTING_DST_SETTINGS = {
    "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"},
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash|Task|Agent",
                "hooks": [
                    {
                        "type": "command",
                        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh",
                    }
                ],
            }
        ]
    },
    "worktree": {"baseRef": "head"},
}


def build_framework_dir(dest):
    """把跑 init.sh 需要的最小子集複製到 dest（模擬 framework 被 clone 進目標專案的位置）。
    只複製 step 3（hooks，含 gate-check.sh，chmod +x 需要它存在）與 step 4（settings.json，
    合併行為的測試對象）依賴的檔案；CLAUDE.md／agents／skills／seed 皆不提供，
    對應步驟會走既有「不存在則 Skipped」分支，不影響本測試對象。"""
    os.makedirs(dest / ".claude", exist_ok=True)
    shutil.copy(ROOT / "init.sh", dest / "init.sh")
    shutil.copytree(
        ROOT / ".claude" / "hooks", dest / ".claude" / "hooks",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(ROOT / ".claude" / "settings.json", dest / ".claude" / "settings.json")
    return dest


def run_init_sh(framework_dir, home_dir):
    """以 subprocess 跑真實 init.sh；HOME 導向 home_dir（sandbox step 5，即使本測試
    不觸發它——SRC_SKILLS 未提供而走 Skipped 分支）。回傳 CompletedProcess。"""
    env = {**os.environ, "HOME": str(home_dir)}
    return subprocess.run(
        ["bash", str(framework_dir / "init.sh")],
        cwd=str(framework_dir), capture_output=True, text=True, env=env, timeout=30,
    )


class SettingsMergeEndToEndTest(unittest.TestCase):
    """情境 L：init.sh 合併兩個 hook 事件（冪等）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent_dir = Path(self.tmp.name) / "target_project"
        self.framework_dir = self.parent_dir / "agent_workspace"
        build_framework_dir(self.framework_dir)
        # 前置：部署層 settings.json 已存在，只含 PreToolUse（模擬先前只部署過舊版框架）
        dst_settings_dir = self.parent_dir / ".claude"
        dst_settings_dir.mkdir(parents=True, exist_ok=True)
        with open(dst_settings_dir / "settings.json", "w", encoding="utf-8") as f:
            json.dump(PRE_EXISTING_DST_SETTINGS, f, indent=2, ensure_ascii=False)
        self.home_dir = Path(self.tmp.name) / "home"

    def tearDown(self):
        self.tmp.cleanup()

    def _dst_settings(self):
        with open(self.parent_dir / ".claude" / "settings.json", encoding="utf-8") as f:
            return json.load(f)

    def test_merge_adds_session_start_keeps_pretooluse_and_other_keys(self):
        p = run_init_sh(self.framework_dir, self.home_dir)
        self.assertEqual(p.returncode, 0, msg=p.stderr)

        dst = self._dst_settings()
        pre = dst["hooks"]["PreToolUse"]
        self.assertEqual(len(pre), 1)
        self.assertEqual(
            pre[0]["hooks"][0]["command"],
            "$CLAUDE_PROJECT_DIR/.claude/hooks/gate-check.sh",
        )

        session_start = dst["hooks"]["SessionStart"]
        self.assertEqual(len(session_start), 1)
        self.assertEqual(session_start[0]["matcher"], "startup|resume|compact")
        self.assertIn("session_start.py", session_start[0]["hooks"][0]["command"])

        # [邊界] 其他鍵（env／worktree）不動
        self.assertEqual(dst["env"], PRE_EXISTING_DST_SETTINGS["env"])
        self.assertEqual(dst["worktree"], PRE_EXISTING_DST_SETTINGS["worktree"])

    def test_merge_is_idempotent(self):
        p1 = run_init_sh(self.framework_dir, self.home_dir)
        self.assertEqual(p1.returncode, 0, msg=p1.stderr)
        after_first = self._dst_settings()

        p2 = run_init_sh(self.framework_dir, self.home_dir)
        self.assertEqual(p2.returncode, 0, msg=p2.stderr)
        after_second = self._dst_settings()

        self.assertEqual(after_first, after_second)
        self.assertIn("already up to date", p2.stdout)


if __name__ == "__main__":
    unittest.main()
