"""Shared inventory of live skill directories and their Markdown contracts."""
from pathlib import Path


def skill_directories(root: Path) -> list[Path]:
    """Return deployable directories in stable order, excluding retired skills.

    Include every live directory, even when its SKILL.md is missing, so deployment
    does not silently omit inputs that existing consistency checks must inspect.
    """
    return sorted(path for path in (root / "skills").iterdir()
                  if path.is_dir() and path.name != "_deprecated")


def skill_documents(root: Path) -> list[Path]:
    """Return existing entry documents and direct Markdown references."""
    documents = []
    for directory in skill_directories(root):
        entry = directory / "SKILL.md"
        if entry.is_file():
            documents.append(entry)
        documents.extend(sorted((directory / "references").glob("*.md")))
    return documents
