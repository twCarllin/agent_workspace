"""MODEL_POLICY.md（政策表）↔ agent frontmatter（執行端）一致性：防「改了一邊沒改另一邊」的漂移。

執行：python3 -m unittest tests.test_model_policy
檢查對象是 repo 本身的靜態一致性，不跑任何流程。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "MODEL_POLICY.md"
AGENTS_DIR = ROOT / ".claude" / "agents"

# 政策表 row：| agent | model | 理由 |（跳過表頭與 |---| 分隔行）
POLICY_ROW_RE = re.compile(r"^\|\s*([a-z][\w-]*)\s*\|\s*(claude-[\w.-]+)\s*\|", re.M)
# frontmatter model 欄：值取到空白或行內註解（# ...）為止
FRONTMATTER_MODEL_RE = re.compile(r"^model:\s*([^\s#]+)", re.M)


def policy_table():
    text = POLICY.read_text(encoding="utf-8")
    rows = {}
    for name, model in POLICY_ROW_RE.findall(text):
        rows[name] = model
    return rows


def frontmatter_models():
    models = {}
    for md in AGENTS_DIR.glob("*.md"):
        m = FRONTMATTER_MODEL_RE.search(md.read_text(encoding="utf-8"))
        models[md.stem] = m.group(1) if m else None
    return models


def family(model_id):
    """claude-<family>-... → family（如 claude-sonnet-5 → sonnet）。"""
    return model_id.removeprefix("claude-").split("-")[0]


class ModelPolicyConsistencyTest(unittest.TestCase):
    def test_policy_covers_exactly_all_agents(self):
        table = set(policy_table())
        agents = {p.stem for p in AGENTS_DIR.glob("*.md")}
        self.assertEqual(
            table, agents,
            f"政策表與 .claude/agents/ 集合不一致：表多出 {table - agents}，漏列 {agents - table}",
        )

    def test_frontmatter_matches_policy(self):
        table = policy_table()
        for agent, actual in frontmatter_models().items():
            self.assertIsNotNone(actual, f"{agent}.md frontmatter 缺 model 欄")
            self.assertEqual(
                table.get(agent), actual,
                f"{agent}：政策表 {table.get(agent)} ≠ frontmatter {actual}（改 model 須兩處同 diff）",
            )

    def test_writer_reviewer_families_differ(self):
        table = policy_table()
        writer, reviewer = table["code-writer"], table["code-reviewer"]
        self.assertNotEqual(
            family(writer), family(reviewer),
            f"去相關化約束違反：code-writer（{writer}）與 code-reviewer（{reviewer}）同家族",
        )

    def test_inline_comment_boundary(self):
        """frontmatter model 行帶行內註解（現況存在）→ 解析須只取值。"""
        m = FRONTMATTER_MODEL_RE.search("model: claude-opus-4-8  # 註解說明\n")
        self.assertEqual(m.group(1), "claude-opus-4-8")


if __name__ == "__main__":
    unittest.main()
