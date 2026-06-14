from __future__ import annotations

import json

import pytest


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
    assert mapping["items"][0]["confidence"] == "high"
    assert mapping["items"][0]["provenance"] == "doi-lookup"
    assert json.loads(output.read_text()) == mapping


def test_propose_marks_missing_metadata_unresolved(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "unknown.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(rename_module, "read_pdf_candidate", lambda path: {})

    mapping = rename_module.propose(tmp_path, tmp_path / "proposal.json", provider=None)

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


def test_propose_groups_related_material_with_longest_matching_main_stem(
    rename_module, tmp_path, monkeypatch
):
    (tmp_path / "study.pdf").write_bytes(b"paper")
    (tmp_path / "study_v2.pdf").write_bytes(b"revised")
    (tmp_path / "study_v2_appendix.pdf").write_bytes(b"appendix")
    metadata = {
        "study.pdf": {
            "title": "Original Study",
            "year": 2023,
            "authors": [{"family_name": "Lee"}],
        },
        "study_v2.pdf": {
            "title": "Revised Study",
            "year": 2024,
            "authors": [{"family_name": "Kim"}],
        },
    }
    monkeypatch.setattr(
        rename_module, "read_pdf_candidate", lambda path: metadata[path.name]
    )

    mapping = rename_module.propose(tmp_path, tmp_path / "proposal.json", provider=None)

    destinations = {item["source"]: item["destination"] for item in mapping["items"]}
    assert (
        destinations["study_v2_appendix.pdf"] == "Kim_2024_Revised_Study_Appendix.pdf"
    )


def test_title_search_result_with_doi_still_requires_review(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "trade_credit.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {"title": "Trade Credit and Firm Dynamics"},
    )

    class TitleProvider:
        def lookup_doi(self, doi):
            raise AssertionError("DOI lookup should not run")

        def search_title(self, title):
            return {
                "title": title,
                "year": 2024,
                "authors": [{"family_name": "Lee"}],
                "doi": "10.1234/title-result",
                "source": "stub",
            }

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=TitleProvider()
    )

    assert mapping["items"][0]["confidence"] == "review"
    assert mapping["items"][0]["provenance"] == "title-search"


def test_incomplete_doi_result_falls_through_to_valid_title_result(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "study.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {
            "doi": "10.1234/example",
            "title": "Trade and Credit",
        },
    )

    class FallbackProvider:
        def lookup_doi(self, doi):
            return {
                "title": "Trade and Credit",
                "year": None,
                "authors": [],
                "doi": doi,
                "source": "stub",
            }

        def search_title(self, title):
            return {
                "title": title,
                "year": 2024,
                "authors": [{"family_name": "Lee"}],
                "doi": "10.1234/search",
                "source": "stub",
            }

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=FallbackProvider()
    )

    assert mapping["items"][0]["destination"] == "Lee_2024_Trade_and_Credit.pdf"
    assert mapping["items"][0]["confidence"] == "review"
    assert mapping["items"][0]["provenance"] == "title-search"


def test_complete_local_metadata_proposes_offline_at_review_confidence(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "local.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {
            "title": "Local Evidence",
            "year": 2024,
            "authors": [{"display_name": "Lee, Ada", "family_name": "Lee"}],
            "doi": "10.1234/unverified",
            "source": "pdf-metadata",
        },
    )

    mapping = rename_module.propose(tmp_path, tmp_path / "proposal.json", provider=None)

    assert mapping["items"][0]["destination"] == "Lee_2024_Local_Evidence.pdf"
    assert mapping["items"][0]["confidence"] == "review"
    assert mapping["items"][0]["provenance"] == "pdf-metadata"


