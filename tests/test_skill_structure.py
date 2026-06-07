from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "rename-and-organize-references"


def test_skill_has_required_frontmatter():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "\nname: rename-and-organize-references\n" in text
    assert re.search(r"\ndescription: .+\n", text)


def test_skill_contains_no_machine_specific_paths():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    forbidden = [
        "/Users/",
        "/home/linshih",
        ".gemini/config/plugins/superpowers",
        "conda run -n",
    ]
    assert all(value not in text for value in forbidden)


def test_skill_references_existing_bundled_files():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    expected = [
        "scripts/rename_references.py",
        "references/mapping-format.md",
    ]
    assert all(value in text for value in expected)
    assert all((SKILL / value).is_file() for value in expected)
