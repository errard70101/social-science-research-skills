from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _make_extract_with_candidate(
    tmp_path: Path, label: str = "Table 3", page: int = 11
) -> Path:
    artifact = {
        "schema_version": 1,
        "pdf_path": str(tmp_path / "paper.pdf"),
        "page_count": max(page, 1),
        "pages": [{"page": page, "text": f"{label}: Main effects."}],
        "embedded_metadata": {},
        "title_guess": None,
        "author_guesses": [],
        "table_candidates": [
            {
                "label": label,
                "caption": "Main effects.",
                "page": page,
                "kind": label.split()[0].lower(),
            }
        ],
        "warnings": [],
    }
    path = tmp_path / "summarize-paper-extract.json"
    path.write_text(json.dumps(artifact))
    return path


def _content_for_image(label: str = "Table 3", page: int = 11) -> dict:
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
            "kind": "image",
            "label": label,
            "page": page,
        },
        "key_result": "Institutions matter.",
        "placement_in_literature": "Builds on prior institutional work.",
        "predecessor_citations": [],
        "limitations": "Mortality data is contested.",
        "followups": "Mechanisms in modern data.",
    }


def test_image_mode_writes_png_and_block(summary_module, tmp_path: Path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract_path = _make_extract_with_candidate(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content_for_image()))
    output_tex = tmp_path / "Authors_2001_Title_Summary.tex"
    asset_dir = tmp_path / "Authors_2001_Title_Summary" / "figures"

    captured: dict[str, Any] = {}

    def fake_render_page(pdf_path: Path, page_number: int) -> bytes:
        captured["pdf_path"] = str(pdf_path)
        captured["page_number"] = page_number
        return b"\x89PNG\r\n\x1a\n-stub"

    monkeypatch.setattr(summary_module, "_render_page_to_png", fake_render_page)

    summary_module.render(
        extract_path=extract_path,
        content_path=content_path,
        output_tex=output_tex,
        include_table="Table 3",
    )

    assert captured["page_number"] == 11
    image_path = asset_dir / "table-3.png"
    assert image_path.exists()
    text = output_tex.read_text(encoding="utf-8")
    assert "\\begin{figure}" in text
    assert "\\includegraphics" in text
    assert "Authors_2001_Title_Summary/figures/table-3.png" in text
    assert "Source: Table 3" in text


def test_image_mode_label_must_match_candidate(
    summary_module, tmp_path: Path, monkeypatch
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract_path = _make_extract_with_candidate(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content_for_image(label="Table 9")))
    output_tex = tmp_path / "summary.tex"

    monkeypatch.setattr(
        summary_module,
        "_render_page_to_png",
        lambda *args, **kwargs: b"",
    )

    with pytest.raises(ValueError) as exc:
        summary_module.render(
            extract_path=extract_path,
            content_path=content_path,
            output_tex=output_tex,
            include_table="Table 9",
        )

    assert "Table 9" in str(exc.value)


def test_image_mode_without_pymupdf_fails_loudly(
    summary_module, tmp_path: Path, monkeypatch
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract_path = _make_extract_with_candidate(tmp_path)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content_for_image()))
    output_tex = tmp_path / "summary.tex"

    def raise_import(*_: Any, **__: Any) -> None:
        raise ImportError("No module named 'fitz'")

    monkeypatch.setattr(summary_module, "_render_page_to_png", raise_import)

    with pytest.raises(RuntimeError) as exc:
        summary_module.render(
            extract_path=extract_path,
            content_path=content_path,
            output_tex=output_tex,
            include_table="Table 3",
        )

    assert "pymupdf" in str(exc.value).lower()
    assert "render" in str(exc.value).lower()


def test_image_mode_rejects_inconsistent_manual_page(
    summary_module, tmp_path: Path, monkeypatch
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract_path = _make_extract_with_candidate(tmp_path, label="Table 3", page=11)
    content_path = tmp_path / "content.json"
    content_path.write_text(json.dumps(_content_for_image(label="Table 3", page=999)))
    output_tex = tmp_path / "summary.tex"

    monkeypatch.setattr(
        summary_module,
        "_render_page_to_png",
        lambda *args, **kwargs: b"",
    )

    with pytest.raises(ValueError) as exc:
        summary_module.render(
            extract_path=extract_path,
            content_path=content_path,
            output_tex=output_tex,
            include_table="Table 3",
        )

    assert "does not match candidate page" in str(exc.value)
    assert "999" in str(exc.value)
    assert "11" in str(exc.value)
