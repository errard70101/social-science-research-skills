from __future__ import annotations

import json
from pathlib import Path


def _make_extract(tmp_path: Path) -> Path:
    artifact = {
        "schema_version": 1,
        "pdf_path": str(tmp_path / "paper.pdf"),
        "page_count": 1,
        "pages": [{"page": 1, "text": ""}],
        "embedded_metadata": {},
        "title_guess": None,
        "author_guesses": [],
        "table_candidates": [],
        "warnings": [],
    }
    path = tmp_path / "summarize-paper-extract.json"
    path.write_text(json.dumps(artifact))
    return path


def _base_content() -> dict:
    return {
        "schema_version": 1,
        "paper": {
            "authors": ["Acemoglu, Daron"],
            "year": 2001,
            "title": "Colonial Origins",
            "venue": "AER",
            "citation_key": "acemoglu2001colonial",
        },
        "one_sentence": "Institutions shape long-run income.",
        "setup": "Cross-country differences.",
        "empirical_strategy": "2SLS.",
        "identification_cartoon": "Compare colonies.",
        "headline_visual": {"kind": "none"},
        "key_result": "Institutions matter.",
        "limitations": "Settler mortality is contested.",
        "followups": "Mechanisms in modern data.",
    }


def test_inline_citation_placeholders_become_cite_commands(
    summary_module, tmp_path: Path
):
    content = _base_content()
    content["placement_in_literature"] = (
        "Builds on {{north1990institutions}} and "
        "{{engerman2002factor}}'s factor-endowments framework."
    )
    content["predecessor_citations"] = [
        {"key": "north1990institutions", "prose_hint": "North (1990)"},
        {"key": "engerman2002factor", "prose_hint": "Engerman et al."},
    ]
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(content))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    assert "\\citep{north1990institutions}" in text
    assert "\\citep{engerman2002factor}" in text
    assert "{{north1990institutions}}" not in text


def test_empty_predecessor_list_emits_no_cite(
    summary_module, tmp_path: Path
):
    content = _base_content()
    content["placement_in_literature"] = (
        "Sits between earlier descriptive work and later experimental "
        "approaches; no single direct predecessor."
    )
    content["predecessor_citations"] = []
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(content))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    placement_index = text.index("Where this sits")
    bibliography_index = text.index("\\bibliographystyle")
    placement_section = text[placement_index:bibliography_index]
    assert "\\cite{}" not in placement_section
    assert "\\citep{}" not in placement_section
    assert "\\cite{" not in placement_section
    assert "\\citep{" not in placement_section


def test_surname_handling_with_particles(summary_module):
    assert summary_module._surname("J. B. De Long") == "De Long"
    assert summary_module._surname("Roy van der Weide") == "van der Weide"
    assert summary_module._surname("Jonathan de Quidt") == "de Quidt"
    assert summary_module._surname("John Doe") == "Doe"
    assert summary_module._surname("de Quidt, Jonathan") == "de Quidt"

