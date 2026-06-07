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


def test_parse_bibtex_skips_directives_and_percent_comment_lines(
    bibliography_module,
):
    text = (
        "@string{journal = {Journal @article{fake, title={Fake}}}}\n"
        '@preamble{"@book{alsofake, title={Fake}}"}\n'
        "@comment{Ignored @misc{thirdfake, title={Fake}}}\n"
        "% @article{commented, title={Commented}}\n"
        "prefix @article{real, title={Real}} suffix\n"
    )

    assert bibliography_module.parse_bibtex_entries(text) == [
        {
            "type": "article",
            "key": "real",
            "fields": {"title": "Real"},
            "start": text.index("@article{real"),
            "end": text.index("} suffix"),
        }
    ]


def test_parse_bibtex_preserves_indexes_after_inline_percent_comment(
    bibliography_module,
):
    text = "text % @article{ignored, title={Ignored}}\n@book{kept, title={Kept}}\n"

    entry = bibliography_module.parse_bibtex_entries(text)[0]

    assert entry["start"] == text.index("@book")
    assert entry["end"] == text.rindex("}")


def test_parse_bibtex_preserves_percent_signs_inside_field_values(
    bibliography_module,
):
    text = (
        "@article{percentages,\n"
        r"  title = {Growth of 10\%},"
        "\n"
        '  url = "https://example.test/a%20b",\n'
        "}\n"
    )

    assert bibliography_module.parse_bibtex_entries(text) == [
        {
            "type": "article",
            "key": "percentages",
            "fields": {
                "title": r"Growth of 10\%",
                "url": "https://example.test/a%20b",
            },
            "start": 0,
            "end": text.rindex("}"),
        }
    ]


def test_parse_bibtex_ignores_fake_entry_in_real_percent_comment(
    bibliography_module,
):
    text = "% real comment @article{fake, title={Fake}}\n@article{real, title={Real}}\n"

    entries = bibliography_module.parse_bibtex_entries(text)

    assert [entry["key"] for entry in entries] == ["real"]
    assert entries[0]["start"] == text.index("@article{real")


def test_parse_bibtex_masks_comments_between_fields(bibliography_module):
    text = (
        "@misc{example,\n"
        "  year = {2024}, % publication year\n"
        "  title = {A Parsed Title},\n"
        "}\n"
    )

    assert bibliography_module.parse_bibtex_entries(text) == [
        {
            "type": "misc",
            "key": "example",
            "fields": {
                "year": "2024",
                "title": "A Parsed Title",
            },
            "start": 0,
            "end": text.rindex("}"),
        }
    ]


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
        ("https://doi.org/10.1000/ABC).", "10.1000/abc"),
        ("doi:10.1000/ABC]};", "10.1000/abc"),
        ("doi:10.1000/foo(bar)", "10.1000/foo(bar)"),
        ("doi:10.1000/foo(bar)).", "10.1000/foo(bar)"),
        ("doi:10.1000/foo[bar]];", "10.1000/foo[bar]"),
        (
            "doi:10.1000/ABC(DEF):part",
            "10.1000/abc(def):part",
        ),
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
                "isbn": "978-1 4028 9462-6",
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


def test_generate_citation_key_skips_stop_words_and_resolves_collision(
    bibliography_module,
):
    fields = {
        "author": "Acemoglu, Daron and Johnson, Simon",
        "year": "2001",
        "title": "The Colonial Origins of Comparative Development",
    }

    assert (
        bibliography_module.generate_citation_key(fields, set())
        == "acemoglu2001colonial"
    )
    assert (
        bibliography_module.generate_citation_key(
            fields, {"acemoglu2001colonial"}
        )
        == "acemoglu2001colonialorigins"
    )


def test_generate_citation_key_requires_semantic_components(
    bibliography_module,
):
    with pytest.raises(
        ValueError, match="author, year, and title are required"
    ):
        bibliography_module.generate_citation_key(
            {"author": "", "year": "2024", "title": "The Study"},
            set(),
        )


def test_headline_title_preserves_protected_content(bibliography_module):
    title = (
        "the effects of {AI} on {U.S.} labor markets: "
        r"evidence from $R^2$ and \LaTeX"
    )

    assert bibliography_module.headline_title(title) == (
        "The Effects of {AI} on {U.S.} Labor Markets: "
        r"Evidence from $R^2$ and \LaTeX"
    )


def test_headline_title_capitalizes_first_last_and_post_colon_words(
    bibliography_module,
):
    assert bibliography_module.headline_title(
        "war and peace: evidence in and out"
    ) == "War and Peace: Evidence in and Out"
