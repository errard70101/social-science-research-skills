from __future__ import annotations

import json

import pytest


def verified_entry(key="doe2024effects"):
    return {
        "citation_key": key,
        "entry_type": "article",
        "fields": {
            "author": "Doe, Jane",
            "title": "the effects of {AI}",
            "year": "2024",
            "journal": "Example Journal",
            "volume": "1",
            "number": "2",
            "pages": "1--20",
            "doi": "10.1000/example",
        },
        "sources": [
            {
                "url": "https://publisher.example/article",
                "retrieved_at": "2026-06-08T00:00:00Z",
            }
        ],
        "conflicts": [],
        "status": "verified",
        "verifier": "independent-agent",
        "requires_user_approval": False,
        "user_approval": None,
    }


def make_project(tmp_path, bib_text):
    project = tmp_path / "paper"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\n\\bibliography{refs}\n",
        encoding="utf-8",
    )
    (project / "refs.bib").write_text(bib_text, encoding="utf-8")
    return project


def test_apply_appends_entry_without_rewriting_existing_text(
    bibliography_module, tmp_path
):
    original = "@article{existing,\n  title = {Keep Formatting}\n}\n"
    project = make_project(tmp_path, original)
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["new_entries"] = [verified_entry()]

    result = bibliography_module.apply_proposal(proposal)

    text = (project / "refs.bib").read_text(encoding="utf-8")
    assert text.startswith(original)
    assert "@article{doe2024effects," in text
    assert "title = {The Effects of {AI}}" in text
    assert result["applied"] == ["doe2024effects"]
    assert result["applied_entries"][0]["verifier"] == "independent-agent"
    assert (
        json.loads(
            (project / "bibliography-apply-result.json").read_text(encoding="utf-8")
        )
        == result
    )


def test_apply_replaces_only_approved_existing_entry(bibliography_module, tmp_path):
    original_entry = {
        "author": "Doe, Jane",
        "title": "Wrong title",
        "journal": "Example Journal",
        "year": "2024",
    }
    project = make_project(
        tmp_path,
        "@article{existing,\n"
        "  author = {Doe, Jane},\n"
        "  title = {Wrong title},\n"
        "  journal = {Example Journal},\n"
        "  year = {2024}\n"
        "}\n\n"
        "% unrelated trailing text\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = verified_entry("existing")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
            "before_fields": original_entry,
        }
    )
    proposal["existing_entry_corrections"] = [correction]

    bibliography_module.apply_proposal(proposal)

    text = (project / "refs.bib").read_text(encoding="utf-8")
    assert "title = {The Effects of {AI}}" in text
    assert text.endswith("\n\n% unrelated trailing text\n")


def test_apply_rejects_correction_when_before_fields_do_not_match(
    bibliography_module, tmp_path
):
    project = make_project(
        tmp_path,
        "@article{existing, author={Doe, Jane}, title={Original}, "
        "journal={Example Journal}, year={2024}}\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = verified_entry("existing")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
            "before_fields": {"title": "Different"},
        }
    )
    proposal["existing_entry_corrections"] = [correction]

    with pytest.raises(ValueError, match="before_fields do not match"):
        bibliography_module.apply_proposal(proposal)


def test_apply_cli_loads_proposal_and_writes_result(bibliography_module, tmp_path):
    project = make_project(tmp_path, "")
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["new_entries"] = [verified_entry()]
    proposal_path = project / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    assert bibliography_module.main(["apply", "--proposal", str(proposal_path)]) == 0
    assert (project / "bibliography-apply-result.json").is_file()


def test_apply_adds_missing_bibtex_commands_before_end_document(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\nText\n\\end{document}\n",
        encoding="utf-8",
    )
    proposal = bibliography_module.build_scan_proposal(project)

    result = bibliography_module.apply_proposal(proposal)

    text = tex.read_text(encoding="utf-8")
    commands = "\\bibliographystyle{aea}\n\\bibliography{references}\n"
    assert commands in text
    assert text.index("\\bibliography{references}") < text.index("\\end{document}")
    assert result["changed_tex"] == ["main.tex"]
    assert (project / "references.bib").read_text(encoding="utf-8") == ""


def test_apply_preserves_existing_style_and_adds_only_bibliography(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\bibliographystyle{plain}\n\\end{document}\n",
        encoding="utf-8",
    )
    proposal = bibliography_module.build_scan_proposal(project)

    bibliography_module.apply_proposal(proposal)

    text = tex.read_text(encoding="utf-8")
    assert text.count("\\bibliographystyle{plain}") == 1
    assert "\\bibliographystyle{aea}" not in text
    assert "\\bibliography{references}" in text


def test_apply_detects_existing_style_in_included_source(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\input{settings}\n\\end{document}\n",
        encoding="utf-8",
    )
    (project / "settings.tex").write_text(
        "\\bibliographystyle{plain}\n", encoding="utf-8"
    )
    proposal = bibliography_module.build_scan_proposal(project)

    bibliography_module.apply_proposal(proposal)

    text = tex.read_text(encoding="utf-8")
    assert "\\bibliography{references}" in text
    assert "\\bibliographystyle{aea}" not in text


