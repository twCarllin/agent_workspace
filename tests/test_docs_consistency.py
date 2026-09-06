"""文件↔實體一致性檢查：防「skill 改了、引用沒跟上」的漂移（實測發生過）。

執行：python3 -m unittest discover -s tests -v
檢查對象是 repo 本身的靜態一致性，不跑任何流程。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_FILES = (
    list((ROOT / "skills").glob("*/SKILL.md"))
    + list((ROOT / "skills").glob("*/references/*.md"))
    + list((ROOT / ".claude" / "agents").glob("*.md"))
    + [ROOT / "CLAUDE.md", ROOT / "README.md"]
)


def read(path):
    return path.read_text(encoding="utf-8")


class HookScriptReferencesTest(unittest.TestCase):
    def test_all_referenced_hook_scripts_exist(self):
        pattern = re.compile(r"\.claude/hooks/([\w.-]+\.(?:py|sh))")
        for md in MD_FILES:
            for name in pattern.findall(read(md)):
                self.assertTrue(
                    (ROOT / ".claude" / "hooks" / name).exists(),
                    f"{md.relative_to(ROOT)} 引用了不存在的 hook script：{name}",
                )


class SkillReferencesTest(unittest.TestCase):
    def test_all_referenced_skills_exist(self):
        # 慣例寫法：`name` skill / **name** skill / skills/name/SKILL.md
        patterns = [
            re.compile(r"[`*]([a-z][a-z0-9-]+)[`*]+ skill"),
            re.compile(r"skills/([a-z][a-z0-9-]+)/SKILL\.md"),
        ]
        skill_dirs = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
        for md in MD_FILES:
            text = read(md)
            for pat in patterns:
                for name in pat.findall(text):
                    self.assertIn(
                        name, skill_dirs,
                        f"{md.relative_to(ROOT)} 引用了不存在的 skill：{name}",
                    )

    def test_agent_frontmatter_skills_exist(self):
        skill_dirs = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
        for md in (ROOT / ".claude" / "agents").glob("*.md"):
            m = re.search(r"^skills:\s*(.+)$", read(md), re.M)
            if not m:
                continue
            for name in re.split(r"[,\s]+", m.group(1).strip()):
                if name:  # testlint: allow — 空欄位跳過是刻意（split 尾端空字串），非藏斷言
                    self.assertIn(
                        name, skill_dirs,
                        f"{md.name} frontmatter 引用了不存在的 skill：{name}",
                    )


class HelperSubcommandDocsTest(unittest.TestCase):
    def test_eval_state_subcommands_in_docs_exist(self):
        """eval-flow skill 列的 helper 子命令必須真的存在於 eval_state.py。

        清單的單一枚舉點自 2026-09-06 起收斂到 references/formats.md
        （run 2026-09-06-skill-prose-slimming 去重，SKILL.md 改指向句）。"""
        source = read(ROOT / ".claude" / "hooks" / "eval_state.py")
        skill = read(ROOT / "skills" / "eval-flow" / "references" / "formats.md")
        m = re.search(r"eval_state\.py`（`([^）]+)`）", skill)
        self.assertIsNotNone(m, "eval-flow references/formats.md 找不到 helper 子命令清單")
        for cmd in m.group(1).split("`／`"):
            self.assertIn(
                f'add_parser("{cmd}")', source,
                f"eval-flow skill 列的子命令 {cmd} 不存在於 eval_state.py",
            )


class GateListConsistencyTest(unittest.TestCase):
    def test_gate_numbering_ranges_match_list(self):
        """README 與 eval-flow skill 宣稱的 gate 區間（gate 1–N）要等於實際列出的條數。"""
        for md in [ROOT / "README.md", ROOT / "skills" / "eval-flow" / "references" / "gates.md"]:
            text = read(md)
            m = re.search(r"gate 1–(\d+)）.*?（gate (\d+)–(\d+)）", text)
            if not m:
                continue
            commit_end, sub_start, sub_end = map(int, m.groups())
            self.assertEqual(sub_start, commit_end + 1, f"{md.name} gate 區間不連續")
            # 找 gate 清單的編號項（1. **...gate**），最大編號 = 區間上限
            section = text[m.start():]
            numbers = [int(n) for n in re.findall(r"^(\d+)\. \*\*", section, re.M)]
            self.assertEqual(
                max(numbers), sub_end,
                f"{md.name} 宣稱 gate 到 {sub_end}，實際清單最大編號 {max(numbers)}",
            )


class RetroIdReferencesTest(unittest.TestCase):
    def test_retro_ids_have_no_duplicates(self):
        text = read(ROOT / "retro" / "RETRO.md")
        ids = re.findall(r"^- (R-\d{3}) ", text, re.M)
        self.assertEqual(
            len(ids), len(set(ids)),
            f"retro/RETRO.md 的 R-NNN ID 有重號：{ids}",
        )

    def test_all_referenced_retro_ids_exist(self):
        retro_text = read(ROOT / "retro" / "RETRO.md")
        defined_ids = set(re.findall(r"^- (R-\d{3}) ", retro_text, re.M))
        pattern = re.compile(r"[（(](R-\d{3})[）)]")
        for md in MD_FILES:
            for ref_id in pattern.findall(read(md)):
                self.assertIn(
                    ref_id, defined_ids,
                    f"{md.relative_to(ROOT)} 引用了不存在的 RETRO ID：{ref_id}",
                )


class EnvelopeSpecTest(unittest.TestCase):
    def test_all_agents_have_envelope_spec(self):
        """每個 agent 定義都須掛報告信封規範（終行 Self-check），防新增 agent 漏掛。"""
        for md in (ROOT / ".claude" / "agents").glob("*.md"):
            self.assertIn(
                "Self-check:", read(md),
                f"{md.name} 缺報告信封規範（無 Self-check: 關鍵句）",
            )


if __name__ == "__main__":
    unittest.main()
