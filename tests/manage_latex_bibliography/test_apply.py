from __future__ import annotations

import json

import pytest


def verified_entry(key="doe2024effects"):
    return {
        "citation_key": key,
        "entry_type": "article",
        "fields": {
            "author": "Doe, Jane",
            "title": "the effects of {AI}",
            "year": "2024",
            "journal": "Example Journal",
            "volume": "1",
            "number": "2",
            "pages": "1--20",
            "doi": "10.1000/example",
        },
        "sources": [
            {
                "url": "https://publisher.example/article",
                "retrieved_at": "2026-06-08T00:00:00Z",
            }
        ],
        "conflicts": [],
        "status": "verified",
        "verifier": "independent-agent",
        "requires_user_approval": False,
        "user_approval": None,
    }


def make_project(tmp_path, bib_text):
    project = tmp_path / "paper"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\n\\bibliography{refs}\n",
        encoding="utf-8",
    )
    (project / "refs.bib").write_text(bib_text, encoding="utf-8")
    return project


def test_apply_appends_entry_without_rewriting_existing_text(
    bibliography_module, tmp_path
):
    original = "@article{existing,\n  title = {Keep Formatting}\n}\n"
    project = make_project(tmp_path, original)
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["new_entries"] = [verified_entry()]

    result = bibliography_module.apply_proposal(proposal)

    text = (project / "refs.bib").read_text(encoding="utf-8")
    assert text.startswith(original)
    assert "@article{doe2024effects," in text
    assert "title = {The Effects of {AI}}" in text
    assert result["applied"] == ["doe2024effects"]
    assert result["applied_entries"][0]["verifier"] == "independent-agent"
    assert json.loads(
        (project / "bibliography-apply-result.json").read_text(encoding="utf-8")
    ) == result


def test_apply_replaces_only_approved_existing_entry(
    bibliography_module, tmp_path
):
    original_entry = {
        "author": "Doe, Jane",
        "title": "Wrong title",
        "journal": "Example Journal",
        "year": "2024",
    }
    project = make_project(
        tmp_path,
        "@article{existing,\n"
        "  author = {Doe, Jane},\n"
        "  title = {Wrong title},\n"
        "  journal = {Example Journal},\n"
        "  year = {2024}\n"
        "}\n\n"
        "% unrelated trailing text\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = verified_entry("existing")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
            "before_fields": original_entry,
        }
    )
    proposal["existing_entry_corrections"] = [correction]

    bibliography_module.apply_proposal(proposal)

    text = (project / "refs.bib").read_text(encoding="utf-8")
    assert "title = {The Effects of {AI}}" in text
    assert text.endswith("\n\n% unrelated trailing text\n")


def test_apply_rejects_correction_when_before_fields_do_not_match(
    bibliography_module, tmp_path
):
    project = make_project(
        tmp_path,
        "@article{existing, author={Doe, Jane}, title={Original}, "
        "journal={Example Journal}, year={2024}}\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = verified_entry("existing")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
            "before_fields": {"title": "Different"},
        }
    )
    proposal["existing_entry_corrections"] = [correction]

    with pytest.raises(ValueError, match="before_fields do not match"):
        bibliography_module.apply_proposal(proposal)


def test_apply_cli_loads_proposal_and_writes_result(
    bibliography_module, tmp_path
):
    project = make_project(tmp_path, "")
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["new_entries"] = [verified_entry()]
    proposal_path = project / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    assert bibliography_module.main(
        ["apply", "--proposal", str(proposal_path)]
    ) == 0
    assert (project / "bibliography-apply-result.json").is_file()
