"""進 LLM context 的 prose 衛生 lint：防 skill／agent／CLAUDE.md 文件回長歷史註記、術語漂移、共用節失同步、無節制膨脹。

依據 Anthropic「Skill authoring best practices」四條：Avoid time-sensitive information、
Use consistent terminology、Concise is key、Keep SKILL.md small。掃描範圍＝會被載入 context 的檔案；
HISTORY.md／README.md／TODO.md 不進 context、不掃。

執行：python3 -m pytest tests/test_prose_lint.py -q
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "skills" / "eval-flow" / "references" / "glossary.md"

SKILL_FILES = sorted(
    p for p in (ROOT / "skills").glob("*/SKILL.md") if "_deprecated" not in p.parts
)
REFERENCE_FILES = sorted(
    p for p in (ROOT / "skills").glob("*/references/*.md") if "_deprecated" not in p.parts
)
AGENT_FILES = sorted((ROOT / ".claude" / "agents").glob("*.md"))
CLAUDE_MD = ROOT / "CLAUDE.md"
PROSE_FILES = SKILL_FILES + REFERENCE_FILES + AGENT_FILES + [CLAUDE_MD]

# 字元預算（以字元計，不以行計——中文 prose 單行可達 900+ 字元，行數不反映 context 成本）。
# 數值＝2026-10-03 去歷史化後各類最大檔的現值取整到千位，餘裕 10–16%；超標時的正確動作是依
# progressive disclosure 拆到 references/，不是擴寫。description 兩條刻意更緊：它們每個 session 預載。
BUDGET_SKILL_CHARS = 24_000        # eval-flow SKILL.md 現值 23.8K（Tier 2 前置外移後；餘裕僅 0.6%，刻意——再長就該分檔）
BUDGET_REFERENCE_CHARS = 16_000    # formats.md 現值 14.1K（餘裕約 13%）
BUDGET_AGENT_CHARS = 8_000         # code-reviewer.md 現值 7.2K（餘裕約 10%）
BUDGET_CLAUDE_MD_CHARS = 6_000     # CLAUDE.md 現值 5.2K（餘裕約 16%；每個 session 必載，最貴的一份）
BUDGET_DESCRIPTION_CHARS = 300     # 現值最大 269（usage-scenario-analysis）＋約 10%；遠嚴於 Anthropic 上限 1,024
BUDGET_DESCRIPTIONS_TOTAL = 2_000  # 現值 1.94K，餘裕僅 3%：刻意——9 個 description 每 session 全部預載，只准縮不准長

DATE_RE = re.compile(r"20\d{2}-\d{2}")
# 已消失機制／裁決編號／實測軼事的句型；規則本身若仍有效，應以現行式陳述，歷史住 HISTORY.md
LEGACY_RE = re.compile(r"已刪除|已作廢|不再產生|不再是|不再需要|裁示 #|出生證|實測教訓|實測（20|實測 20|實測：")
FENCE_RE = re.compile(r"^```")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
SECTION_HEADER = "## 測試案例組織"
SHARED_SECTION_AGENTS = ("code-writer", "code-reviewer", "task-verifier")


def read(path):
    return path.read_text(encoding="utf-8")


def prose_lines(text):
    """去掉 fenced code block 與行內 code 後的 (行號, 行文字)——格式範例與 CLI 旗標不算 prose。"""
    out, in_fence = [], False
    for no, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((no, INLINE_CODE_RE.sub("", line)))
    return out


def description_of(text):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = m.group(1)
    single = re.search(r"^description:[ \t]*(\S.*)$", fm, re.M)
    if single and single.group(1).strip() != "|":
        return single.group(1).strip()
    block = re.search(r"^description:[ \t]*\|\n((?:[ \t]+.*\n?)+)", fm, re.M)
    return " ".join(l.strip() for l in block.group(1).splitlines()) if block else None


def banned_variants():
    """glossary.md「禁用變體」欄的單一枚舉點：只取可機械比對的純英數變體（中文同義詞含括號說明，留給人審）。"""
    variants = []
    for line in read(GLOSSARY).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("正式詞", "---"):
            continue
        for v in cells[2].split("、"):
            v = v.strip()
            if v and re.fullmatch(r"[A-Za-z_\-]+", v):
                variants.append(v)
    return variants


def terminology_scan_files():
    """術語 lint 的掃描範圍：全部 prose 減去術語表自身（它的禁用變體欄必然命中）。"""
    return [p for p in PROSE_FILES if p != GLOSSARY]


def hits(path, regex):
    return [f"{path.relative_to(ROOT)}:{no}: {line.strip()[:80]}"
            for no, line in prose_lines(read(path)) if regex.search(line)]


class NoTimeSensitiveProseTest(unittest.TestCase):
    def test_prose_body_has_no_dates(self):
        found = [h for p in PROSE_FILES for h in hits(p, DATE_RE)]
        self.assertEqual(found, [], "prose 本體含日期（歷史註記請搬 HISTORY.md）：\n" + "\n".join(found))

    def test_prose_body_has_no_legacy_phrases(self):
        found = [h for p in PROSE_FILES for h in hits(p, LEGACY_RE)]
        self.assertEqual(found, [], "prose 本體含已消失機制／裁決碼／實測軼事句型：\n" + "\n".join(found))


class ConsistentTerminologyTest(unittest.TestCase):
    def test_no_banned_term_variants_outside_code(self):
        variants = banned_variants()
        self.assertIn("subtask", variants, "glossary.md 禁用變體欄未解析到預期項目")
        regex = re.compile("|".join(re.escape(v) for v in variants), re.I)
        found = [h for p in terminology_scan_files() for h in hits(p, regex)]
        self.assertEqual(found, [], "prose 使用了術語表禁用的變體（正式詞見 glossary.md）：\n" + "\n".join(found))


class ProseExtractionTest(unittest.TestCase):
    """契約 C3／C4／C5：格式範例、CLI 旗標與術語表自身不算違規。"""

    def test_fenced_code_block_dates_are_ignored(self):
        text = "規則一句。\n```json\n{\"created_at\": \"2026-07-06 14:30\"}\n```\n規則二句。"
        self.assertEqual([no for no, line in prose_lines(text) if DATE_RE.search(line)], [])
        self.assertEqual([no for no, line in prose_lines("本段於 2026-01-01 寫入。") if DATE_RE.search(line)], [1])

    def test_inline_code_variants_are_ignored(self):
        regex = re.compile("|".join(re.escape(v) for v in banned_variants()), re.I)
        self.assertEqual([no for no, line in prose_lines("子命令 `add-subtask` 與旗標 `--sub-task`。") if regex.search(line)], [])
        self.assertEqual([no for no, line in prose_lines("這個 subtask 要先做。") if regex.search(line)], [1])

    def test_glossary_itself_is_excluded_from_variant_scan(self):
        regex = re.compile("|".join(re.escape(v) for v in banned_variants()), re.I)
        self.assertIn(GLOSSARY, PROSE_FILES)
        self.assertNotIn(GLOSSARY, terminology_scan_files())
        self.assertNotEqual(hits(GLOSSARY, regex), [], "glossary.md 的禁用變體欄本身應命中，才證明排除有效")


class SharedSectionSyncTest(unittest.TestCase):
    def test_test_case_organization_section_identical_across_agents(self):
        sections = {}
        for name in SHARED_SECTION_AGENTS:
            text = read(ROOT / ".claude" / "agents" / f"{name}.md")
            m = re.search(re.escape(SECTION_HEADER) + r".*?\n(.*?)(?=\n## )", text, re.S)
            self.assertIsNotNone(m, f"{name}.md 缺「{SECTION_HEADER}」節")
            sections[name] = m.group(1).strip()
        distinct = set(sections.values())
        self.assertEqual(len(distinct), 1, "三份 agent 的「測試案例組織」節不一致，須同 diff 改齊：" + ", ".join(sections))


class CharBudgetTest(unittest.TestCase):
    @staticmethod
    def _over(files, budget):
        return [f"{p.relative_to(ROOT)}={len(read(p))}" for p in files if len(read(p)) > budget]

    def test_skill_bodies_within_budget(self):
        self.assertEqual(self._over(SKILL_FILES, BUDGET_SKILL_CHARS), [],
                         f"SKILL.md 超過字元預算 {BUDGET_SKILL_CHARS}（請拆到 references/，不要擴寫）")

    def test_reference_files_within_budget(self):
        self.assertEqual(self._over(REFERENCE_FILES, BUDGET_REFERENCE_CHARS), [],
                         f"references/*.md 超過字元預算 {BUDGET_REFERENCE_CHARS}（請再分檔，不要擴寫）")

    def test_agent_definitions_within_budget(self):
        self.assertEqual(self._over(AGENT_FILES, BUDGET_AGENT_CHARS), [],
                         f".claude/agents/*.md 超過字元預算 {BUDGET_AGENT_CHARS}（規則細節請指向 skill，不要擴寫）")

    def test_claude_md_within_budget(self):
        self.assertEqual(self._over([CLAUDE_MD], BUDGET_CLAUDE_MD_CHARS), [],
                         f"CLAUDE.md 超過字元預算 {BUDGET_CLAUDE_MD_CHARS}（每 session 必載；細則請指向 skill）")

    def test_descriptions_within_budget(self):
        descs = {p.parent.name: description_of(read(p)) for p in SKILL_FILES}
        descs.update({f"agent:{p.stem}": description_of(read(p)) for p in AGENT_FILES})
        missing = [k for k, v in descs.items() if not v]
        self.assertEqual(missing, [], f"缺 description：{missing}")
        over = {k: len(v) for k, v in descs.items() if len(v) > BUDGET_DESCRIPTION_CHARS}
        self.assertEqual(over, {}, f"description 超過 {BUDGET_DESCRIPTION_CHARS} 字元：{over}")
        total = sum(len(v) for k, v in descs.items() if not k.startswith("agent:"))
        self.assertLessEqual(total, BUDGET_DESCRIPTIONS_TOTAL,
                             f"skill description 合計 {total} 超過 {BUDGET_DESCRIPTIONS_TOTAL}（每 session 預載）")


if __name__ == "__main__":
    unittest.main()
