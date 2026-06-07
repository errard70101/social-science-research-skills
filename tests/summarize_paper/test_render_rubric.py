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


def _content(setup_words: int) -> dict:
    return {
        "schema_version": 1,
        "paper": {
            "authors": ["Acemoglu, Daron"],
            "year": 2001,
            "title": "Colonial Origins",
            "venue": "AER",
            "citation_key": "acemoglu2001colonial",
        },
        "one_sentence": (
            "Institutions shape long-run income via colonial origins."
        ),
        "setup": "word " * setup_words,
        "empirical_strategy": (
            "We instrument current institutions with settler mortality "
            "and run two-stage least squares to recover the causal effect."
        ),
        "identification_cartoon": (
            "Two countries with similar geography differ in modern "
            "institutions because their colonizers faced different "
            "disease environments centuries ago."
        ),
        "headline_visual": {"kind": "none"},
        "key_result": "Institutions explain a large share of cross-country variation.",
        "placement_in_literature": "Builds on prior institutional work.",
        "predecessor_citations": [],
        "limitations": "Mortality data is contested.",
        "followups": "Mechanisms in modern data.",
    }


def test_rubric_warning_when_setup_too_short(
    summary_module, tmp_path: Path
):
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content(setup_words=10)))
    output_tex = tmp_path / "summary.tex"

    result = summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
    )

    assert any("setup" in warning for warning in result["warnings"])


def test_no_rubric_warning_when_in_band(
    summary_module, tmp_path: Path
):
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content(setup_words=80)))
    output_tex = tmp_path / "summary.tex"

    result = summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
    )

    assert not any("setup" in warning for warning in result["warnings"])
