from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest


def write_project(tmp_path, tex, bib=None):
    if "\\end{document}" not in tex:
        tex += "\n\\end{document}\n"
    project = tmp_path / "paper"
    project.mkdir()
    main = project / "main.tex"
    main.write_text(tex, encoding="utf-8")
    if bib is not None:
        (project / "references.bib").write_text(bib, encoding="utf-8")
    return project, main


def accepted_entry(key="missing", entry_type="article"):
    fields = {
        "author": "Smith, Jane",
        "title": "A Verified Article",
        "journal": "Journal of Tests",
        "year": "2026",
        "doi": "10.1000/example",
    }
    return {
        "citation_key": key,
        "entry_type": entry_type,
        "fields": fields,
        "sources": [
            {
                "url": "https://example.test/article",
                "retrieved_at": "2026-06-08T00:00:00Z",
            }
        ],
        "conflicts": [],
        "status": "verified",
        "verifier": "independent-agent",
        "requires_user_approval": False,
        "user_approval": False,
    }


def test_sha256_file_streams_file_contents(bibliography_module, tmp_path):
    source = tmp_path / "large.bin"
    source.write_bytes(b"abc" * 100_000)

    assert (
        bibliography_module.sha256_file(source)
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )


def test_select_main_tex_accepts_file_or_unique_top_level_document(
    bibliography_module, tmp_path
):
    project = tmp_path / "paper"
    project.mkdir()
    main = project / "main.tex"
    main.write_text("% \\documentclass{book}\n\\documentclass{article}\n")
    (project / "notes.tex").write_text("notes")
    nested = project / "sections"
    nested.mkdir()
    (nested / "other.tex").write_text("\\documentclass{article}\n")

    assert bibliography_module.select_main_tex(main) == (
        project.resolve(),
        main.resolve(),
    )
    assert bibliography_module.select_main_tex(project) == (
        project.resolve(),
        main.resolve(),
    )


@pytest.mark.parametrize("count", [0, 2])
def test_select_main_tex_rejects_missing_or_ambiguous_main(
    bibliography_module, tmp_path, count
):
    project = tmp_path / "paper"
    project.mkdir()
    for index in range(count):
        (project / f"main{index}.tex").write_text("\\documentclass{article}\n")

    with pytest.raises(ValueError, match="exactly one top-level"):
        bibliography_module.select_main_tex(project)


def test_build_scan_proposal_tracks_known_and_missing_citations(
    bibliography_module, tmp_path
):
    project, main = write_project(
        tmp_path,
        "\\documentclass{article}\n"
        "\\cite{known, missing}\\citep{missing}\n"
        "\\bibliographystyle{aea}\n"
        "\\bibliography{references}\n",
        "@article{known, author={A}, title={Known}, journal={J}, year={2020}}\n",
    )

    proposal = bibliography_module.build_scan_proposal(project)

    assert proposal["schema_version"] == 1
    assert proposal["project_root"] == str(project.resolve())
    assert proposal["main_tex"] == "main.tex"
    assert proposal["bibliography_system"] == "bibtex"
    assert proposal["target_bib"] == "references.bib"
    assert proposal["citations"] == [
        {"key": "known", "source": "main.tex", "line": 2},
        {"key": "missing", "source": "main.tex", "line": 2},
        {"key": "missing", "source": "main.tex", "line": 2},
    ]
    assert proposal["new_entries"] == [
        {
            "citation_key": "missing",
            "entry_type": None,
            "fields": {},
            "sources": [],
            "conflicts": [],
            "status": "candidate",
            "verifier": None,
            "requires_user_approval": False,
            "user_approval": None,
        }
    ]
    assert proposal["file_digests"] == {
        "main.tex": bibliography_module.sha256_file(main),
        "references.bib": bibliography_module.sha256_file(project / "references.bib"),
    }
    for key in (
        "existing_entry_corrections",
        "inferred_references",
        "tex_changes",
        "unresolved",
        "verification_report",
        "warnings",
    ):
        assert proposal[key] == []


def test_scan_without_bibtex_config_proposes_references_and_aea(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path, "\\documentclass{article}\nText\n\\end{document}\n"
    )

    proposal = bibliography_module.build_scan_proposal(project)

    assert proposal["target_bib"] == "references.bib"
    assert proposal["tex_changes"] == [
        {
            "file": "main.tex",
            "status": "verified",
            "action": "insert-before-end-document",
            "commands": [
                "\\bibliographystyle{aea}",
                "\\bibliography{references}",
            ],
        }
    ]


