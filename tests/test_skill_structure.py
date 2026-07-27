from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
SKILLS = sorted(path.name for path in SKILLS_ROOT.iterdir() if path.is_dir())


def test_structure_checks_cover_every_discovered_skill(install_module):
    assert install_module.discover_skills() == SKILLS


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


@pytest.mark.parametrize("name", SKILLS)
def test_skill_references_existing_bundled_files(name):
    skill = ROOT / "skills" / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    references = set(re.findall(r"\$SKILL_DIR/(scripts/[A-Za-z0-9_.-]+)", text))
    references.update(re.findall(r"`(references/[A-Za-z0-9_.-]+)`", text))

    assert references
    assert all((skill / path).is_file() for path in references)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_openai_interface_metadata(name):
    metadata = ROOT / "skills" / name / "agents" / "openai.yaml"

    assert metadata.is_file()
    text = metadata.read_text(encoding="utf-8")
    display_name = re.search(r'^  display_name: "(.+)"$', text, re.MULTILINE)
    short_description = re.search(
        r'^  short_description: "(.+)"$', text, re.MULTILINE
    )
    default_prompt = re.search(r'^  default_prompt: "(.+)"$', text, re.MULTILINE)

    assert display_name
    assert short_description
    assert 25 <= len(short_description.group(1)) <= 64
    assert default_prompt
    assert f"${name}" in default_prompt.group(1)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_defines_skill_dir_before_using_it(name):
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    if "$SKILL_DIR/" not in text:
        pytest.skip(f"{name} does not use SKILL_DIR")

    assignment = "assign its absolute path to `SKILL_DIR`"
    assert assignment in text
    assert text.index(assignment) < text.index("$SKILL_DIR/")


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_no_empty_second_level_section(name):
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    assert not re.search(r"^## [^\n]+\n\s*^## ", text, re.MULTILINE)


def test_repec_skill_omits_redundant_synergy_section():
    text = (
        ROOT / "skills" / "literature-search-repec" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "## Synergy with other skills" not in text


def test_client_instruction_files_stay_in_sync():
    paths = [ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]
    contents = {path.read_bytes() for path in paths}
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert len(contents) == 1
    assert "`AGENTS.md` is the canonical client instruction file" in contributing


SUMMARY_SKILL = ROOT / "skills" / "summarize-academic-paper"
BIBLIOGRAPHY_SKILL = ROOT / "skills" / "manage-latex-bibliography"


def test_readme_describes_headline_visuals_as_page_snapshots():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Optional cropped headline visuals" not in readme
    assert "Optional page-snapshot headline visuals" in readme


def test_summary_points_to_canonical_bibliography_citation_key_rules():
    summary_docs = [
        (SUMMARY_SKILL / "SKILL.md").read_text(encoding="utf-8"),
        (SUMMARY_SKILL / "references" / "section-rubric.md").read_text(
            encoding="utf-8"
        ),
    ]
    bibliography = (BIBLIOGRAPHY_SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "authorYearFirstTitleWord" in bibliography
    for text in summary_docs:
        assert "authorYearFirstWord" not in text
        assert "authorYearFirstTitleWord" not in text
        assert "manage-latex-bibliography" in text
        assert "Entry Rules" in text


def test_bibliography_infers_clear_operation_without_forced_menu():
    text = (BIBLIOGRAPHY_SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "STOP AND ASK" not in text
    assert not re.search(r"[\u4e00-\u9fff]", text)
    assert (
        "When the request clearly identifies one operation, proceed without asking."
        in text
    )


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


def test_repec_runtime_dependency_is_packaged():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"beautifulsoup4' in pyproject