def test_apply_rejects_bibtex_commands_for_biblatex_project(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{biblatex}\n"
        "\\addbibresource{refs.bib}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (project / "refs.bib").write_text("", encoding="utf-8")
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["tex_changes"] = [
        {
            "file": "main.tex",
            "status": "verified",
            "action": "insert-before-end-document",
            "commands": ["\\bibliographystyle{aea}"],
        }
    ]

    with pytest.raises(ValueError, match="biblatex"):
        bibliography_module.apply_proposal(proposal)


def test_apply_rejects_tex_change_when_end_document_is_missing(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    (project / "main.tex").write_text(
        "\\documentclass{article}\nText\n", encoding="utf-8"
    )
    proposal = bibliography_module.build_scan_proposal(project)

    with pytest.raises(ValueError, match=r"missing \\end\{document\}"):
        bibliography_module.apply_proposal(proposal)


def test_apply_is_atomic_across_files(bibliography_module, tmp_path, monkeypatch):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    original_tex = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    tex.write_text(original_tex, encoding="utf-8")
    bib = project / "references.bib"
    bib.write_text("", encoding="utf-8")
    proposal = bibliography_module.build_scan_proposal(project)

    # Patch os.replace to fail on the second call (the tex file).
    original_replace = bibliography_module.os.replace

    def mock_replace(src, dst):
        if "main.tex" in str(dst) and ".bak" not in str(dst) and ".bak" not in str(src):
            raise OSError("simulated failure")
        original_replace(src, dst)

    monkeypatch.setattr(bibliography_module.os, "replace", mock_replace)

    with pytest.raises(OSError, match="simulated failure"):
        bibliography_module.apply_proposal(proposal)

    # Check rollback
    assert bib.read_text(encoding="utf-8") == ""
    assert tex.read_text(encoding="utf-8") == original_tex


def test_apply_retains_backup_when_rollback_restore_fails(
    bibliography_module, tmp_path, monkeypatch
):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    original_tex = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    tex.write_text(original_tex, encoding="utf-8")
    (project / "references.bib").write_text("", encoding="utf-8")
    proposal = bibliography_module.build_scan_proposal(project)
    original_replace = bibliography_module.os.replace

    def fail_main_replacement_and_restore(src, dst):
        source = str(src)
        if dst == tex and source.startswith(str(project / ".main.tex.")):
            if ".bak." in source:
                raise OSError("simulated restore failure")
            raise OSError("simulated replacement failure")
        original_replace(src, dst)

    monkeypatch.setattr(
        bibliography_module.os, "replace", fail_main_replacement_and_restore
    )

    with pytest.raises(RuntimeError, match="backup retained") as error:
        bibliography_module.apply_proposal(proposal)

    backups = list(project.glob(".main.tex.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_tex
    assert str(backups[0]) in str(error.value)


def test_apply_rollback_on_report_write_failure(
    bibliography_module, tmp_path, monkeypatch
):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    original_tex = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    tex.write_text(original_tex, encoding="utf-8")
    bib = project / "references.bib"
    bib.write_text("", encoding="utf-8")
    result_file = project / "bibliography-apply-result.json"
    result_file.write_text("existing_result", encoding="utf-8")
    proposal = bibliography_module.build_scan_proposal(project)

    def mock_atomic_write(path, data):
        raise OSError("simulated report write failure")

    monkeypatch.setattr(bibliography_module, "atomic_write", mock_atomic_write)

    with pytest.raises(OSError, match="simulated report write failure"):
        bibliography_module.apply_proposal(proposal)

    assert bib.read_text(encoding="utf-8") == ""
    assert tex.read_text(encoding="utf-8") == original_tex
    assert result_file.read_text(encoding="utf-8") == "existing_result"


def test_apply_preserves_existing_backup_files(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8",
    )
    existing_backup = project / ".main.tex.bak.123"
    existing_backup.write_text("user data", encoding="utf-8")

    proposal = bibliography_module.build_scan_proposal(project)
    bibliography_module.apply_proposal(proposal)

    assert existing_backup.read_text(encoding="utf-8") == "user data"


def test_apply_preserves_existing_file_modes(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8",
    )
    bib = project / "references.bib"
    bib.write_text("", encoding="utf-8")

    tex.chmod(0o644)
    bib.chmod(0o600)

    proposal = bibliography_module.build_scan_proposal(project)
    bibliography_module.apply_proposal(proposal)

    import stat

    assert stat.S_IMODE(tex.stat().st_mode) == 0o644
    assert stat.S_IMODE(bib.stat().st_mode) == 0o600


def test_apply_sets_umask_mode_for_new_files(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    tex = project / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8",
    )
    # references.bib does not exist

    proposal = bibliography_module.build_scan_proposal(project)

    import os
    import stat

    old_umask = os.umask(0o022)
    try:
        bibliography_module.apply_proposal(proposal)
    finally:
        os.umask(old_umask)

    bib = project / "references.bib"
    assert stat.S_IMODE(bib.stat().st_mode) == (0o666 & ~0o022)
