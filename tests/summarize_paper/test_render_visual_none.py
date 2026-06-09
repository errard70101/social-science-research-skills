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


def _content_with_visual(kind: str = "none") -> dict:
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
        "headline_visual": {"kind": kind},
        "key_result": "Institutions matter.",
        "placement_in_literature": "Builds on prior institutional work.",
        "predecessor_citations": [],
        "limitations": "Mortality data is contested.",
        "followups": "Mechanisms in modern data.",
    }


def test_none_mode_collapses_block(summary_module, tmp_path: Path):
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content_with_visual("none")))
    output_tex = tmp_path / "summary.tex"

    summary_module.render(
        extract_path=_make_extract(tmp_path),
        content_path=content_path,
        output_tex=output_tex,
    )

    text = output_tex.read_text(encoding="utf-8")
    assert "<<headline_visual_block>>" not in text
    assert "\\begin{figure}" not in text
    assert "\\begin{table}" not in text
    assert "\\includegraphics" not in text
