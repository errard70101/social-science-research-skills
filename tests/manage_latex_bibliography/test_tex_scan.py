from __future__ import annotations

import pytest


def test_discover_tex_files_follows_recursive_local_inputs(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    sections = project / "sections"
    sections.mkdir(parents=True)
    main = project / "main.tex"
    appendix = project / "appendix.tex"
    intro = sections / "intro.tex"
    main.write_text(
        "\\documentclass{article}\n\\input{sections/intro}\n\\include{appendix.tex}\n"
    )
    intro.write_text("\\input{../appendix}\n")
    appendix.write_text("Appendix\n")

    discovered = bibliography_module.discover_tex_files(main, project)

    assert discovered == [
        main.resolve(),
        appendix.resolve(),
        intro.resolve(),
    ]


def test_discover_tex_files_ignores_commented_inputs_and_avoids_cycles(
    bibliography_module, tmp_path
):
    main = tmp_path / "main.tex"
    chapter = tmp_path / "chapter.tex"
    ignored = tmp_path / "ignored.tex"
    main.write_text("% \\input{ignored}\n\\input{chapter} % \\input{ignored}\n")
    chapter.write_text("\\include{main}\n")

    assert bibliography_module.discover_tex_files(main, tmp_path) == [
        main.resolve(),
        chapter.resolve(),
    ]
    assert not ignored.exists()


@pytest.mark.parametrize(
    "included",
    [
        "../outside",
        "subdir/../../outside.tex",
    ],
)
def test_discover_tex_files_rejects_sources_outside_project(
    bibliography_module, tmp_path, included
):
    project = tmp_path / "paper"
    project.mkdir()
    main = project / "main.tex"
    main.write_text(f"\\input{{{included}}}\n")

    with pytest.raises(ValueError, match="outside project root"):
        bibliography_module.discover_tex_files(main, project)


def test_discover_tex_files_rejects_missing_source(bibliography_module, tmp_path):
    main = tmp_path / "main.tex"
    main.write_text("\\input{missing}\n")

    with pytest.raises(FileNotFoundError, match="missing.tex"):
        bibliography_module.discover_tex_files(main, tmp_path)


def test_discover_tex_files_adds_tex_suffix_to_dotted_names(
    bibliography_module, tmp_path
):
    main = tmp_path / "main.tex"
    chapter = tmp_path / "chapter.v1.tex"
    main.write_text("\\input{chapter.v1}\n")
    chapter.write_text("Chapter\n")

    assert bibliography_module.discover_tex_files(main, tmp_path) == [
        main.resolve(),
        chapter.resolve(),
    ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Text % comment", "Text "),
        (r"Rate is 10\% % comment", r"Rate is 10\% "),
        (r"Path \\% comment", "Path \\\\"),
        ("No comment", "No comment"),
    ],
)
def test_strip_tex_comment_stops_at_first_unescaped_percent(
    bibliography_module, line, expected
):
    assert bibliography_module.strip_tex_comment(line) == expected


def test_scan_citations_ignores_comments_and_reports_source_locations(
    bibliography_module, tmp_path
):
    source = tmp_path / "sections" / "intro.tex"
    source.parent.mkdir()
    source.write_text(
        "% \\citep{ignored}\n"
        "Prior work \\citep{alpha, beta} establishes this. % \\citet{ignored}\n"
        "Later, \\citet{gamma} extends it.\n"
    )

    assert bibliography_module.scan_citations(source, tmp_path) == [
        {"key": "alpha", "source": "sections/intro.tex", "line": 2},
        {"key": "beta", "source": "sections/intro.tex", "line": 2},
        {"key": "gamma", "source": "sections/intro.tex", "line": 3},
    ]


def test_scan_citations_supports_stars_optional_arguments_and_command_order(
    bibliography_module, tmp_path
):
    source = tmp_path / "main.tex"
    source.write_text(
        "\\textcite*[see][p.~4]{first, ,second} and "
        "\\autocite[chap.~2]{third} then \\citeyear{fourth}\n"
    )

    assert bibliography_module.scan_citations(source, tmp_path) == [
        {"key": "first", "source": "main.tex", "line": 1},
        {"key": "second", "source": "main.tex", "line": 1},
        {"key": "third", "source": "main.tex", "line": 1},
        {"key": "fourth", "source": "main.tex", "line": 1},
    ]


@pytest.mark.parametrize(
    "command",
    [
        "cite",
        "citep",
        "citet",
        "citealp",
        "citealt",
        "citeauthor",
        "citeyear",
        "parencite",
        "textcite",
        "autocite",
    ],
)
def test_scan_citations_recognizes_supported_commands(
    bibliography_module, tmp_path, command
):
    source = tmp_path / "main.tex"
    source.write_text(f"\\{command}{{reference}}\n")

    assert bibliography_module.scan_citations(source, tmp_path) == [
        {"key": "reference", "source": "main.tex", "line": 1}
    ]


def test_scan_citations_rejects_source_outside_project(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    source = tmp_path / "outside.tex"
    source.write_text("\\cite{reference}\n")

    with pytest.raises(ValueError, match="outside project root"):
        bibliography_module.scan_citations(source, project)
