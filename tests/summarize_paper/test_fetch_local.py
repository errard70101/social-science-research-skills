from __future__ import annotations

import json
from pathlib import Path


def test_resolve_local_pdf_records_provenance(summary_module, tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub content")

    result = summary_module.resolve_input(str(pdf), output_dir=tmp_path / "work")

    assert result["pdf_path"] == str(pdf.resolve())
    assert result["resolution_path"] == ["local"]
    assert result["source_url"] is None
    assert result["unresolved"] is None
    assert result["sha256"]
    assert len(result["sha256"]) == 64
    assert "retrieved_at" in result


def test_fetch_writes_artifact_for_local_input(summary_module, tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub content")
    work = tmp_path / "work"

    artifact = summary_module.fetch(input_value=str(pdf), output_dir=work)

    assert artifact["schema_version"] == 1
    written = json.loads((work / "summarize-paper-fetch.json").read_text())
    assert written == artifact
