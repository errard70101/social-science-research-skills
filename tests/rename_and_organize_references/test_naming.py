from __future__ import annotations

import pytest


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


def test_family_name_uses_leading_name_in_comma_form(rename_module):
    assert rename_module.family_name({"display_name": "Smith, John Q."}) == "Smith"


@pytest.mark.parametrize(
    "display_name",
    [
        "John Q. Smith Jr.",
        "John Q. Smith Sr.",
        "John Q. Smith II",
        "Smith, John Q., III",
    ],
)
def test_family_name_rejects_ambiguous_suffix_forms(rename_module, display_name):
    assert rename_module.family_name({"display_name": display_name}) == ""


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


def test_build_filename_truncates_only_title(rename_module):
    metadata = {
        "authors": [
            {"family_name": "First-Long-Author"},
            {"family_name": "Second-Long-Author"},
        ],
        "year": "2024",
        "title": "Evidence " * 30,
    }

    name = rename_module.build_filename(metadata, kind="slides", max_length=60)

    assert name.startswith("First-Long-Author_Second-Long-Author_2024_")
    assert name.endswith("_Slides.pdf")
    assert len(name) <= 60


def test_build_filename_rejects_limit_without_room_for_title(rename_module):
    metadata = {
        "authors": [{"family_name": "Long-Author-Name"}],
        "year": 2024,
        "title": "Evidence",
    }

    fixed_length = len("Long-Author-Name_2024__Appendix.pdf")

    with pytest.raises(ValueError, match="title"):
        rename_module.build_filename(
            metadata,
            kind="appendix",
            max_length=fixed_length,
        )


def test_build_filename_accepts_four_digit_year_string(rename_module):
    metadata = {
        "authors": [{"family_name": "Author"}],
        "year": "2024",
        "title": "Evidence",
    }

    assert (
        rename_module.build_filename(metadata, kind="main-paper")
        == "Author_2024_Evidence.pdf"
    )


def test_build_filename_rejects_partially_unresolved_authors(rename_module):
    metadata = {
        "authors": [
            {"family_name": "One"},
            {"display_name": "Two, Taylor"},
            {"display_name": "Jordan Three Jr."},
            {"family_name": "Four"},
        ],
        "year": 2024,
        "title": "Evidence",
    }

    with pytest.raises(ValueError, match="authors"):
        rename_module.build_filename(metadata, kind="main-paper")


@pytest.mark.parametrize(
    "year",
    [
        24,
        20245,
        "24",
        "20245",
        "20/24",
        "../2024",
        True,
    ],
)
def test_build_filename_rejects_invalid_or_unsafe_years(rename_module, year):
    metadata = {
        "authors": [{"family_name": "Author"}],
        "year": year,
        "title": "Evidence",
    }

    with pytest.raises(ValueError, match="four-digit"):
        rename_module.build_filename(metadata, kind="main-paper")


def test_build_filename_rejects_missing_required_metadata(rename_module):
    metadata = {"authors": [], "year": None, "title": "Known title"}

    try:
        rename_module.build_filename(metadata, kind="main-paper")
    except ValueError as error:
        assert "authors and year" in str(error)
    else:
        raise AssertionError("missing metadata must not produce a filename")
