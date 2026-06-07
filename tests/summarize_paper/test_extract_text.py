from __future__ import annotations

import json
from pathlib import Path


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(
        self,
        pages: list[str],
        metadata: dict[str, str] | None = None,
    ):
        self.pages = [FakePage(text) for text in pages]
        self.metadata = metadata or {}


def make_reader_factory(reader: FakeReader):
    def factory(_path: Path) -> FakeReader:
        return reader

    return factory


def test_extract_records_per_page_text(
    summary_module, tmp_path: Path
):
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
    reader = FakeReader(
        pages=["Page one body.", "Page two body.", ""],
        metadata={"/Title": "Stub Title", "/Author": "Stub Author"},
    )

    artifact = summary_module.extract(
        fetch_path,
        output_path=tmp_path / "summarize-paper-extract.json",
        reader_factory=make_reader_factory(reader),
    )

    assert artifact["schema_version"] == 1
    assert artifact["page_count"] == 3
    assert artifact["pages"][0] == {"page": 1, "text": "Page one body."}
    assert artifact["pages"][2] == {"page": 3, "text": ""}
    assert artifact["embedded_metadata"] == {
        "/Title": "Stub Title",
        "/Author": "Stub Author",
    }
    assert artifact["pdf_path"] == str(pdf)
    assert artifact["warnings"] == []
