from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FakeResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeClient:
    def __init__(self, responses: dict[str, FakeResponse]):
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        self.calls.append(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected request: {url}")
        return self._responses[url]

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def test_generic_pdf_url_is_downloaded(summary_module, tmp_path: Path):
    pdf_bytes = b"%PDF-1.4 stub"
    client = FakeClient(
        {
            "https://example.org/paper.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://example.org/paper.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://example.org/paper.pdf",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    saved = Path(result["pdf_path"])
    assert saved.exists()
    assert saved.read_bytes() == pdf_bytes
    assert result["resolution_path"] == ["url"]
    assert result["source_url"] == "https://example.org/paper.pdf"
    assert result["sha256"] == summary_module._sha256_bytes(pdf_bytes)


def test_arxiv_abs_url_is_rewritten_to_pdf(summary_module, tmp_path: Path):
    pdf_bytes = b"%PDF-1.4 arxiv stub"
    client = FakeClient(
        {
            "https://arxiv.org/pdf/2401.01234.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://arxiv.org/pdf/2401.01234.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://arxiv.org/abs/2401.01234",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["url", "arxiv"]
    assert client.calls == ["https://arxiv.org/pdf/2401.01234.pdf"]
    assert Path(result["pdf_path"]).read_bytes() == pdf_bytes


def test_html_landing_page_uses_citation_pdf_url_meta(
    summary_module, tmp_path: Path
):
    landing = (
        "<html><head>"
        "<meta name=\"citation_pdf_url\" "
        "content=\"https://journal.example/article.pdf\">"
        "</head><body></body></html>"
    )
    pdf_bytes = b"%PDF-1.4 journal stub"
    client = FakeClient(
        {
            "https://journal.example/article": FakeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                content=landing.encode("utf-8"),
                url="https://journal.example/article",
            ),
            "https://journal.example/article.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://journal.example/article.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://journal.example/article",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["url", "citation-pdf-meta"]
    assert client.calls == [
        "https://journal.example/article",
        "https://journal.example/article.pdf",
    ]


def test_citation_pdf_url_meta_handles_flipped_attribute_order(
    summary_module, tmp_path: Path
):
    landing = (
        "<html><head>"
        "<meta content=\"https://journal.example/article.pdf\" "
        "name=\"citation_pdf_url\">"
        "</head><body></body></html>"
    )
    pdf_bytes = b"%PDF-1.4 journal stub"
    client = FakeClient(
        {
            "https://journal.example/article": FakeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                content=landing.encode("utf-8"),
                url="https://journal.example/article",
            ),
            "https://journal.example/article.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://journal.example/article.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://journal.example/article",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["url", "citation-pdf-meta"]
    assert client.calls == [
        "https://journal.example/article",
        "https://journal.example/article.pdf",
    ]


def test_non_pdf_response_is_unresolved(summary_module, tmp_path: Path):
    client = FakeClient(
        {
            "https://example.org/paywall": FakeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>nothing useful</html>",
                url="https://example.org/paywall",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://example.org/paywall",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["pdf_path"] is None
    assert result["unresolved"]
    assert "content-type" in result["unresolved"]


def test_url_is_preferred_even_if_shadowed_by_local_file(
    summary_module, tmp_path: Path, monkeypatch
):
    shadowed_dir = tmp_path / "https:" / "example.org"
    shadowed_dir.mkdir(parents=True, exist_ok=True)
    shadowed_file = shadowed_dir / "paper.pdf"
    shadowed_file.write_bytes(b"%PDF-1.4 local file content")

    monkeypatch.chdir(tmp_path)

    pdf_bytes = b"%PDF-1.4 remote url content"
    client = FakeClient(
        {
            "https://example.org/paper.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://example.org/paper.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "https://example.org/paper.pdf",
        output_dir=tmp_path / "out",
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["url"]
    assert result["source_url"] == "https://example.org/paper.pdf"
    assert Path(result["pdf_path"]).read_bytes() == pdf_bytes

