from __future__ import annotations

import pytest


def test_parse_bibtex_entry_with_nested_braces_and_exact_indexes(
    bibliography_module,
):
    text = (
        "prefix\n"
        "@Article{smith2024effects,\n"
        "  title = {The Effects of {AI}},\n"
        '  author = "Smith, Jane",\n'
        "}\n"
        "suffix"
    )

    entries = bibliography_module.parse_bibtex_entries(text)

    assert entries == [
        {
            "type": "article",
            "key": "smith2024effects",
            "fields": {
                "title": "The Effects of {AI}",
                "author": "Smith, Jane",
            },
            "start": text.index("@Article"),
            "end": text.index("}\nsuffix"),
        }
    ]


def test_parse_bibtex_supports_multiple_and_parenthesized_entries(
    bibliography_module,
):
    text = (
        "@book(first,\n"
        '  title = "A Title, with a Comma",\n'
        "  publisher = {Press (International)}\n"
        ")\n"
        "@misc{second,\n"
        "  note = {Nested {braces, preserve} commas},\n"
        "  year = 2025,\n"
        "}"
    )

    entries = bibliography_module.parse_bibtex_entries(text)

    assert [(entry["type"], entry["key"]) for entry in entries] == [
        ("book", "first"),
        ("misc", "second"),
    ]
    assert entries[0]["fields"] == {
        "title": "A Title, with a Comma",
        "publisher": "Press (International)",
    }
    assert entries[1]["fields"] == {
        "note": "Nested {braces, preserve} commas",
        "year": "2025",
    }
    assert entries[1]["end"] == len(text) - 1


@pytest.mark.parametrize(
    "text",
    [
        "@article{broken, title = {Missing close}",
        '@article{broken, title = "Missing quote}',
        '@article{broken, title = "Missing {brace"}',
        "@article(broken, title = {Missing parenthesis}",
    ],
)
def test_parse_bibtex_rejects_unbalanced_entries(bibliography_module, text):
    with pytest.raises(ValueError, match="unbalanced BibTeX entry"):
        bibliography_module.parse_bibtex_entries(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("doi:10.1000/ABC.", "10.1000/abc"),
        ("https://doi.org/10.1000/ABC,", "10.1000/abc"),
        ("http://dx.doi.org/10.1000/ABC;", "10.1000/abc"),
        (" DOI: 10.1000/ABC ", "10.1000/abc"),
    ],
)
def test_normalize_doi_removes_prefixes_and_trailing_punctuation(
    bibliography_module, raw, expected
):
    assert bibliography_module.normalize_doi(raw) == expected


def test_find_duplicate_identifiers_normalizes_doi_and_isbn(
    bibliography_module,
):
    entries = [
        {
            "key": "two",
            "fields": {
                "doi": "https://doi.org/10.1000/ABC.",
                "isbn": "978-1-4028-9462-6",
            },
        },
        {
            "key": "one",
            "fields": {
                "doi": "doi:10.1000/abc",
                "isbn": "9781402894626",
            },
        },
        {"key": "unique", "fields": {"doi": "10.1000/unique"}},
    ]

    assert bibliography_module.find_duplicate_identifiers(entries) == [
        "duplicate DOI 10.1000/abc: one, two",
        "duplicate ISBN 9781402894626: one, two",
    ]
