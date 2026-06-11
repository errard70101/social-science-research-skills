from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeResponse:
    def __init__(self, status_code, headers, content, url):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def get(self, url, **_: Any):
        self.calls.append(url)
        return self._responses[url]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_fetch_writes_versioned_artifact(summary_module, tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")

    artifact = summary_module.fetch(input_value=str(pdf), output_dir=tmp_path / "work")

    assert artifact["schema_version"] == 1
    assert artifact["input"] == str(pdf)
    payload = json.loads((tmp_path / "work" / "summarize-paper-fetch.json").read_text())
    assert payload == artifact


def test_url_download_does_not_clobber_existing_file(summary_module, tmp_path: Path):
    existing = tmp_path / "paper.pdf"
    existing.write_bytes(b"original")
    pdf_bytes = b"%PDF-1.4 fresh"
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
    assert saved != existing
    assert saved.name == "paper-1.pdf"
    assert saved.read_bytes() == pdf_bytes
    assert existing.read_bytes() == b"original"


def test_fetch_cli_command_writes_artifact(summary_module, tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    work = tmp_path / "work"

    assert (
        summary_module.main(
            [
                "fetch",
                "--input",
                str(pdf),
                "--output-dir",
                str(work),
            ]
        )
        == 0
    )
    assert (work / "summarize-paper-fetch.json").exists()
