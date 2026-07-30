"""文件→subagent 存在性檢查：防文件引用不存在的 agent（如 eval-scorer 已刪但 skill 還引用）。

現況缺口：既有 test_docs_consistency.py 只檢查 hook 路徑、skill 互引、agent frontmatter
宣告的 skill，不檢查被文件引用的 agent 本身是否存在。本測試補齊此缺口。

執行：python3 -m unittest tests.test_agent_refs -v
掃描來源：skills/*/SKILL.md、.claude/agents/*.md、CLAUDE.md、README.md。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN_FILES = (
    list((ROOT / "skills").glob("*/SKILL.md"))
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
    # 移入 skills/_deprecated/、脫離上方 SCAN_FILES 的單層 glob，全 repo 再無 eval-scorer
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


def scan_all_refs() -> dict:
    """掃描所有來源檔案，回傳 {agent_name: [來源檔相對路徑, ...]} 的字典。"""
    refs: dict = {}
    for f in SCAN_FILES:
        if not f.exists():
            continue
        text = read(f)
        rel = str(f.relative_to(ROOT))
        for name in extract_agent_refs(text):
            refs.setdefault(name, []).append(rel)
    return refs


class AgentRefPatternTest(unittest.TestCase):
    """extract_agent_refs() 的單元測試——驗證兩種判準的正向識別與裸形式的反向過濾。"""

    def test_backtick_form_detected(self):
        """判準 1：反引號包裹名字後接 subagent，應識別為引用。"""
        refs = extract_agent_refs("`code-writer` subagent 執行")
        self.assertIn("code-writer", refs)

    def test_bold_backtick_wrapped_name_detected(self):
        """判準 1：粗體在名字兩側（**`name`** subagent），應識別為引用。"""
        refs = extract_agent_refs("**`usage-analyzer`** subagent 載入使用")
        self.assertIn("usage-analyzer", refs)

    def test_bold_backtick_phrase_detected(self):
        """判準 1：粗體包整句（**`name` subagent**），應識別為引用。"""
        refs = extract_agent_refs("本 skill 由 **`usage-analyzer` subagent** 載入")
        self.assertIn("usage-analyzer", refs)

    def test_path_form_detected(self):
        """判準 2：路徑形式 .claude/agents/<name>.md，應識別為引用。"""
        refs = extract_agent_refs("見 .claude/agents/code-writer.md 的規則節")
        self.assertIn("code-writer", refs)

    def test_bare_hyphenated_name_not_detected(self):
        """不採納：裸帶連字號名字後接 agent／subagent，不應被識別（已知且接受的漏抓）。"""
        cases = [("task-verifier agent 做驗收", "task-verifier"),
                 ("eval-scorer subagent 執行評分", "eval-scorer")]
        for text, name in cases:
            with self.subTest(text=text):
                self.assertNotIn(name, extract_agent_refs(text))

    def test_hyphenated_english_prose_not_detected(self):
        """不採納的關鍵理由：英文複合形容詞修飾 agent 是技術文件常態，不得判為引用。

        沒有這道守護，任何人日後在 README／SKILL 寫一句 'a long-running agent'
        就會讓 test_all_refs_exist 紅燈（假陽性把測試變成雜訊源）。
        """
        prose = [
            ("a long-running agent", "long-running"),
            ("the built-in agent", "built-in"),
            ("a user-facing agent", "user-facing"),
            ("use a multi-purpose subagent", "multi-purpose"),
            ("the real-time agent", "real-time"),
        ]
        for text, word in prose:
            with self.subTest(text=text):
                self.assertNotIn(
                    word,
                    extract_agent_refs(text),
                    f"'{text}' 是英文散文，不應被識別為 agent 引用",
                )

    def test_capitalized_builtin_agent_not_detected(self):
        """判準 1 的名字限小寫：文件提到 Claude Code 內建 agent 不應被判為專案 agent 引用。

        內建 agent（Explore／Plan／Task）不住在 .claude/agents/，若被捕捉會紅燈。
        """
        for text, name in [("`Explore` subagent", "Explore"), ("`Plan` agent", "Plan")]:
            with self.subTest(text=text):
                self.assertNotIn(name, extract_agent_refs(text))

    def test_bare_single_word_not_detected(self):
        """不採納：裸單字 token 後接 agent，不應被識別為引用（防散文假陽性）。"""
        anti_patterns = [
            ("item agent", "item"),
            ("spawn agent", "spawn"),
            ("cd agent", "cd"),
        ]
        for text, word in anti_patterns:
            with self.subTest(text=text):
                refs = extract_agent_refs(text)
                self.assertNotIn(
                    word,
                    refs,
                    f"'{text}' 是英文散文，不應被識別為 agent 引用",
                )

    def test_bare_retro_not_detected(self):
        """不採納：裸單字 retro 後接 agent（已知且接受的漏抓），不應被識別。"""
        refs = extract_agent_refs("retro agent 記錄根因")
        self.assertNotIn("retro", refs)


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

    def test_exception_agent_not_live(self):
        """Hygiene：例外清單中的 agent 若已重新建立於 .claude/agents/，應從清單移除。"""
        for name, reason in EXCEPTION_LIST.items():
            with self.subTest(agent=name):
                self.assertFalse(
                    (self._agents_dir / f"{name}.md").exists(),
                    f"例外清單中的 '{name}' 已重新存在於 .claude/agents/{name}.md，"
                    f"請從 EXCEPTION_LIST 移除此條目。原因：{reason}",
                )

    def test_exception_still_referenced(self):
        """Hygiene：例外清單中的 agent 若文件中已無引用，應從清單移除。"""
        for name in EXCEPTION_LIST:
            with self.subTest(agent=name):
                self.assertIn(
                    name,
                    self._all_refs,
                    f"例外清單中的 '{name}' 在所有掃描文件中已無引用，"
                    f"請從 EXCEPTION_LIST 移除此條目（引用已清理，例外不再需要）。",
                )

    def test_non_vacuous(self):
        """非空性：掃描必須抓到已知的活引用，防判準損壞導致零命中的假通過。"""
        known_live = ["code-writer", "task-decomposer"]
        for name in known_live:
            with self.subTest(agent=name):
                self.assertIn(
                    name,
                    self._all_refs,
                    f"掃描結果未找到預期活引用 '{name}'，"
                    f"判準可能損壞（零命中會讓 test_all_refs_exist 假通過）",
                )


if __name__ == "__main__":
    unittest.main()