def test_scan_preserves_non_aea_style_and_warns(bibliography_module, tmp_path):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n"
        "\\bibliographystyle{plain}\n"
        "\\bibliography{references}\n",
    )

    proposal = bibliography_module.build_scan_proposal(project)

    assert proposal["tex_changes"] == []
    assert proposal["warnings"] == ["existing bibliography style preserved: plain"]


def test_scan_with_style_but_no_target_adds_only_bibliography_command(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n\\bibliographystyle{plain}\n\\end{document}\n",
    )

    proposal = bibliography_module.build_scan_proposal(project)

    assert proposal["tex_changes"] == [
        {
            "file": "main.tex",
            "status": "verified",
            "action": "insert-before-end-document",
            "commands": ["\\bibliography{references}"],
        }
    ]
    assert proposal["warnings"] == ["existing bibliography style preserved: plain"]


def test_scan_biblatex_warns_and_requires_exactly_one_target(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n"
        "\\usepackage{biblatex}\n"
        "\\addbibresource{references.bib}\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    assert proposal["warnings"] == ["biblatex detected; aea.bst is not activated"]

    (project / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{biblatex}\n"
        "\\addbibresource{one.bib}\n\\addbibresource{two.bib}\n"
    )
    with pytest.raises(ValueError, match="exactly one bibliography target"):
        bibliography_module.build_scan_proposal(project)


def test_scan_rejects_biblatex_without_target_and_ambiguous_bibtex_target(
    bibliography_module, tmp_path
):
    project, main = write_project(
        tmp_path, "\\documentclass{article}\n\\usepackage{biblatex}\n"
    )
    with pytest.raises(ValueError, match="biblatex.*target"):
        bibliography_module.build_scan_proposal(project)

    main.write_text(
        "\\documentclass{article}\n\\bibliography{one,two}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly one bibliography target"):
        bibliography_module.build_scan_proposal(project)


def test_scan_cli_writes_sorted_indented_utf8_json(bibliography_module, tmp_path):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    output = tmp_path / "proposal.json"

    assert (
        bibliography_module.main(
            ["scan", "--project", str(project), "--output", str(output)]
        )
        == 0
    )
    text = output.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert (
        text
        == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def test_validate_rejects_unverified_entry(bibliography_module, tmp_path):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n\\cite{missing}\n")
    proposal = bibliography_module.build_scan_proposal(project)

    with pytest.raises(ValueError, match="must be verified, approved, or rejected"):
        bibliography_module.validate_proposal(proposal)


def test_validate_accepts_verified_and_skips_rejected_entries(
    bibliography_module, tmp_path
):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["new_entries"] = [
        accepted_entry(),
        {
            **accepted_entry("rejected"),
            "status": "rejected",
            "sources": [],
            "verifier": None,
        },
    ]

    bibliography_module.validate_proposal(proposal)


def test_validate_rejected_entry_still_requires_exact_schema(
    bibliography_module, tmp_path
):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    rejected = accepted_entry()
    rejected["status"] = "rejected"
    rejected.pop("conflicts")
    proposal["new_entries"] = [rejected]

    with pytest.raises(ValueError, match="schema mismatch"):
        bibliography_module.validate_proposal(proposal)


def test_validate_rejects_unknown_status_outside_entry_lists(
    bibliography_module, tmp_path
):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    proposal["tex_changes"][0]["status"] = "ready"

    with pytest.raises(ValueError, match="unknown status"):
        bibliography_module.validate_proposal(proposal)


def test_validate_requires_approval_for_corrections_and_inferred_references(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n\\bibliography{references}\n",
        "@article{known, author={A}, title={T}, journal={J}, year={1}}\n",
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = accepted_entry("known")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": False,
            "before_fields": {
                "author": "A",
                "title": "T",
                "journal": "J",
                "year": "1",
            },
        }
    )
    proposal["existing_entry_corrections"] = [correction]

    with pytest.raises(ValueError, match="requires user approval"):
        bibliography_module.validate_proposal(proposal)

    correction["user_approval"] = True
    inferred = accepted_entry("inferred")
    inferred["fields"]["doi"] = "10.1000/inferred"
    inferred.update(
        {
            "status": "verified",
            "requires_user_approval": False,
            "user_approval": False,
        }
    )
    proposal["inferred_references"] = [inferred]
    with pytest.raises(ValueError, match="inferred reference.*approval"):
        bibliography_module.validate_proposal(proposal)

    inferred.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
        }
    )
    bibliography_module.validate_proposal(proposal)


