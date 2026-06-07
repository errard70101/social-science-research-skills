from __future__ import annotations

import json


class StubProvider:
    def lookup_doi(self, doi):
        assert doi == "10.1234/example"
        return {
            "title": "Trade and Credit",
            "year": 2024,
            "authors": [{"family_name": "Lee"}],
            "doi": doi,
            "source": "stub",
        }

    def search_title(self, title):
        return None


def test_propose_writes_mapping_without_renaming_sources(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "download.pdf"
    source.write_bytes(b"fake-pdf")
    output = tmp_path / "proposal.json"
    monkeypatch.setattr(
        rename_module, "read_pdf_candidate", lambda path: {"doi": "10.1234/example"}
    )

    mapping = rename_module.propose(tmp_path, output, provider=StubProvider())

    assert source.exists()
    assert not (tmp_path / "Lee_2024_Trade_and_Credit.pdf").exists()
    assert mapping["items"][0]["source"] == "download.pdf"
    assert mapping["items"][0]["destination"] == "Lee_2024_Trade_and_Credit.pdf"
    assert json.loads(output.read_text()) == mapping


def test_propose_marks_missing_metadata_unresolved(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "unknown.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(rename_module, "read_pdf_candidate", lambda path: {})

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=None
    )

    assert mapping["items"] == []
    assert len(mapping["unresolved"]) == 1
    assert mapping["unresolved"][0]["source"] == "unknown.pdf"
    assert "metadata" in mapping["unresolved"][0]["reason"]


def test_title_search_requires_similarity_threshold(rename_module):
    candidate = {"title": "A Completely Different Paper"}

    assert (
        rename_module.accept_title_match(
            "Trade Credit and Firm Dynamics", candidate, threshold=0.9
        )
        is False
    )


def test_propose_groups_appendix_and_replication_materials(
    rename_module, tmp_path, monkeypatch
):
    (tmp_path / "study.pdf").write_bytes(b"paper")
    (tmp_path / "study_appendix.pdf").write_bytes(b"appendix")
    (tmp_path / "study_replication").mkdir()
    monkeypatch.setattr(
        rename_module, "read_pdf_candidate", lambda path: {"doi": "10.1234/example"}
    )

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=StubProvider()
    )

    destinations = {item["destination"] for item in mapping["items"]}
    assert "Lee_2024_Trade_and_Credit.pdf" in destinations
    assert "Lee_2024_Trade_and_Credit_Appendix.pdf" in destinations
    assert "Lee_2024_Trade_and_Credit_Replication" in destinations