def test_complete_local_metadata_skips_provider_calls(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "local.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {
            "title": "Local Evidence",
            "year": 2024,
            "authors": [{"family_name": "Lee"}],
            "doi": "10.1234/local",
            "source": "pdf-metadata",
        },
    )

    class ProviderSpy:
        def __init__(self):
            self.calls = []

        def lookup_doi(self, doi):
            self.calls.append(("doi", doi))
            return None

        def search_title(self, title):
            self.calls.append(("title", title))
            return None

    provider = ProviderSpy()

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=provider
    )

    assert provider.calls == []
    assert mapping["items"][0]["confidence"] == "review"
    assert mapping["items"][0]["provenance"] == "pdf-metadata"


def test_incomplete_local_metadata_stays_unresolved_offline(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "local.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {
            "title": "Local Evidence",
            "authors": [],
            "source": "pdf-metadata",
        },
    )

    mapping = rename_module.propose(tmp_path, tmp_path / "proposal.json", provider=None)

    assert mapping["items"] == []
    assert mapping["unresolved"][0]["source"] == "local.pdf"


def test_read_pdf_candidate_returns_conservative_provider_shaped_metadata(
    rename_module, tmp_path, monkeypatch
):
    class FakePage:
        def extract_text(self):
            return "doi: 10.1234/example"

    class FakeMetadata:
        title = "Trade and Credit"
        author = "Lee, Ada; Kim, Bo"
        year = "2024"

    class FakeReader:
        pages = [FakePage()]
        metadata = FakeMetadata()

        def __init__(self, path):
            pass

    monkeypatch.setattr(rename_module, "PdfReader", FakeReader)

    candidate = rename_module.read_pdf_candidate(tmp_path / "paper.pdf")

    assert candidate == {
        "title": "Trade and Credit",
        "year": 2024,
        "authors": [
            {"display_name": "Lee, Ada", "family_name": "Lee"},
            {"display_name": "Kim, Bo", "family_name": "Kim"},
        ],
        "doi": "10.1234/example",
        "source": "pdf-metadata",
    }


def test_read_pdf_candidate_leaves_ambiguous_authors_unresolved(
    rename_module, tmp_path, monkeypatch
):
    class FakeMetadata:
        title = "Trade and Credit"
        author = "Ada Lee and Bo Kim"
        year = "2024"

    class FakeReader:
        pages = []
        metadata = FakeMetadata()

        def __init__(self, path):
            pass

    monkeypatch.setattr(rename_module, "PdfReader", FakeReader)

    candidate = rename_module.read_pdf_candidate(tmp_path / "paper.pdf")

    assert candidate["authors"] == []


def test_related_filename_failure_is_unresolved_and_mapping_is_written(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "study.pdf"
    appendix = tmp_path / "study_appendix.pdf"
    source.write_bytes(b"paper")
    appendix.write_bytes(b"appendix")
    output = tmp_path / "proposal.json"
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {
            "title": "A",
            "year": 2024,
            "authors": [{"family_name": "L" * 165}],
            "source": "pdf-metadata",
        },
    )

    mapping = rename_module.propose(tmp_path, output, provider=None)

    assert output.exists()
    assert json.loads(output.read_text()) == mapping
    assert mapping["items"][0]["source"] == "study.pdf"
    assert mapping["unresolved"] == [
        {
            "source": "study_appendix.pdf",
            "reason": "max_length leaves no room for a nonempty title",
        }
    ]


def test_provider_exception_leaves_source_unresolved(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "study.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {"doi": "10.1234/example", "title": "Study"},
    )

    class FailingProvider:
        def lookup_doi(self, doi):
            raise OSError("network unavailable")

        def search_title(self, title):
            raise OSError("network unavailable")

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=FailingProvider()
    )

    assert mapping["items"] == []
    assert mapping["unresolved"][0]["source"] == "study.pdf"


def test_openalex_metadata_marks_fallback_family_names_as_inferred(
    rename_module,
):
    work = {
        "title": "Trade and Credit",
        "publication_year": 2024,
        "doi": "https://doi.org/10.1234/example",
        "authorships": [
            {"author": {"display_name": "Ada van Lee", "family_name": "van Lee"}},
            {"author": {"display_name": "Bo Kim"}},
        ],
    }

    metadata = rename_module.OpenAlexProvider()._metadata(work)

    assert metadata == {
        "title": "Trade and Credit",
        "year": 2024,
        "authors": [
            {"display_name": "Ada van Lee", "family_name": "van Lee"},
            {
                "display_name": "Bo Kim",
                "family_name": "Kim",
                "family_name_inferred": True,
            },
        ],
        "doi": "10.1234/example",
        "source": "openalex",
        "metadata_quality": "inferred-author-names",
        "requires_review": True,
    }