@pytest.mark.parametrize(
    ("entry_type", "fields"),
    [
        ("article", {"author": "A", "title": "T", "journal": "J", "year": "1"}),
        ("book", {"title": "T", "publisher": "P", "year": "1"}),
        (
            "incollection",
            {
                "author": "A",
                "title": "T",
                "booktitle": "B",
                "publisher": "P",
                "year": "1",
            },
        ),
        (
            "inproceedings",
            {"author": "A", "title": "T", "booktitle": "B", "year": "1"},
        ),
        ("phdthesis", {"author": "A", "title": "T", "school": "S", "year": "1"}),
        (
            "techreport",
            {"author": "A", "title": "T", "institution": "I", "year": "1"},
        ),
        (
            "unpublished",
            {"author": "A", "title": "T", "year": "1", "note": "N"},
        ),
        ("misc", {"title": "T", "year": "1"}),
    ],
)
def test_validate_entry_required_fields(bibliography_module, entry_type, fields):
    entry = accepted_entry(entry_type=entry_type)
    entry["fields"] = fields
    bibliography_module.validate_entry(entry, "new entry")

    if fields:
        broken = deepcopy(entry)
        broken["fields"] = dict(fields)
        broken["fields"].pop(next(iter(fields)))
        with pytest.raises(ValueError, match="missing required"):
            bibliography_module.validate_entry(broken, "new entry")


def test_validate_rejects_stale_digest_and_outside_target(
    bibliography_module, tmp_path
):
    project, main = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    main.write_text("\\documentclass{book}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale file digest"):
        bibliography_module.validate_proposal(proposal)

    proposal = bibliography_module.build_scan_proposal(project)
    proposal["target_bib"] = "../outside.bib"
    with pytest.raises(ValueError, match="outside project root"):
        bibliography_module.validate_proposal(proposal)


def test_validate_rejects_target_created_after_scan(bibliography_module, tmp_path):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    (project / "references.bib").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="stale bibliography target"):
        bibliography_module.validate_proposal(proposal)


def test_validate_rejects_removed_tracked_digest(bibliography_module, tmp_path):
    project = tmp_path / "paper"
    project.mkdir()
    main = project / "main.tex"
    chapter = project / "chapter.tex"
    main.write_text("\\documentclass{article}\n\\input{chapter}\n", encoding="utf-8")
    chapter.write_text("Chapter\n", encoding="utf-8")
    proposal = bibliography_module.build_scan_proposal(project)
    del proposal["file_digests"]["chapter.tex"]

    with pytest.raises(ValueError, match="digest coverage"):
        bibliography_module.validate_proposal(proposal)


@pytest.mark.parametrize("duplicate_kind", ["key", "doi", "isbn"])
def test_validate_rejects_duplicates_across_existing_and_proposed(
    bibliography_module, tmp_path, duplicate_kind
):
    identifiers = {
        "key": ("existing", {"doi": "10.1000/new"}),
        "doi": ("new", {"doi": "https://doi.org/10.1000/existing"}),
        "isbn": ("new", {"isbn": "978-1 4028 9462-6"}),
    }
    proposed_key, proposed_identifiers = identifiers[duplicate_kind]
    existing_identifier = (
        "doi={10.1000/existing}" if duplicate_kind != "isbn" else "isbn={9781402894626}"
    )
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n\\bibliography{references}\n",
        (
            "@article{existing, author={A}, title={T}, journal={J}, year={1}, "
            f"{existing_identifier}}}\n"
        ),
    )
    proposal = bibliography_module.build_scan_proposal(project)
    entry = accepted_entry(proposed_key)
    entry["fields"].update(proposed_identifiers)
    proposal["new_entries"] = [entry]

    with pytest.raises(ValueError, match="duplicate"):
        bibliography_module.validate_proposal(proposal)


