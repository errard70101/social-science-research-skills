from __future__ import annotations

import json
from pathlib import Path

import pytest


def _valid_content() -> dict:
    return {
        "schema_version": 1,
        "paper": {
            "authors": ["Acemoglu, Daron", "Johnson, Simon", "Robinson, James"],
            "year": 2001,
            "title": "Colonial Origins of Comparative Development",
            "venue": "American Economic Review",
            "citation_key": "acemoglu2001colonial",
        },
        "one_sentence": "Institutions shape long-run income.",
        "setup": "We study cross-country differences.",
        "empirical_strategy": "Two-stage least squares.",
        "identification_cartoon": "Compare colonies that differed only in mortality.",
        "headline_visual": {"kind": "none"},
        "key_result": "Institutions matter.",
        "placement_in_literature": "Builds on North (1990).",
        "predecessor_citations": [],
        "limitations": "Settler mortality data is contested.",
        "followups": "Test mechanisms in modern data.",
    }


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


def test_format_author_string_uses_oxford_comma(summary_module):
    assert (
        summary_module.format_author_string(
            [
                "Acemoglu, Daron",
                "Johnson, Simon",
                "Robinson, James",
            ]
        )
        == "Acemoglu, Johnson, and Robinson"
    )


def test_format_author_string_uses_et_al_for_four_or_more(summary_module):
    assert (
        summary_module.format_author_string(
            [
                "Acemoglu, Daron",
                "Johnson, Simon",
                "Robinson, James",
                "Smith, Jane",
            ]
        )
        == "Acemoglu et al."
    )


def test_render_writes_tex_with_substituted_slots(summary_module, tmp_path: Path):
    extract_path = _make_extract(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_valid_content()))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=extract_path,
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    assert "<<paper.title>>" not in text
    assert "Colonial Origins of Comparative Development" in text
    assert "Acemoglu, Johnson, and Robinson (2001)" in text
    assert "\\citep{acemoglu2001colonial}" in text
    assert "\\bibliographystyle{aea}" in text
    assert "\\bibliography{references}" in text


def test_render_reports_content_path_for_missing_nested_slot(
    summary_module, tmp_path: Path, monkeypatch
):
    extract_path = _make_extract(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_valid_content()))
    output_tex = tmp_path / "summary.tex"
    monkeypatch.setattr(summary_module, "_load_template", lambda: "<<paper.abstract>>")

    with pytest.raises(ValueError) as error:
        summary_module.render(
            extract_path=extract_path,
            content_path=content_path,
            output_tex=output_tex,
        )

    message = str(error.value)
    assert str(content_path) in message
    assert "paper.abstract" in message


def test_render_reports_content_path_for_missing_top_level_slot(
    summary_module, tmp_path: Path, monkeypatch
):
    extract_path = _make_extract(tmp_path)
    content = _valid_content()
    content.pop("one_sentence")
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(content))
    output_tex = tmp_path / "summary.tex"
    monkeypatch.setattr(summary_module, "validate_content", lambda content: None)
    monkeypatch.setattr(
        summary_module,
        "CONTENT_REQUIRED_SECTIONS",
        tuple(
            section
            for section in summary_module.CONTENT_REQUIRED_SECTIONS
            if section != "one_sentence"
        ),
    )
    monkeypatch.setattr(summary_module, "_load_template", lambda: "<<one_sentence>>")

    with pytest.raises(ValueError) as error:
        summary_module.render(
            extract_path=extract_path,
            content_path=content_path,
            output_tex=output_tex,
        )

    message = str(error.value)
    assert str(content_path) in message
    assert "one_sentence" in message


def test_render_is_atomic(summary_module, tmp_path: Path):
    extract_path = _make_extract(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_valid_content()))
    output_tex = tmp_path / "summary.tex"
    output_tex.write_text("PRE-EXISTING")

    summary_module.render(
        extract_path=extract_path,
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    assert text.startswith("\\documentclass")
    assert "PRE-EXISTING" not in text
    siblings = [name for name in tmp_path.iterdir() if name.suffix == ".tmp"]
    assert siblings == []


def test_render_escapes_special_characters_in_paper_metadata(
    summary_module, tmp_path: Path
):
    extract_path = _make_extract(tmp_path)
    content = _valid_content()
    content["paper"] = {
        "authors": ["A & B", r"C\\D"],
        "year": 2001,
        "title": r"50% of $x$ #1_2 {draft} \\ ~ ^",
        "venue": r"R&D_{Lab} 100%",
        "citation_key": "acemoglu2001colonial",
    }
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(content))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=extract_path,
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    escaped_text = (
        r"50\% of \$x\$ \#1\_2 \{draft\} "
        r"\textbackslash{}\textbackslash{} \textasciitilde{} \textasciicircum{}"
    )
    assert (
        escaped_text in text
    )
    assert r"R\&D\_\{Lab\} 100\%" in text
    assert r"B and C\textbackslash{}\textbackslash{}D (2001)" in text