def test_openalex_uses_raw_author_name_for_conservative_fallback(rename_module):
    work = {
        "title": "Trade and Credit",
        "publication_year": 2024,
        "doi": "https://doi.org/10.1234/example",
        "authorships": [
            {
                "author": {"display_name": "A. Lee"},
                "raw_author_name": "Lee, Ada",
            }
        ],
    }

    metadata = rename_module.OpenAlexProvider()._metadata(work)

    assert metadata["authors"] == [
        {
            "display_name": "A. Lee",
            "family_name": "Lee",
            "family_name_inferred": True,
        }
    ]
    assert metadata["requires_review"] is True


def test_openalex_leaves_ambiguous_compound_author_unresolved(rename_module):
    work = {
        "title": "Trade and Credit",
        "publication_year": 2024,
        "doi": "https://doi.org/10.1234/example",
        "authorships": [
            {
                "author": {"display_name": "Ada van Lee"},
                "raw_author_name": "Ada van Lee",
            }
        ],
    }

    metadata = rename_module.OpenAlexProvider()._metadata(work)

    assert metadata["authors"] == [{"display_name": "Ada van Lee", "family_name": ""}]
    assert metadata["metadata_quality"] == "unresolved-author-names"
    assert metadata["requires_review"] is True


def test_inferred_openalex_doi_author_requires_review_confidence(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "study.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {"doi": "10.1234/example"},
    )
    metadata = rename_module.OpenAlexProvider()._metadata(
        {
            "title": "Trade and Credit",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/example",
            "authorships": [
                {
                    "author": {"display_name": "Ada Lee"},
                    "raw_author_name": "Ada Lee",
                }
            ],
        }
    )

    class OpenAlexStub:
        def lookup_doi(self, doi):
            return metadata

        def search_title(self, title):
            return None

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=OpenAlexStub()
    )

    assert mapping["items"][0]["destination"] == "Lee_2024_Trade_and_Credit.pdf"
    assert mapping["items"][0]["confidence"] == "review"
    assert mapping["items"][0]["provenance"] == "doi-lookup"


def test_structured_openalex_doi_author_can_be_high_confidence(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "study.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        rename_module,
        "read_pdf_candidate",
        lambda path: {"doi": "10.1234/example"},
    )
    metadata = rename_module.OpenAlexProvider()._metadata(
        {
            "title": "Trade and Credit",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/example",
            "authorships": [
                {
                    "author": {
                        "display_name": "Ada van Lee",
                        "family_name": "van Lee",
                    },
                    "raw_author_name": "Ada van Lee",
                }
            ],
        }
    )

    class OpenAlexStub:
        def lookup_doi(self, doi):
            return metadata

        def search_title(self, title):
            return None

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=OpenAlexStub()
    )

    assert mapping["items"][0]["confidence"] == "high"


def test_propose_cli_offline_dispatches_without_openalex(
    rename_module, tmp_path, monkeypatch
):
    output = tmp_path / "proposal.json"
    calls = []

    def fake_propose(directory, destination, *, provider, fmt=None):
        calls.append((directory, destination, provider))
        return {}

    monkeypatch.setattr(rename_module, "propose", fake_propose)
    monkeypatch.setattr(
        rename_module,
        "OpenAlexProvider",
        lambda: pytest.fail("offline mode must not construct a network provider"),
    )

    result = rename_module.main(
        [
            "propose",
            "--directory",
            str(tmp_path),
            "--output",
            str(output),
            "--offline",
        ]
    )

    assert result == 0
    assert calls == [(tmp_path, output, None)]
