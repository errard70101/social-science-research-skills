from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "rename-and-organize-references": [
        "scripts/rename_references.py",
        "references/mapping-format.md",
    ],
    "manage-latex-bibliography": [
        "scripts/manage_bibliography.py",
        "references/verification-rules.md",
        "references/title-case-rules.md",
    ],
    "summarize-academic-paper": [
        "scripts/summarize_paper.py",
        "references/section-rubric.md",
        "references/input-sources.md",
    ],
    "skill-development-workflow": [
        "scripts/skill_development_workflow.py",
        "references/prompt-contracts.md",
    ],
}


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_required_frontmatter(name):
    skill = ROOT / "skills" / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert f"\nname: {name}\n" in text
    assert re.search(r"\ndescription: .+\n", text)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_contains_no_machine_specific_paths(name):
    skill = ROOT / "skills" / name
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in skill.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    forbidden = [
        "/Users/",
        "/home/linshih",
        ".gemini/config/plugins/superpowers",
        "conda run -n",
    ]
    assert all(value not in text for value in forbidden)


@pytest.mark.parametrize(("name", "expected"), SKILLS.items())
def test_skill_references_existing_bundled_files(name, expected):
    skill = ROOT / "skills" / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert all(value in text for value in expected)
    assert all((skill / value).is_file() for value in expected)


SUMMARY_SKILL = ROOT / "skills" / "summarize-academic-paper"


def test_summary_skill_template_exists_and_has_slots():
    template = (SUMMARY_SKILL / "references" / "template.tex").read_text(
        encoding="utf-8"
    )
    assert "\\documentclass" in template
    assert "<<paper.title>>" in template
    assert "<<headline_visual_block>>" in template


def test_bibliography_skill_does_not_bundle_aea_style():
    skill = ROOT / "skills" / "manage-latex-bibliography"

    assert not list(skill.rglob("aea.bst"))
