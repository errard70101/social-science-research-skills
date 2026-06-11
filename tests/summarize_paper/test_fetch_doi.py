from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        url: str = "",
        text: str | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.text = (
            text if text is not None else content.decode("utf-8", errors="replace")
        )
        self.url = url

    def json(self) -> Any:
        return json.loads(self.text)

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


def test_doi_resolves_to_open_access_pdf(summary_module, tmp_path: Path, monkeypatch):
    pdf_bytes = b"%PDF-1.4 doi stub"
    client = FakeClient(
        {
            "https://doi.org/10.1257/aer.20180754": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://doi.org/10.1257/aer.20180754",
            ),
        }
    )

    result = summary_module.resolve_input(
        "10.1257/aer.20180754",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["doi"]
    assert result["source_url"] == "https://doi.org/10.1257/aer.20180754"
    assert Path(result["pdf_path"]).read_bytes() == pdf_bytes


def test_paywalled_doi_falls_back_to_unpaywall(
    summary_module, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "user@example.org")
    pdf_bytes = b"%PDF-1.4 oa stub"
    unpaywall_json = json.dumps(
        {
            "best_oa_location": {
                "url_for_pdf": "https://openaccess.example/paper.pdf",
            }
        }
    )
    client = FakeClient(
        {
            "https://doi.org/10.1234/paywalled": FakeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>paywall</html>",
                url="https://publisher.example/paywalled",
            ),
            "https://api.unpaywall.org/v2/10.1234/paywalled?email=user%40example.org": FakeResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                content=unpaywall_json.encode("utf-8"),
                url="https://api.unpaywall.org/v2/10.1234/paywalled",
            ),
            "https://openaccess.example/paper.pdf": FakeResponse(
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                url="https://openaccess.example/paper.pdf",
            ),
        }
    )

    result = summary_module.resolve_input(
        "10.1234/paywalled",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["resolution_path"] == ["doi", "unpaywall"]
    assert result["source_url"] == "https://openaccess.example/paper.pdf"
    assert Path(result["pdf_path"]).read_bytes() == pdf_bytes


def test_paywalled_doi_without_email_is_unresolved(
    summary_module, tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    client = FakeClient(
        {
            "https://doi.org/10.1234/paywalled": FakeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>paywall</html>",
                url="https://publisher.example/paywalled",
            ),
        }
    )

    result = summary_module.resolve_input(
        "10.1234/paywalled",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["pdf_path"] is None
    assert result["resolution_path"] == ["doi"]
    assert "UNPAYWALL_EMAIL" in result["unresolved"]


def test_doi_http_error_is_unresolved(summary_module, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    client = FakeClient(
        {
            "https://doi.org/10.1234/missing": FakeResponse(
                status_code=404,
                headers={"content-type": "text/html"},
                content=b"<html>not found</html>",
                url="https://doi.org/10.1234/missing",
            ),
        }
    )

    result = summary_module.resolve_input(
        "10.1234/missing",
        output_dir=tmp_path,
        http_client_factory=lambda: client,
    )

    assert result["pdf_path"] is None
    assert result["resolution_path"] == ["doi"]
    assert "404" in result["unresolved"]