def test_validate_rejects_identifier_collision_from_correction(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n\\bibliography{references}\n",
        (
            "@article{one, author={A}, title={T}, journal={J}, year={1}, "
            "doi={10.1000/one}}\n"
            "@article{two, author={B}, title={U}, journal={J}, year={2}, "
            "doi={10.1000/two}}\n"
        ),
    )
    proposal = bibliography_module.build_scan_proposal(project)
    correction = accepted_entry("two")
    correction.update(
        {
            "status": "approved",
            "requires_user_approval": True,
            "user_approval": True,
            "before_fields": {
                "author": "B",
                "title": "U",
                "journal": "J",
                "year": "2",
                "doi": "10.1000/two",
            },
        }
    )
    correction["fields"]["doi"] = "10.1000/one"
    proposal["existing_entry_corrections"] = [correction]

    with pytest.raises(ValueError, match="duplicate DOI"):
        bibliography_module.validate_proposal(proposal)


def test_validate_rejects_duplicate_keys_already_in_target(
    bibliography_module, tmp_path
):
    project, _ = write_project(
        tmp_path,
        "\\documentclass{article}\n\\bibliography{references}\n",
        (
            "@article{same, author={A}, title={T}, journal={J}, year={1}}\n"
            "@book{same, author={B}, title={U}, publisher={P}, year={2}}\n"
        ),
    )
    proposal = bibliography_module.build_scan_proposal(project)

    with pytest.raises(ValueError, match="duplicate citation keys.*same"):
        bibliography_module.validate_proposal(proposal)


def test_validate_cli_loads_and_validates_json(bibliography_module, tmp_path):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(bibliography_module.build_scan_proposal(project)),
        encoding="utf-8",
    )

    assert bibliography_module.main(["validate", "--proposal", str(proposal_path)]) == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda entry: entry.update(citation_key="Doe2024"), "citation key"),
        (
            lambda entry: entry["fields"].update({"bad field": "value"}),
            "field name",
        ),
        (
            lambda entry: entry["fields"].update({"volume": 1}),
            "field values",
        ),
        (
            lambda entry: entry["fields"].update({"title": "Unbalanced {Title"}),
            "balanced braces",
        ),
        (lambda entry: entry.update(verifier=True), "nonempty verifier string"),
        (lambda entry: entry.update(verifier=" "), "nonempty verifier string"),
        (lambda entry: entry.update(sources=[]), "nonempty list of sources"),
        (lambda entry: entry.update(sources=[True]), "must be an object"),
        (
            lambda entry: entry["sources"][0].update(url="ftp://bad"),
            "valid HTTPS url",
        ),
        (
            lambda entry: entry["sources"][0].pop("retrieved_at"),
            "retrieved_at timestamp",
        ),
        (
            lambda entry: entry["sources"][0].update(retrieved_at=""),
            "retrieved_at timestamp",
        ),
        (
            lambda entry: entry["sources"][0].update(retrieved_at="invalid"),
            "retrieved_at timestamp",
        ),
        (
            lambda entry: entry["sources"][0].update(
                retrieved_at="2024-02-30T10:00:00Z"
            ),
            "retrieved_at timestamp",
        ),
        (
            lambda entry: entry["sources"][0].update(
                retrieved_at="2024-01-01T10:00:00"
            ),
            "retrieved_at timestamp",
        ),
    ],
)
def test_validate_rejects_entries_that_cannot_render_safe_bibtex(
    bibliography_module, tmp_path, mutation, message
):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    entry = accepted_entry()
    mutation(entry)
    proposal["new_entries"] = [entry]

    with pytest.raises(ValueError, match=message):
        bibliography_module.validate_proposal(proposal)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2024-01-01T10:00:00Z",
        "2024-01-01T10:00:00+00:00",
        "2024-01-01T10:00:00-05:00",
    ],
)
def test_validate_accepts_valid_timestamps(bibliography_module, tmp_path, timestamp):
    project, _ = write_project(tmp_path, "\\documentclass{article}\n")
    proposal = bibliography_module.build_scan_proposal(project)
    entry = accepted_entry()
    entry["sources"][0]["retrieved_at"] = timestamp
    proposal["new_entries"] = [entry]

    # Should not raise
    bibliography_module.validate_proposal(proposal)
