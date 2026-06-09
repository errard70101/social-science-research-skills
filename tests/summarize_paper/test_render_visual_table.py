from __future__ import annotations

import json
from pathlib import Path

import pytest


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


def _table_content() -> dict:
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
        "headline_visual": {
            "kind": "table",
            "latex_table": (
                "\\begin{tabular}{lcc}\\toprule\n"
                "Outcome & Coef. & SE \\\\\n"
                "\\midrule\n"
                "Income & 1.32 & 0.41 \\\\\n"
                "\\bottomrule\n"
                "\\end{tabular}"
            ),
            "notes": [
                "Standard errors clustered by country.",
                "Sample: 64 ex-colonies.",
            ],
        },
        "key_result": "Institutions matter.",
        "placement_in_literature": "Builds on prior institutional work.",
        "predecessor_citations": [],
        "limitations": "Mortality data is contested.",
        "followups": "Mechanisms in modern data.",
    }


def test_reconstructed_table_renders_threeparttable(
    summary_module, tmp_path: Path
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_table_content()))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
        reproduce_tables=True,
    )

    text = output_tex.read_text(encoding="utf-8")
    assert "\\begin{threeparttable}" in text
    assert "\\begin{tabular}{lcc}" in text
    assert "\\begin{tablenotes}" in text
    assert "clustered by country" in text
    assert "Sample: 64 ex-colonies" in text


def test_reconstructed_table_requires_flag(
    summary_module, tmp_path: Path
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_table_content()))
    output_tex = tmp_path / "summary.tex"

    with pytest.raises(ValueError) as exc:
        summary_module.render(
            extract_path=_make_extract(tmp_path),
            content_path=content_path,
            output_tex=output_tex,
            reproduce_tables=False,
        )

    assert "reproduce-tables" in str(exc.value)


def test_reconstructed_table_requires_latex(
    summary_module, tmp_path: Path
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    content = _table_content()
    content["headline_visual"]["latex_table"] = ""
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(content))
    output_tex = tmp_path / "summary.tex"

    with pytest.raises(ValueError) as exc:
        summary_module.render(
            extract_path=_make_extract(tmp_path),
            content_path=content_path,
            output_tex=output_tex,
            reproduce_tables=True,
        )

    assert "latex_table" in str(exc.value)
