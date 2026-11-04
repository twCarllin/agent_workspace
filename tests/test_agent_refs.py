"""文件→subagent 存在性檢查：防文件引用不存在的 agent（如 eval-scorer 已刪但 skill 還引用）。

現況缺口：既有 test_docs_consistency.py 只檢查 hook 路徑、skill 互引、agent frontmatter
宣告的 skill，不檢查被文件引用的 agent 本身是否存在。本測試補齊此缺口。

執行：python3 -m unittest tests.test_agent_refs -v
掃描來源：skills/*/SKILL.md、skills/*/references/*.md、.claude/agents/*.md、CLAUDE.md、README.md。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agent-flow/scripts"))
from document_inventory import skill_documents

SCAN_FILES = (
    skill_documents(ROOT)
    + list((ROOT / ".claude" / "agents").glob("*.md"))
    + [ROOT / "CLAUDE.md", ROOT / "README.md"]
)

# 已知死引用例外清單（承擔攔截的地方，不是為了讓測試過而存在）。
#
# hygiene 測試強制維護：
#   - 若清單內的 agent 重新出現於 .claude/agents/ → 測試 fail（提示清理例外）
#   - 若清單內的 agent 在文件中已無人引用 → 測試 fail（提示清理例外）
#
# 格式：{ agent_name: "說明" }
EXCEPTION_LIST = {
    # 目前無例外。原有的 eval-scorer 條目已於 run 2026-07-30-deprecate-orphan-skills
    # 移除——該條目的說明本身即預告「待 eval-scoring skill 汰除後清理」，而該 skill 已
    # 移入 skills/_deprecated/、脫離共同清單的活 skill 範圍，全 repo 再無 eval-scorer
    # 的引用來源，hygiene 檢查（清單內 agent 已無人引用即 fail）如設計般要求清理本條目。
    # 移除是收緊而非放寬：主檢查不再豁免 eval-scorer，涵蓋範圍變大。
}


def read(path):
    return path.read_text(encoding="utf-8")


def extract_agent_refs(text: str) -> set:
    """從文字中提取被引用的 agent 名稱集合。

    採納的兩種判準：

    判準 1 — 反引號／粗體包裹後接 agent／subagent（名字限小寫）
        例：`code-writer` subagent、**`usage-analyzer`** subagent
        理由：名字在反引號內且有明確關鍵字，專案慣用寫法，零誤判。名字限小寫是
              刻意的——專案 agent 命名慣例即小寫連字號，放寬大小寫會讓文件提到
              Claude Code 內建 agent（`Explore` subagent、`Plan` agent）時誤判為
              「不存在於 .claude/agents/」而紅燈。

    判準 2 — 路徑形式 .claude/agents/<name>.md
        例：.claude/agents/code-writer.md
        理由：路徑語義無歧義，只命中真正的 agent 定義路徑。

    明確不採納 — 任何「裸名字 + agent／subagent」形式（不論是否帶連字號）
        單字例：item agent、spawn agent、cd agent、AI agent、retro agent
        連字號例：long-running agent、built-in agent、multi-purpose subagent

        理由：裸形式無法與英文散文機械區分。單字形式會命中 item／spawn／cd 等
        大量散文；連字號形式一度被認為「散文極罕見」而採納，實測推翻——英文複合
        形容詞（long-running、built-in、user-facing、real-time、multi-purpose）
        修飾 agent／subagent 是技術文件的常態寫法，會讓任何人日後寫一句英文散文
        就使本測試紅燈。假陽性會把測試變成雜訊源、進而被整條停用，代價高於漏抓，
        故一律不採納裸形式。

        代價（已知且接受）：`retro agent`、`task-verifier agent` 這類裸形式真引用
        會漏抓。這不損及本測試的核心價值——專案慣例是反引號形式，實際的死引用
        eval-scorer 正是由判準 1 在 skills/eval-scoring/SKILL.md 命中；要讓引用
        被偵測到，寫成 `name` subagent 即可。
    """
    # 判準 1：反引號（含粗體）包裹後接 agent/subagent
    # 匹配：`name` agent、`name` subagent、**`name`** subagent、**`name` subagent** 等
    # 名字部分固定小寫（專案 agent 命名慣例即小寫連字號），大小寫寬容只給關鍵字
    # （(?i:...) 為 scoped inline flag）——若讓 IGNORECASE 也放寬名字，`Explore` subagent、
    # `Plan` agent 這類 Claude Code 內建 agent 的引用會被判為「不存在」而紅燈。
    _p1 = re.compile(r"\*{0,2}`([a-z][a-z0-9-]+)`\*{0,2}\s+(?i:(?:sub)?agent)")
    # 判準 2：路徑形式 .claude/agents/<name>.md
    _p2 = re.compile(r"\.claude/agents/([a-z][a-z0-9-]+)\.md")

    refs: set = set()
    refs.update(_p1.findall(text))
    refs.update(_p2.findall(text))
    return refs


def scan_all_refs(root=ROOT) -> dict:
    """掃描所有來源檔案，回傳 {agent_name: [來源檔相對路徑, ...]} 的字典。"""
    refs: dict = {}
    files = (
        skill_documents(root)
        + list((root / ".claude" / "agents").glob("*.md"))
        + [root / "CLAUDE.md", root / "README.md"]
    )
    for f in files:
        if not f.exists():
            continue
        text = read(f)
        rel = str(f.relative_to(root))
        for name in extract_agent_refs(text):
            refs.setdefault(name, []).append(rel)
    return refs


class AgentRefIntegrationTest(unittest.TestCase):
    """對實際文件進行掃描的整合測試。"""

    def setUp(self):
        self._all_refs = scan_all_refs()
        self._agents_dir = ROOT / ".claude" / "agents"

    def test_all_refs_exist(self):
        """主檢查：所有掃出的引用（扣除例外清單）都必須存在對應的 .md 檔。

        失敗訊息會指出是哪個檔案引用了哪個不存在的 agent。
        """
        for name, sources in self._all_refs.items():
            with self.subTest(agent=name):
                if name in EXCEPTION_LIST:
                    continue
                self.assertTrue(
                    (self._agents_dir / f"{name}.md").exists(),
                    f"agent '{name}' 被引用（來源：{sources}）"
                    f"但 .claude/agents/{name}.md 不存在",
                )

    def test_non_vacuous(self):
        """非空性：掃描必須抓到已知的活引用，防判準損壞導致零命中的假通過。"""
        for name in ["code-writer", "task-decomposer"]:
            with self.subTest(agent=name):
                self.assertIn(name, self._all_refs)

    def test_engineering_skills_resolve_from_both_repo_entries(self):
        for name in (
            "system-investigation",
            "design-comparison",
            "impact-analysis",
            "adversarial-verification",
            "structural-correction",
        ):
            with self.subTest(skill=name):
                source = ROOT / "skills" / name / "SKILL.md"
                for entry in (".agents/skills", ".claude/skills"):
                    path = ROOT / entry / name
                    self.assertTrue(path.is_symlink())
                    self.assertEqual((path / "SKILL.md").resolve(), source.resolve())
                    self.assertEqual(
                        (path / "SKILL.md").read_bytes(), source.read_bytes()
                    )


if __name__ == "__main__":
    unittest.main()
