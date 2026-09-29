"""MODEL_POLICY.md（政策表）↔ agent frontmatter（執行端）一致性：防「改了一邊沒改另一邊」的漂移。
Claude 端 writer／reviewer 異族約束已於 2026-09-29 廢除（run 2026-09-29-all-sonnet55），本檔不再檢查。

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

    # Claude 端「writer 與 reviewer 異族」測試已於 2026-09-29 隨規則廢除刪除（run 2026-09-29-all-sonnet55，
    # 使用者裁決全部 sonnet-5-5；去相關化改由 session 層承擔，見 MODEL_POLICY.md 約束節）。Codex 端仍有異族測試（下方 M1③）。

    def test_inline_comment_boundary(self):
        """frontmatter model 行帶行內註解（現況存在）→ 解析須只取值。"""
        m = FRONTMATTER_MODEL_RE.search("model: claude-opus-4-8  # 註解說明\n")
        self.assertEqual(m.group(1), "claude-opus-4-8")


CODEX_AGENTS_DIR = ROOT / ".codex" / "agents"
# Codex 表 row：| role | gpt-... | effort | 理由 |
CODEX_ROW_RE = re.compile(r"^\|\s*([a-z][\w-]*)\s*\|\s*(gpt-[\w.-]+)\s*\|\s*([a-z]+)\s*\|", re.M)


def codex_policy_table(text=None):
    """MODEL_POLICY.md Codex 表 → {role: (model, effort)}；text 給定時解析該字串（fixture 用）。"""
    if text is None:
        text = POLICY.read_text(encoding="utf-8")
    return {name: (model, effort) for name, model, effort in CODEX_ROW_RE.findall(text)}


def codex_toml_models(agents_dir=CODEX_AGENTS_DIR):
    """.codex/agents/<role>.toml → {role: (model, effort)}。"""
    import tomllib
    models = {}
    for path in agents_dir.glob("*.toml"):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        models[path.stem] = (data.get("model"), data.get("model_reasoning_effort"))
    return models


def codex_mismatches(expected, actual):
    """兩份 {role: (model, effort)} 的差異：角色集合不等或值不等的角色名清單（空＝一致）。"""
    problems = []
    for role in sorted(set(expected) | set(actual)):
        if role not in expected or role not in actual or expected[role] != actual[role]:
            problems.append(role)
    return problems


class CodexModelPolicyTest(unittest.TestCase):
    """run 2026-09-29-codex-model-policy item 1.2：MODEL_POLICY.md Codex 表 ↔ install_codex.CODEX_MODELS ↔
    repo .codex/agents/*.toml 三方一致（契約 M1–M3）。"""

    @staticmethod
    def codex_models():
        import importlib.util
        spec = importlib.util.spec_from_file_location("install_codex", ROOT / "install_codex.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {role: (model, effort) for role, (model, effort) in module.CODEX_MODELS.items()}

    def test_m1_table_matches_codex_models(self):
        """M1①：表 ↔ CODEX_MODELS 逐角色 model／effort 相等、角色集合相等且＝.claude/agents 集合（P1）。"""
        table = codex_policy_table()
        self.assertEqual(set(table), {p.stem for p in AGENTS_DIR.glob("*.md")})
        self.assertEqual(codex_mismatches(self.codex_models(), table), [],
                         "Codex 表與 install_codex.CODEX_MODELS 不一致（改 model 須三處同 diff）")

    def test_m1_codex_models_match_repo_toml(self):
        """M1②：CODEX_MODELS ↔ repo .codex/agents/*.toml 逐角色相等。"""
        self.assertEqual(codex_mismatches(self.codex_models(), codex_toml_models()), [],
                         ".codex/agents/*.toml 與 CODEX_MODELS 不一致（重跑 install_codex.py 或同 diff 改齊）")

    def test_m1_codex_writer_reviewer_differ(self):
        """M1③：Codex writer 與 reviewer model id 不同（去相關化）。"""
        table = codex_policy_table()
        self.assertNotEqual(table["code-writer"][0], table["code-reviewer"][0])

    def test_m2_modified_toml_copy_reported(self):
        """M2 [邊界]：暫存複本把 task-verifier 的 model 改掉 → 比對回報該角色（不動 repo 檔）。"""
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            for path in CODEX_AGENTS_DIR.glob("*.toml"):
                shutil.copy2(path, copy / path.name)
            target = copy / "task-verifier.toml"
            target.write_text(target.read_text(encoding="utf-8").replace('model = "gpt-6-luna"', 'model = "gpt-6-x"'),
                              encoding="utf-8")
            problems = codex_mismatches(self.codex_models(), codex_toml_models(copy))
        self.assertEqual(problems, ["task-verifier"])

    def test_m3_missing_role_in_table_reported(self):
        """M3 [邊界]：表少列 retro → 集合不等，差異清單含 retro。"""
        text = POLICY.read_text(encoding="utf-8")
        text = "\n".join(line for line in text.splitlines() if not line.startswith("| retro | gpt-"))
        table = codex_policy_table(text)
        self.assertNotIn("retro", table)
        self.assertIn("retro", codex_mismatches(self.codex_models(), table))


if __name__ == "__main__":
    unittest.main()
