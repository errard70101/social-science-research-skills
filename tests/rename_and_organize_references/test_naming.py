from __future__ import annotations


def test_format_authors_preserves_order_and_uses_family_names(rename_module):
    authors = [
        {"display_name": "Ana María León-Ledesma", "family_name": "León-Ledesma"},
        {"display_name": "John Q. Smith", "family_name": "Smith"},
    ]

    assert rename_module.format_authors(authors) == "Leon-Ledesma_Smith"


def test_format_authors_uses_et_al_for_four_or_more(rename_module):
    authors = [
        {"family_name": "One"},
        {"family_name": "Two"},
        {"family_name": "Three"},
        {"family_name": "Four"},
    ]

    assert rename_module.format_authors(authors) == "One_et_al"


def test_clean_title_is_ascii_and_separator_safe(rename_module):
    assert (
        rename_module.clean_title("Crédit, Trade: Evidence & Policy")
        == "Credit_Trade_Evidence_Policy"
    )


def test_normalize_doi_removes_url_and_trailing_punctuation(rename_module):
    assert (
        rename_module.normalize_doi("https://doi.org/10.1234/example.5).")
        == "10.1234/example.5"
    )


def test_build_filename_preserves_suffix_under_length_limit(rename_module):
    metadata = {
        "authors": [{"family_name": "Author"}],
        "year": 2024,
        "title": "A " + ("Very Long " * 40) + "Title",
    }

    name = rename_module.build_filename(metadata, kind="appendix", max_length=120)

    assert len(name) <= 120
    assert name.endswith("_Appendix.pdf")


def test_build_filename_rejects_missing_required_metadata(rename_module):
    metadata = {"authors": [], "year": None, "title": "Known title"}

    try:
        rename_module.build_filename(metadata, kind="main-paper")
    except ValueError as error:
        assert "authors and year" in str(error)
    else:
        raise AssertionError("missing metadata must not produce a filename")
