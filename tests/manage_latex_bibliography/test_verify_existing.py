from __future__ import annotations

BIB_TEXT = """@article{smith2020,
  author = {Smith, John},
  title = {A Study of Things},
  journal = {Journal of Things},
  year = {2020},
  doi = {10.1234/abc}
}

@article{jones2019,
  author = {Jones, Jane},
  title = {On Stuff},
  journal = {Stuff Quarterly},
  year = {2018},
  doi = {10.5678/def}
}

@article{nodoi,
  author = {Doe, John},
  title = {No DOI Here},
  journal = {Obscure Press},
  year = {2015}
}
"""


def _bib(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text(BIB_TEXT, encoding="utf-8")
    return path


def test_verify_existing_flags_year_mismatch(bibliography_module, tmp_path):
    bib = _bib(tmp_path)

    responses = {
        "10.1234/abc": {
            "DOI": "10.1234/abc",
            "title": ["A Study of Things"],
            "issued": {"date-parts": [[2020]]},
        },
        "10.5678/def": {
            "DOI": "10.5678/def",
            "title": ["On Stuff"],
            "issued": {"date-parts": [[2019]]},
        },
    }

    def fetcher(doi: str):
        return responses[doi]

    report = bibliography_module.verify_existing_entries(bib, fetcher=fetcher)

    by_key = {entry["citation_key"]: entry for entry in report["entries"]}
    assert by_key["smith2020"]["status"] == "verified"
    assert by_key["jones2019"]["status"] == "inconsistent"
    assert any(d["field"] == "year" for d in by_key["jones2019"]["discrepancies"])
    assert by_key["nodoi"]["status"] == "skipped"
    assert report["summary"]["inconsistent"] == 1
    assert report["summary"]["verified"] == 1
    assert report["summary"]["skipped"] == 1


def test_verify_existing_graceful_when_fetcher_fails(bibliography_module, tmp_path):
    bib = _bib(tmp_path)

    def fetcher(doi: str):
        raise RuntimeError("network down")

    report = bibliography_module.verify_existing_entries(bib, fetcher=fetcher)
    by_key = {entry["citation_key"]: entry for entry in report["entries"]}
    assert by_key["smith2020"]["status"] == "unverified"
    # Once unavailable, subsequent DOI-bearing entries are marked unverified
    # without further fetch attempts.
    assert by_key["jones2019"]["status"] == "unverified"
    # Skipped entries (no DOI) remain skipped, not unverified.
    assert by_key["nodoi"]["status"] == "skipped"


def test_verify_existing_detects_title_drift(bibliography_module, tmp_path):
    bib = _bib(tmp_path)

    responses = {
        "10.1234/abc": {
            "DOI": "10.1234/abc",
            "title": ["A Completely Different Title"],
            "issued": {"date-parts": [[2020]]},
        },
        "10.5678/def": {
            "DOI": "10.5678/def",
            "title": ["On Stuff"],
            "issued": {"date-parts": [[2018]]},
        },
    }

    def fetcher(doi: str):
        return responses[doi]

    report = bibliography_module.verify_existing_entries(bib, fetcher=fetcher)
    by_key = {entry["citation_key"]: entry for entry in report["entries"]}
    assert by_key["smith2020"]["status"] == "inconsistent"
    assert any(d["field"] == "title" for d in by_key["smith2020"]["discrepancies"])
    assert by_key["jones2019"]["status"] == "verified"
