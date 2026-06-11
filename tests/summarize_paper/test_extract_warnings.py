from __future__ import annotations

import json
from pathlib import Path


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, pages, metadata=None):
        self.pages = [FakePage(text) for text in pages]
        self.metadata = metadata or {}


def make_reader_factory(reader):
    def factory(_path: Path):
        return reader

    return factory


def _make_fetch_artifact(tmp_path: Path) -> Path:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    fetch_artifact = {
        "schema_version": 1,
        "input": str(pdf),
        "pdf_path": str(pdf),
        "resolution_path": ["local"],
        "source_url": None,
        "retrieved_at": "2026-06-08T00:00:00Z",
        "sha256": "0" * 64,
        "unresolved": None,
    }
    fetch_path = tmp_path / "summarize-paper-fetch.json"
    fetch_path.write_text(json.dumps(fetch_artifact))
    return fetch_path


def test_no_extractable_text_emits_warning(summary_module, tmp_path: Path):
    fetch_path = _make_fetch_artifact(tmp_path)
    reader = FakeReader(pages=["", "   ", "\n"])

    artifact = summary_module.extract(
        fetch_path,
        output_path=tmp_path / "summarize-paper-extract.json",
        reader_factory=make_reader_factory(reader),
    )

    assert "no-extractable-text" in artifact["warnings"]


def test_text_only_pages_emit_no_warning(summary_module, tmp_path: Path):
    fetch_path = _make_fetch_artifact(tmp_path)
    reader = FakeReader(pages=["Some real content."])

    artifact = summary_module.extract(
        fetch_path,
        output_path=tmp_path / "summarize-paper-extract.json",
        reader_factory=make_reader_factory(reader),
    )

    assert "no-extractable-text" not in artifact["warnings"]


def test_missing_author_block_emits_warning(summary_module, tmp_path: Path):
    fetch_path = _make_fetch_artifact(tmp_path)
    reader = FakeReader(pages=["A Single Long Title With No Recognizable Author Block"])

    artifact = summary_module.extract(
        fetch_path,
        output_path=tmp_path / "summarize-paper-extract.json",
        reader_factory=make_reader_factory(reader),
    )

    assert "author-guess-empty" in artifact["warnings"]
