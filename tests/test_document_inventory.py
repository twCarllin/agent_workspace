"""Regression coverage for shared deployment and document discovery."""

import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agent-flow/scripts"))
from document_inventory import skill_directories, skill_documents
import test_agent_refs


class DocumentInventoryTest(unittest.TestCase):
    def test_references_are_checked_and_retired_documents_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "skills/live"
            (live / "references").mkdir(parents=True)
            (live / "SKILL.md").write_text("Read references/agents.md")
            reference = live / "references/agents.md"
            reference.write_text("`code-writer` subagent; `missing-agent` subagent")
            retired = root / "skills/_deprecated/old"
            retired.mkdir(parents=True)
            (retired / "SKILL.md").write_text("`retired-agent` subagent")
            agents = root / ".claude/agents"
            agents.mkdir(parents=True)
            (agents / "code-writer.md").write_text("live")
            self.assertEqual(skill_documents(root), [live / "SKILL.md", reference])
            refs = test_agent_refs.scan_all_refs(root)
            self.assertEqual(
                refs,
                {
                    "code-writer": ["skills/live/references/agents.md"],
                    "missing-agent": ["skills/live/references/agents.md"],
                },
            )
            check = test_agent_refs.AgentRefIntegrationTest("test_all_refs_exist")
            check._all_refs = {"code-writer": refs["code-writer"]}
            check._agents_dir = agents
            check.test_all_refs_exist()
            check._all_refs = refs
            with self.assertRaisesRegex(AssertionError, "missing-agent"):
                check.test_all_refs_exist()

    def test_directory_without_entry_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "skills/incomplete"
            directory.mkdir(parents=True)
            self.assertEqual(skill_directories(root), [directory])
            self.assertEqual(skill_documents(root), [])

    def test_real_install_preserves_whole_skills_and_shared_inventory(self):
        with tempfile.TemporaryDirectory(prefix="inventory install ") as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            project_config = target / "pyproject.toml"
            project_config.write_text("[tool.black]\nline-length = 100\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "install_harness.py"),
                    "--target",
                    tmp,
                    "--harness",
                    "both",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            deployed = target / ".agents/skills"
            self.assertEqual(
                {p.name for p in deployed.iterdir()},
                {p.name for p in skill_directories(ROOT)},
            )
            self.assertFalse((deployed / "_deprecated").exists())
            sources = [
                (directory, source)
                for directory in skill_directories(ROOT)
                for source in directory.rglob("*")
                if source.is_file()
                and "__pycache__" not in source.parts
                and source.name != ".DS_Store"
            ]
            self.assertTrue(sources, "live skill inventory must contain files")
            for directory, source in sources:
                installed = deployed / directory.name / source.relative_to(directory)
                self.assertEqual(
                    installed.read_bytes(), source.read_bytes(), str(source)
                )
            self.assertTrue(
                (target / ".agent-flow/scripts/document_inventory.py").is_file()
            )
            self.assertEqual(
                project_config.read_text(), "[tool.black]\nline-length = 100\n"
            )
            policy = target / ".agent-flow/CODE_QUALITY.md"
            self.assertEqual(
                policy.read_bytes(), (ROOT / ".agent-flow/CODE_QUALITY.md").read_bytes()
            )
            assets = deployed / "eval-flow/assets"
            settings = tomllib.loads((assets / "black.toml").read_text())["tool"][
                "black"
            ]
            self.assertEqual(settings["line-length"], 88)
            self.assertFalse(settings["preview"])
            self.assertEqual(
                (assets / "requirements-format.txt").read_text().strip(),
                "black==" + settings["required-version"],
            )
            for role in ("code-writer", "code-reviewer"):
                common = (target / ".agent-flow/roles" / f"{role}.md").read_text()
                self.assertIn(".agent-flow/CODE_QUALITY.md", common)
                claude = (target / ".claude/agents" / f"{role}.md").read_text()
                self.assertEqual(claude.split("---", 2)[2].lstrip(), common)
                codex = tomllib.loads(
                    (target / ".codex/agents" / f"{role}.toml").read_text()
                )
                self.assertTrue(codex["developer_instructions"].startswith(common))
