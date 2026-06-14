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


def test_extract_records_per_page_text(summary_module, tmp_path: Path):
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
        pages=["Page one body.\n\nJane Author, John Author", "Page two body.", ""],
        metadata={"/Title": "Stub Title", "/Author": "Stub Author"},
    )

    output_path = tmp_path / "summarize-paper-extract.json"
    artifact = summary_module.extract(
        fetch_path,
        output_path=output_path,
        reader_factory=make_reader_factory(reader),
    )

    assert artifact["schema_version"] == 2
    assert artifact["page_count"] == 3
    expected_page_0 = {"page": 1, "text": "Page one body.\n\nJane Author, John Author"}
    assert "pages" not in artifact
    pages_path = Path(artifact["pages_path"])
    assert pages_path == Path(f"{output_path}.pages.jsonl").resolve()
    assert pages_path.read_text(encoding="utf-8").splitlines() == [
        json.dumps(expected_page_0),
        json.dumps({"page": 2, "text": "Page two body."}),
        json.dumps({"page": 3, "text": ""}),
    ]
    pages = summary_module.load_extract_pages(artifact)
    assert iter(pages) is pages
    assert list(pages) == [
        expected_page_0,
        {"page": 2, "text": "Page two body."},
        {"page": 3, "text": ""},
    ]
    assert artifact["embedded_metadata"] == {
        "/Title": "Stub Title",
        "/Author": "Stub Author",
    }
    assert artifact["pdf_path"] == str(pdf)
    assert artifact["warnings"] == []
    assert not list(tmp_path.glob("*.tmp"))
