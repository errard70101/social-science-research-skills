from __future__ import annotations


def test_title_guess_uses_largest_first_block(summary_module):
    first_page = (
        "The Colonial Origins of Comparative Development\n"
        "\n"
        "Daron Acemoglu, Simon Johnson, and James A. Robinson\n"
        "\n"
        "American Economic Review, December 2001\n"
        "\n"
        "Abstract: ..."
    )

    title = summary_module.guess_title(first_page)

    assert title == "The Colonial Origins of Comparative Development"


def test_author_guess_handles_oxford_comma_and_and(summary_module):
    first_page = (
        "Some Paper Title\n"
        "\n"
        "Daron Acemoglu, Simon Johnson, and James A. Robinson\n"
    )

    authors = summary_module.guess_authors(first_page)

    assert authors == [
        "Daron Acemoglu",
        "Simon Johnson",
        "James A. Robinson",
    ]


def test_author_guess_handles_ampersand(summary_module):
    first_page = "Title\n\nJane Smith & John Doe"

    assert summary_module.guess_authors(first_page) == [
        "Jane Smith",
        "John Doe",
    ]


def test_author_guess_falls_back_to_empty(summary_module):
    assert summary_module.guess_authors("Just a title and nothing else") == []


def test_author_guess_handles_lowercase_particles(summary_module):
    first_page = (
        "Title\n"
        "\n"
        "Roy van der Weide, Jonathan de Quidt, and J. B. De Long\n"
    )
    assert summary_module.guess_authors(first_page) == [
        "Roy van der Weide",
        "Jonathan de Quidt",
        "J. B. De Long",
    ]


def test_author_guess_strips_trailing_superscript_markers(summary_module):
    first_page = (
        "Title\n"
        "\n"
        "Daron Acemoglu1, Simon Johnson* and James A. Robinson\u2020\n"
    )
    assert summary_module.guess_authors(first_page) == [
        "Daron Acemoglu",
        "Simon Johnson",
        "James A. Robinson",
    ]
