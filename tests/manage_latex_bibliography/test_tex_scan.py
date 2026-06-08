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


def test_discover_tex_files_preserves_explicit_suffixes(bibliography_module, tmp_path):
    main = tmp_path / "main.tex"
    chapter = tmp_path / "chapter.ltx"
    main.write_text("\\input{chapter.ltx}\n")
    chapter.write_text("Chapter\n")

    assert bibliography_module.discover_tex_files(main, tmp_path) == [
        main.resolve(),
        chapter.resolve(),
    ]


def test_discover_tex_files_follows_multiline_inputs(bibliography_module, tmp_path):
    sections = tmp_path / "sections"
    sections.mkdir()
    main = tmp_path / "main.tex"
    intro = sections / "intro.tex"
    main.write_text("\\input{\nsections/intro\n}\n")
    intro.write_text("Introduction\n")

    assert bibliography_module.discover_tex_files(main, tmp_path) == [
        main.resolve(),
        intro.resolve(),
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


def test_detect_bibliography_finds_bibtex_targets_and_style(
    bibliography_module, tmp_path
):
    main = tmp_path / "main.tex"
    main.write_text(
        "\\bibliography{refs, extra.bib}\n"
        "\\bibliographystyle{aea}\n"
        "% \\addbibresource{ignored.bib}\n",
        encoding="utf-8",
    )

    assert bibliography_module.detect_bibliography([main], tmp_path) == {
        "system": "bibtex",
        "targets": ["extra.bib", "refs.bib"],
        "styles": ["aea"],
    }


def test_detect_bibliography_finds_biblatex_with_optional_arguments(
    bibliography_module, tmp_path
):
    main = tmp_path / "main.tex"
    main.write_text(
        "\\usepackage[backend=biber]{biblatex}\n"
        "\\addbibresource[location=local]{library.bib}\n",
        encoding="utf-8",
    )

    assert bibliography_module.detect_bibliography([main], tmp_path) == {
        "system": "biblatex",
        "targets": ["library.bib"],
        "styles": [],
    }


def test_detect_bibliography_finds_biblatex_in_package_list(
    bibliography_module, tmp_path
):
    main = tmp_path / "main.tex"
    main.write_text(
        "\\usepackage[backend=biber]{foo, biblatex, bar}\n",
        encoding="utf-8",
    )

    assert bibliography_module.detect_bibliography([main], tmp_path) == {
        "system": "biblatex",
        "targets": [],
        "styles": [],
    }


def test_detect_bibliography_resolves_targets_from_declaring_source(
    bibliography_module, tmp_path
):
    sections = tmp_path / "sections"
    sections.mkdir()
    main = tmp_path / "main.tex"
    chapter = sections / "chapter.tex"
    main.write_text("\\bibliographystyle{plain}\n", encoding="utf-8")
    chapter.write_text("\\bibliography{chapter-refs}\n", encoding="utf-8")

    assert bibliography_module.detect_bibliography([main, chapter], tmp_path) == {
        "system": "bibtex",
        "targets": ["sections/chapter-refs.bib"],
        "styles": ["plain"],
    }


def test_detect_bibliography_prefers_any_biblatex_signal(bibliography_module, tmp_path):
    main = tmp_path / "main.tex"
    main.write_text(
        "\\bibliography{refs}\n\\bibliographystyle{aea}\n\\usepackage{biblatex}\n",
        encoding="utf-8",
    )

    assert bibliography_module.detect_bibliography([main], tmp_path) == {
        "system": "biblatex",
        "targets": ["refs.bib"],
        "styles": ["aea"],
    }


def test_detect_bibliography_rejects_target_outside_project(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    main = project / "main.tex"
    main.write_text("\\bibliography{../outside}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside project root"):
        bibliography_module.detect_bibliography([main], project)


def test_scan_citations_supports_multiline_commands_and_keys(
    bibliography_module, tmp_path
):
    source = tmp_path / "main.tex"
    source.write_text("\\citep{\n  first,\n  second\n}\n")

    assert bibliography_module.scan_citations(source, tmp_path) == [
        {"key": "first", "source": "main.tex", "line": 1},
        {"key": "second", "source": "main.tex", "line": 1},
    ]
