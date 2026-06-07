# Manage LaTeX Bibliography Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable skill that inventories LaTeX citations, validates researched BibTeX entries, safely applies approved bibliography changes, and downloads `aea.bst` from the official AEA template only with explicit consent.

**Architecture:** Keep the distributed implementation in one importable standard-library Python CLI, following the repository's existing self-contained skill pattern. Separate deterministic parsing, validation, application, and download behavior into functions within that script; keep online research and independent verification as an agent workflow documented in `SKILL.md` and reference files. Tests load the script directly and use temporary LaTeX projects and injected downloaders, so the default suite remains offline.

**Tech Stack:** Python 3.10+, `argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `re`, `tempfile`, `urllib`, `zipfile`, `pytest`, Ruff, BibTeX/LaTeX for optional integration verification.

---

## File Map

- `skills/manage-latex-bibliography/scripts/manage_bibliography.py`: Importable CLI implementing project scanning, proposal validation, deterministic formatting, atomic application, and secure AEA download.
- `skills/manage-latex-bibliography/SKILL.md`: Agent workflow, online research sequence, approval gates, and command examples.
- `skills/manage-latex-bibliography/references/verification-rules.md`: Source priority, required metadata, verifier independence, and conflict policy.
- `skills/manage-latex-bibliography/references/title-case-rules.md`: Chicago headline capitalization and BibTeX case-protection rules.
- `skills/manage-latex-bibliography/agents/openai.yaml`: Optional Codex-facing display metadata.
- `tests/conftest.py`: Direct-loader fixture for the new helper.
- `tests/manage_latex_bibliography/test_tex_scan.py`: TeX traversal, citation parsing, and bibliography-system discovery.
- `tests/manage_latex_bibliography/test_bibtex.py`: BibTeX entry parsing, duplicate detection, citation keys, and title formatting.
- `tests/manage_latex_bibliography/test_proposal.py`: Proposal schema, status, approvals, required fields, and stale-digest validation.
- `tests/manage_latex_bibliography/test_apply.py`: Atomic `.bib` and `.tex` changes plus result reports.
- `tests/manage_latex_bibliography/test_aea_download.py`: Offline secure-ZIP and official-host download tests.
- `tests/test_skill_structure.py`: Generic validation for both canonical skills and bundled-path checks.
- `tests/test_scaffold.py`: CLI loading and help behavior for the new helper.
- `README.md`: Replace the temporary feature note with the new skill inventory and AEA download disclosure.

Do not add, stage, move, or edit the untracked repository-root `aea.bst`. The canonical skill must not contain an AEA-owned file.

### Task 1: Scaffold the Skill and CLI

**Files:**
- Create: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_scaffold.py`

- [ ] **Step 1: Add the failing module fixture and CLI tests**

Add to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def bibliography_module() -> ModuleType:
    return load_script(
        "manage_bibliography",
        REPO_ROOT
        / "skills"
        / "manage-latex-bibliography"
        / "scripts"
        / "manage_bibliography.py",
    )
```

Add to `tests/test_scaffold.py`:

```python
def test_bibliography_cli_parser_loads(bibliography_module):
    parser = bibliography_module.build_parser()

    assert parser.prog
    assert {"scan", "validate", "apply", "install-aea-style"} <= {
        action.dest
        for action in parser._subparsers._group_actions[0].choices.values()
    }


def test_bibliography_main_accepts_help(bibliography_module):
    with pytest.raises(SystemExit) as exc_info:
        bibliography_module.main(["--help"])

    assert exc_info.value.code == 0
```

- [ ] **Step 2: Run the scaffold tests to verify RED**

Run:

```bash
python -m pytest tests/test_scaffold.py -v
```

Expected: collection fails because `manage_bibliography.py` does not exist.

- [ ] **Step 3: Create the CLI scaffold**

Create `skills/manage-latex-bibliography/scripts/manage_bibliography.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan, validate, and update a LaTeX bibliography."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--project", type=Path, required=True)
    scan.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--proposal", type=Path, required=True)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--proposal", type=Path, required=True)

    install = subparsers.add_parser("install-aea-style")
    install.add_argument("--project", type=Path, required=True)
    install.add_argument("--confirm-download", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install-aea-style" and not args.confirm_download:
        raise SystemExit("--confirm-download is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Correct the subcommand assertion and run GREEN**

Replace the first assertion body in `test_bibliography_cli_parser_loads` with:

```python
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers_action.choices) == {
        "scan",
        "validate",
        "apply",
        "install-aea-style",
    }
```

Add `import argparse` to `tests/test_scaffold.py`, then run:

```bash
python -m pytest tests/test_scaffold.py -v
python -m ruff check tests/conftest.py tests/test_scaffold.py \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py
```

Expected: all scaffold tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the scaffold**

```bash
git add tests/conftest.py tests/test_scaffold.py \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py
git commit -m "chore: scaffold bibliography skill"
```

### Task 2: Discover TeX Sources and Citation Commands

**Files:**
- Create: `tests/manage_latex_bibliography/test_tex_scan.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing traversal and citation tests**

Create `tests/manage_latex_bibliography/test_tex_scan.py`:

```python
from __future__ import annotations


def test_discover_tex_files_follows_local_inputs_only(
    bibliography_module, tmp_path
):
    (tmp_path / "main.tex").write_text(
        "\\input{sections/intro}\n\\include{appendix}\n"
    )
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "intro.tex").write_text("Intro")
    (tmp_path / "appendix.tex").write_text("Appendix")

    files = bibliography_module.discover_tex_files(
        tmp_path / "main.tex", tmp_path
    )

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "main.tex",
        "appendix.tex",
        "sections/intro.tex",
    ]


def test_scan_citations_ignores_comments_and_tracks_locations(
    bibliography_module, tmp_path
):
    tex = tmp_path / "main.tex"
    tex.write_text(
        "% \\\\cite{ignored}\n"
        "Text \\\\citep{alpha,beta} and \\\\citet[23]{gamma}.\n"
    )

    citations = bibliography_module.scan_citations(tex, tmp_path)

    assert [(item["key"], item["line"]) for item in citations] == [
        ("alpha", 2),
        ("beta", 2),
        ("gamma", 2),
    ]
    assert all(item["source"] == "main.tex" for item in citations)


def test_discover_tex_files_rejects_path_outside_project(
    bibliography_module, tmp_path
):
    outside = tmp_path.parent / "outside.tex"
    outside.write_text("outside")
    main = tmp_path / "main.tex"
    main.write_text("\\input{../outside}")

    try:
        bibliography_module.discover_tex_files(main, tmp_path)
    except ValueError as error:
        assert "outside project root" in str(error)
    else:
        raise AssertionError("outside input must fail")
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
python -m pytest \
  tests/manage_latex_bibliography/test_tex_scan.py -v
```

Expected: failures because `discover_tex_files` and `scan_citations` do not exist.

- [ ] **Step 3: Implement comment-aware TeX traversal**

Add imports and functions:

```python
import re
from collections.abc import Iterable

INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
CITE_PATTERN = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|"
    r"parencite|textcite|autocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]+)\}"
)


def strip_tex_comment(line: str) -> str:
    escaped = False
    for index, character in enumerate(line):
        if character == "%" and not escaped:
            return line[:index]
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    return line


def contained_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"path is outside project root: {path}") from error
    return resolved


def tex_reference_path(source: Path, value: str, root: Path) -> Path:
    candidate = source.parent / value
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".tex")
    return contained_path(candidate, root)


def discover_tex_files(main: Path, root: Path) -> list[Path]:
    root = root.resolve()
    pending = [contained_path(main, root)]
    visited: set[Path] = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        if not source.is_file():
            raise ValueError(f"TeX source does not exist: {source}")
        visited.add(source)
        text = "\n".join(
            strip_tex_comment(line)
            for line in source.read_text(encoding="utf-8").splitlines()
        )
        pending.extend(
            tex_reference_path(source, match.group(1).strip(), root)
            for match in INPUT_PATTERN.finditer(text)
        )
    return sorted(visited)


def scan_citations(source: Path, root: Path) -> list[dict[str, object]]:
    citations = []
    for line_number, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = strip_tex_comment(raw_line)
        for match in CITE_PATTERN.finditer(line):
            citations.extend(
                {
                    "key": key.strip(),
                    "source": source.resolve().relative_to(root.resolve()).as_posix(),
                    "line": line_number,
                }
                for key in match.group(1).split(",")
                if key.strip()
            )
    return citations
```

Remove the unused `Iterable` import if Ruff flags it.

- [ ] **Step 4: Run focused and lint checks**

```bash
python -m pytest tests/manage_latex_bibliography/test_tex_scan.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_tex_scan.py
```

Expected: 3 tests pass and Ruff succeeds.

- [ ] **Step 5: Commit TeX discovery**

```bash
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_tex_scan.py
git commit -m "feat: discover LaTeX citations"
```

### Task 3: Detect Bibliography Systems and Parse BibTeX

**Files:**
- Modify: `tests/manage_latex_bibliography/test_tex_scan.py`
- Create: `tests/manage_latex_bibliography/test_bibtex.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing bibliography discovery tests**

Append to `test_tex_scan.py`:

```python
def test_detect_bibtex_configuration(bibliography_module, tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(
        "\\bibliographystyle{aea}\n\\bibliography{refs,extra}\n"
    )

    config = bibliography_module.detect_bibliography([tex], tmp_path)

    assert config == {
        "system": "bibtex",
        "targets": ["extra.bib", "refs.bib"],
        "styles": ["aea"],
    }


def test_detect_biblatex_configuration(bibliography_module, tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(
        "\\usepackage[backend=biber]{biblatex}\n"
        "\\addbibresource{library.bib}\n"
    )

    config = bibliography_module.detect_bibliography([tex], tmp_path)

    assert config["system"] == "biblatex"
    assert config["targets"] == ["library.bib"]
```

Create `tests/manage_latex_bibliography/test_bibtex.py`:

```python
from __future__ import annotations


def test_parse_bibtex_entries_handles_nested_braces(bibliography_module):
    text = (
        "@article{smith2024effects,\n"
        "  author = {Smith, Jane},\n"
        "  title = {The Effects of {AI}},\n"
        "  year = {2024},\n"
        "  doi = {10.1000/example}\n"
        "}\n"
    )

    entries = bibliography_module.parse_bibtex_entries(text)

    assert entries[0]["type"] == "article"
    assert entries[0]["key"] == "smith2024effects"
    assert entries[0]["fields"]["title"] == "The Effects of {AI}"
    assert entries[0]["start"] == 0
    assert entries[0]["end"] == len(text) - 2


def test_duplicate_identifiers_are_case_insensitive(bibliography_module):
    entries = [
        {"key": "one", "fields": {"doi": "10.1000/ABC"}},
        {"key": "two", "fields": {"doi": "https://doi.org/10.1000/abc"}},
    ]

    errors = bibliography_module.find_duplicate_identifiers(entries)

    assert errors == ["duplicate DOI 10.1000/abc: one, two"]
```

- [ ] **Step 2: Run tests to verify RED**

```bash
python -m pytest tests/manage_latex_bibliography/test_tex_scan.py \
  tests/manage_latex_bibliography/test_bibtex.py -v
```

Expected: new tests fail because discovery and BibTeX functions are missing.

- [ ] **Step 3: Implement bibliography configuration discovery**

Add:

```python
BIBLIOGRAPHY_PATTERN = re.compile(r"\\bibliography\s*\{([^{}]+)\}")
BIBSTYLE_PATTERN = re.compile(r"\\bibliographystyle\s*\{([^{}]+)\}")
ADDBIB_PATTERN = re.compile(r"\\addbibresource(?:\[[^\]]*\])?\s*\{([^{}]+)\}")


def bibliography_path(source: Path, value: str, root: Path) -> str:
    candidate = source.parent / value.strip()
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".bib")
    return contained_path(candidate, root).relative_to(root.resolve()).as_posix()


def detect_bibliography(sources: list[Path], root: Path) -> dict[str, object]:
    targets: set[str] = set()
    styles: set[str] = set()
    biblatex = False
    for source in sources:
        text = "\n".join(
            strip_tex_comment(line)
            for line in source.read_text(encoding="utf-8").splitlines()
        )
        biblatex = biblatex or bool(
            re.search(r"\\usepackage(?:\[[^\]]*\])?\{biblatex\}", text)
        )
        for match in ADDBIB_PATTERN.finditer(text):
            biblatex = True
            targets.add(bibliography_path(source, match.group(1), root))
        for match in BIBLIOGRAPHY_PATTERN.finditer(text):
            targets.update(
                bibliography_path(source, value, root)
                for value in match.group(1).split(",")
            )
        styles.update(
            match.group(1).strip()
            for match in BIBSTYLE_PATTERN.finditer(text)
        )
    return {
        "system": "biblatex" if biblatex else "bibtex",
        "targets": sorted(targets),
        "styles": sorted(styles),
    }
```

- [ ] **Step 4: Implement the balanced BibTeX scanner**

Add:

```python
def matching_delimiter(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if character == opening and not escaped:
            depth += 1
        elif character == closing and not escaped:
            depth -= 1
            if depth == 0:
                return index
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    raise ValueError("unbalanced BibTeX entry")


def split_top_level(value: str, separator: str = ",") -> list[str]:
    parts = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(value):
        if character == '"' and not escaped and depth == 0:
            quoted = not quoted
        elif character == "{" and not quoted and not escaped:
            depth += 1
        elif character == "}" and not quoted and not escaped:
            depth -= 1
        elif character == separator and depth == 0 and not quoted:
            parts.append(value[start:index])
            start = index + 1
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    parts.append(value[start:])
    return parts


def unwrap_bibtex_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and (
        (value[0] == "{" and value[-1] == "}")
        or (value[0] == '"' and value[-1] == '"')
    ):
        return value[1:-1]
    return value


def parse_bibtex_entries(text: str) -> list[dict[str, object]]:
    entries = []
    position = 0
    pattern = re.compile(r"@([A-Za-z]+)\s*([({])")
    while match := pattern.search(text, position):
        entry_type = match.group(1).lower()
        opening = match.group(2)
        closing = "}" if opening == "{" else ")"
        end = matching_delimiter(text, match.end() - 1, opening, closing)
        body = text[match.end():end]
        parts = split_top_level(body)
        key = parts[0].strip()
        fields = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            fields[name.strip().lower()] = unwrap_bibtex_value(value)
        entries.append(
            {
                "type": entry_type,
                "key": key,
                "fields": fields,
                "start": match.start(),
                "end": end,
            }
        )
        position = end + 1
    return entries


def normalize_doi(value: str) -> str:
    return re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    ).rstrip(".,;:)]}").lower()


def find_duplicate_identifiers(
    entries: list[dict[str, object]],
) -> list[str]:
    seen: dict[tuple[str, str], list[str]] = {}
    for entry in entries:
        fields = entry["fields"]
        for name in ("doi", "isbn"):
            raw = fields.get(name)
            if not raw:
                continue
            value = normalize_doi(raw) if name == "doi" else raw.replace("-", "").lower()
            seen.setdefault((name, value), []).append(entry["key"])
    return [
        f"duplicate {name.upper()} {value}: {', '.join(keys)}"
        for (name, value), keys in sorted(seen.items())
        if len(keys) > 1
    ]
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/manage_latex_bibliography/test_tex_scan.py \
  tests/manage_latex_bibliography/test_bibtex.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography
git commit -m "feat: parse LaTeX bibliography configuration"
```

Expected: all focused tests pass before committing.

### Task 4: Generate and Validate Versioned Proposals

**Files:**
- Create: `tests/manage_latex_bibliography/test_proposal.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing scan and schema tests**

Create `tests/manage_latex_bibliography/test_proposal.py`:

```python
from __future__ import annotations

import json

import pytest


def test_build_scan_proposal_reports_missing_keys(
    bibliography_module, tmp_path
):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "Text \\cite{known,missing}.\n\\bibliography{refs}\n"
    )
    (tmp_path / "refs.bib").write_text(
        "@article{known, title={Known}, author={Doe, Jane}, year={2020}}\n"
    )

    proposal = bibliography_module.build_scan_proposal(tmp_path)

    assert proposal["bibliography_system"] == "bibtex"
    assert proposal["target_bib"] == "refs.bib"
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


def test_validate_proposal_rejects_unverified_new_entry(
    bibliography_module, tmp_path
):
    proposal = {
        "schema_version": 1,
        "project_root": str(tmp_path),
        "bibliography_system": "bibtex",
        "target_bib": "refs.bib",
        "file_digests": {},
        "citations": [],
        "new_entries": [
            {
                "citation_key": "doe2020paper",
                "entry_type": "article",
                "fields": {"author": "Doe, Jane", "title": "Paper", "year": "2020"},
                "sources": [],
                "conflicts": [],
                "status": "candidate",
                "verifier": None,
                "requires_user_approval": False,
                "user_approval": None,
            }
        ],
        "existing_entry_corrections": [],
        "inferred_references": [],
        "tex_changes": [],
        "unresolved": [],
        "verification_report": [],
    }

    with pytest.raises(ValueError, match="must be verified"):
        bibliography_module.validate_proposal(proposal)


def test_scan_cli_writes_json(bibliography_module, tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\bibliography{refs}\n"
    )
    output = tmp_path / "proposal.json"

    assert bibliography_module.main(
        ["scan", "--project", str(tmp_path), "--output", str(output)]
    ) == 0

    assert json.loads(output.read_text())["schema_version"] == 1
```

- [ ] **Step 2: Run proposal tests to verify RED**

```bash
python -m pytest tests/manage_latex_bibliography/test_proposal.py -v
```

Expected: failures because proposal functions are missing and `main` is not wired.

- [ ] **Step 3: Implement project selection, digests, and scan output**

Add imports and functions:

```python
import hashlib
import json

SCHEMA_VERSION = 1
VALID_STATUSES = {
    "candidate",
    "verified",
    "needs-user-confirmation",
    "approved",
    "rejected",
    "unresolved",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_main_tex(project: Path) -> Path:
    project = project.resolve()
    if project.is_file():
        return project
    candidates = sorted(
        path for path in project.glob("*.tex")
        if "\\documentclass" in path.read_text(encoding="utf-8")
    )
    if len(candidates) != 1:
        raise ValueError("project must contain exactly one main TeX document")
    return candidates[0]


def empty_entry(citation_key: str) -> dict[str, object]:
    return {
        "citation_key": citation_key,
        "entry_type": None,
        "fields": {},
        "sources": [],
        "conflicts": [],
        "status": "candidate",
        "verifier": None,
        "requires_user_approval": False,
        "user_approval": None,
    }


def build_scan_proposal(project: Path) -> dict[str, object]:
    main = select_main_tex(project)
    root = main.parent if project.is_file() else project.resolve()
    sources = discover_tex_files(main, root)
    config = detect_bibliography(sources, root)
    targets = config["targets"]
    target_bib = targets[0] if len(targets) == 1 else (
        "references.bib" if not targets and config["system"] == "bibtex" else None
    )
    if target_bib is None:
        raise ValueError("unable to select exactly one bibliography target")
    bib_path = root / target_bib
    entries = (
        parse_bibtex_entries(bib_path.read_text(encoding="utf-8"))
        if bib_path.exists()
        else []
    )
    known_keys = {entry["key"] for entry in entries}
    citations = [
        citation
        for source in sources
        for citation in scan_citations(source, root)
    ]
    missing = sorted({item["key"] for item in citations} - known_keys)
    tracked = sources + ([bib_path] if bib_path.exists() else [])
    tex_changes = []
    if config["system"] == "bibtex" and not config["targets"]:
        tex_changes.append(
            {
                "source": main.relative_to(root).as_posix(),
                "kind": "add-bibliography",
                "style": "aea",
                "target": "references",
                "status": "verified",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "main_tex": main.relative_to(root).as_posix(),
        "bibliography_system": config["system"],
        "target_bib": target_bib,
        "file_digests": {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in tracked
        },
        "citations": citations,
        "new_entries": [empty_entry(key) for key in missing],
        "existing_entry_corrections": [],
        "inferred_references": [],
        "tex_changes": tex_changes,
        "unresolved": [],
        "verification_report": [],
        "warnings": (
            ["biblatex/biber detected; aea.bst will not be activated"]
            if config["system"] == "biblatex"
            else (
                [f"existing bibliography style preserved: {', '.join(config['styles'])}"]
                if config["styles"] and "aea" not in config["styles"]
                else []
            )
        ),
    }
```

- [ ] **Step 4: Implement validation and wire `scan`/`validate`**

Add:

```python
REQUIRED_FIELDS = {
    "article": {"author", "title", "year", "journal"},
    "book": {"title", "year", "publisher"},
    "incollection": {"author", "title", "year", "booktitle", "publisher"},
    "inproceedings": {"author", "title", "year", "booktitle"},
    "phdthesis": {"author", "title", "year", "school"},
    "techreport": {"author", "title", "year", "institution"},
    "unpublished": {"author", "title", "year", "note"},
    "misc": {"title", "year"},
}


def validate_entry(item: dict[str, object], *, correction: bool = False) -> None:
    status = item.get("status")
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown proposal status: {status}")
    if status not in {"verified", "approved", "rejected"}:
        raise ValueError(f"{item.get('citation_key')} must be verified")
    if status == "rejected":
        return
    if not item.get("verifier"):
        raise ValueError(f"{item.get('citation_key')} is missing verifier")
    if not item.get("sources"):
        raise ValueError(f"{item.get('citation_key')} is missing sources")
    entry_type = item.get("entry_type")
    if entry_type not in REQUIRED_FIELDS:
        raise ValueError(f"unsupported BibTeX entry type: {entry_type}")
    missing = REQUIRED_FIELDS[entry_type] - set(item.get("fields", {}))
    if missing:
        raise ValueError(
            f"{item.get('citation_key')} missing fields: {', '.join(sorted(missing))}"
        )
    if correction or item.get("requires_user_approval"):
        if item.get("user_approval") is not True:
            raise ValueError(f"{item.get('citation_key')} requires user approval")


def validate_current_digests(proposal: dict[str, object]) -> None:
    root = Path(proposal["project_root"]).resolve()
    for relative, expected in proposal.get("file_digests", {}).items():
        path = contained_path(root / relative, root)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"input changed since scan: {relative}")


def validate_proposal(proposal: dict[str, object]) -> None:
    if proposal.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported proposal schema")
    if proposal.get("bibliography_system") not in {"bibtex", "biblatex"}:
        raise ValueError("unsupported bibliography system")
    for item in proposal.get("new_entries", []):
        validate_entry(item)
    for item in proposal.get("existing_entry_corrections", []):
        validate_entry(item, correction=True)
    for item in proposal.get("inferred_references", []):
        validate_entry(item)
    validate_current_digests(proposal)
    root = Path(proposal["project_root"]).resolve()
    target = contained_path(root / proposal["target_bib"], root)
    existing = (
        parse_bibtex_entries(target.read_text(encoding="utf-8"))
        if target.exists()
        else []
    )
    proposed = [
        {"key": item["citation_key"], "fields": item["fields"]}
        for group in (
            proposal.get("new_entries", []),
            proposal.get("inferred_references", []),
        )
        for item in group
        if item["status"] != "rejected"
    ]
    keys = [entry["key"] for entry in existing + proposed]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate citation key in bibliography proposal")
    duplicate_identifiers = find_duplicate_identifiers(existing + proposed)
    if duplicate_identifiers:
        raise ValueError("; ".join(duplicate_identifiers))


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
```

Replace `main` with:

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        proposal = build_scan_proposal(args.project)
        args.output.write_text(
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif args.command == "validate":
        validate_proposal(load_json(args.proposal))
    elif args.command == "apply":
        apply_proposal(load_json(args.proposal))
    elif not args.confirm_download:
        raise SystemExit("--confirm-download is required")
    return 0
```

- [ ] **Step 5: Run proposal tests and commit**

```bash
python -m pytest tests/manage_latex_bibliography/test_proposal.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_proposal.py
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_proposal.py
git commit -m "feat: generate bibliography proposals"
```

Expected: all proposal tests pass.

### Task 5: Implement Citation Keys and Headline Capitalization

**Files:**
- Modify: `tests/manage_latex_bibliography/test_bibtex.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing naming and capitalization tests**

Append:

```python
def test_generate_citation_key_skips_stop_words_and_resolves_collision(
    bibliography_module,
):
    fields = {
        "author": "Acemoglu, Daron and Johnson, Simon",
        "year": "2001",
        "title": "The Colonial Origins of Comparative Development",
    }

    assert bibliography_module.generate_citation_key(fields, set()) == (
        "acemoglu2001colonial"
    )
    assert bibliography_module.generate_citation_key(
        fields, {"acemoglu2001colonial"}
    ) == "acemoglu2001colonialorigins"


def test_headline_title_preserves_protected_content(bibliography_module):
    title = "the effects of {AI} on {U.S.} labor markets: evidence from $R^2$"

    assert bibliography_module.headline_title(title) == (
        "The Effects of {AI} on {U.S.} Labor Markets: Evidence from $R^2$"
    )
```

- [ ] **Step 2: Run the tests to verify RED**

```bash
python -m pytest tests/manage_latex_bibliography/test_bibtex.py -v
```

Expected: two failures for missing functions.

- [ ] **Step 3: Implement deterministic key generation and title casing**

Add:

```python
STOP_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in",
    "nor", "of", "on", "or", "the", "to", "with",
}


def protected_segments(value: str) -> list[tuple[str, bool]]:
    segments = []
    plain = []
    index = 0
    while index < len(value):
        if value[index] in "{$":
            if plain:
                segments.append(("".join(plain), False))
                plain = []
            if value[index] == "$":
                end = value.find("$", index + 1)
                if end == -1:
                    raise ValueError("unbalanced math in title")
            else:
                end = matching_delimiter(value, index, "{", "}")
            segments.append((value[index:end + 1], True))
            index = end + 1
        else:
            plain.append(value[index])
            index += 1
    if plain:
        segments.append(("".join(plain), False))
    return segments


def headline_title(value: str) -> str:
    tokens: list[tuple[str, str]] = []
    for segment, protected in protected_segments(value):
        if protected:
            tokens.append((segment, "protected"))
            continue
        for token in re.findall(r"\s+|[A-Za-z]+(?:['-][A-Za-z]+)*|.", segment):
            kind = "word" if re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", token) else "other"
            tokens.append((token, kind))

    word_indexes = [
        index
        for index, (_, kind) in enumerate(tokens)
        if kind in {"word", "protected"}
    ]
    last_word = word_indexes[-1] if word_indexes else -1
    capitalize_next = True
    result = []
    for index, (token, kind) in enumerate(tokens):
        if kind == "protected":
            result.append(token)
            capitalize_next = False
        elif kind == "word":
            lower = token.lower()
            capitalize = (
                capitalize_next or index == last_word or lower not in STOP_WORDS
            )
            result.append(
                token[:1].upper() + token[1:].lower() if capitalize else lower
            )
            capitalize_next = False
        else:
            result.append(token)
            if ":" in token:
                capitalize_next = True
    return "".join(result)


def first_author_family(author_field: str) -> str:
    first = author_field.split(" and ", 1)[0].strip()
    family = first.split(",", 1)[0] if "," in first else first.split()[-1]
    return re.sub(r"[^a-z0-9]", "", family.lower())


def title_words(title: str) -> list[str]:
    unprotected = re.sub(r"[{}$\\]", "", title)
    return [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", unprotected)
        if word.lower() not in STOP_WORDS
    ]


def generate_citation_key(fields: dict[str, str], existing: set[str]) -> str:
    author = first_author_family(fields["author"])
    year = re.sub(r"\D", "", fields["year"])
    words = title_words(fields["title"])
    if not author or not year or not words:
        raise ValueError("author, year, and title are required for citation key")
    for count in range(1, len(words) + 1):
        candidate = f"{author}{year}{''.join(words[:count])}"
        if candidate not in existing:
            return candidate
    raise ValueError("unable to generate unique semantic citation key")
```

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/manage_latex_bibliography/test_bibtex.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_bibtex.py
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_bibtex.py
git commit -m "feat: format bibliography keys and titles"
```

### Task 6: Apply Approved BibTeX Changes Atomically

**Files:**
- Create: `tests/manage_latex_bibliography/test_apply.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing apply tests**

Create `tests/manage_latex_bibliography/test_apply.py`:

```python
from __future__ import annotations

import json


def verified_entry(key="doe2024effects"):
    return {
        "citation_key": key,
        "entry_type": "article",
        "fields": {
            "author": "Doe, Jane",
            "title": "The Effects of {AI}",
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


def test_apply_appends_entry_without_rewriting_existing_text(
    bibliography_module, tmp_path
):
    bib = tmp_path / "refs.bib"
    original = "@article{existing,\n  title = {Keep Formatting}\n}\n"
    bib.write_text(original)
    proposal = {
        "schema_version": 1,
        "project_root": str(tmp_path),
        "main_tex": "main.tex",
        "bibliography_system": "bibtex",
        "target_bib": "refs.bib",
        "file_digests": {"refs.bib": bibliography_module.sha256_file(bib)},
        "citations": [],
        "new_entries": [verified_entry()],
        "existing_entry_corrections": [],
        "inferred_references": [],
        "tex_changes": [],
        "unresolved": [],
        "verification_report": [],
    }

    result = bibliography_module.apply_proposal(proposal)

    assert bib.read_text().startswith(original)
    assert "@article{doe2024effects," in bib.read_text()
    assert result["applied"] == ["doe2024effects"]


def test_apply_refuses_unapproved_existing_correction(
    bibliography_module, tmp_path
):
    item = verified_entry("existing")
    item["before_fields"] = {"title": "Wrong"}
    item["user_approval"] = False
    proposal = {
        "schema_version": 1,
        "project_root": str(tmp_path),
        "bibliography_system": "bibtex",
        "target_bib": "refs.bib",
        "file_digests": {},
        "citations": [],
        "new_entries": [],
        "existing_entry_corrections": [item],
        "inferred_references": [],
        "tex_changes": [],
        "unresolved": [],
        "verification_report": [],
    }

    try:
        bibliography_module.apply_proposal(proposal)
    except ValueError as error:
        assert "requires user approval" in str(error)
    else:
        raise AssertionError("unapproved correction must fail")
```

- [ ] **Step 2: Run tests to verify RED**

```bash
python -m pytest tests/manage_latex_bibliography/test_apply.py -v
```

Expected: failures because `apply_proposal` is missing.

- [ ] **Step 3: Implement rendering and atomic replacement**

Add imports and functions:

```python
import os
import tempfile
from datetime import datetime, timezone


def render_entry(item: dict[str, object]) -> str:
    fields = dict(item["fields"])
    fields["title"] = headline_title(fields["title"])
    lines = [f"@{item['entry_type']}{{{item['citation_key']},"]
    for name in sorted(fields):
        lines.append(f"  {name} = {{{fields[name]}}},")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def replace_entry_text(
    text: str, parsed: dict[str, object], item: dict[str, object]
) -> str:
    replacement = render_entry(item)
    return text[: parsed["start"]] + replacement + text[parsed["end"] + 1 :]


def apply_proposal(proposal: dict[str, object]) -> dict[str, object]:
    validate_proposal(proposal)
    root = Path(proposal["project_root"]).resolve()
    bib = contained_path(root / proposal["target_bib"], root)
    text = bib.read_text(encoding="utf-8") if bib.exists() else ""
    parsed = parse_bibtex_entries(text)
    by_key = {entry["key"]: entry for entry in parsed}

    corrections = proposal.get("existing_entry_corrections", [])
    for item in sorted(
        corrections,
        key=lambda value: by_key[value["citation_key"]]["start"],
        reverse=True,
    ):
        key = item["citation_key"]
        if key not in by_key:
            raise ValueError(f"correction target does not exist: {key}")
        text = replace_entry_text(text, by_key[key], item)

    additions = [
        item
        for item in proposal.get("new_entries", [])
        + proposal.get("inferred_references", [])
        if item["status"] != "rejected"
    ]
    if additions:
        separator = "\n" if not text or text.endswith("\n") else "\n\n"
        text += separator + "\n\n".join(render_entry(item) for item in additions) + "\n"
    atomic_write(bib, text)

    result = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "applied": [item["citation_key"] for item in corrections + additions],
        "applied_entries": [
            {
                "citation_key": item["citation_key"],
                "sources": item["sources"],
                "verifier": item["verifier"],
            }
            for item in corrections + additions
        ],
        "skipped": [
            item["citation_key"]
            for group in (
                proposal.get("new_entries", []),
                proposal.get("existing_entry_corrections", []),
                proposal.get("inferred_references", []),
            )
            for item in group
            if item["status"] == "rejected"
        ],
        "unresolved": proposal.get("unresolved", []),
        "verification_report": proposal.get("verification_report", []),
    }
    result_path = root / "bibliography-apply-result.json"
    atomic_write(
        result_path,
        json.dumps(result, indent=2, sort_keys=True) + "\n",
    )
    return result
```

- [ ] **Step 4: Wire `apply`, run tests, and commit**

Replace the `apply` branch in `main`:

```python
    elif args.command == "apply":
        apply_proposal(load_json(args.proposal))
```

Run:

```bash
python -m pytest tests/manage_latex_bibliography/test_apply.py \
  tests/manage_latex_bibliography/test_proposal.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_apply.py
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_apply.py
git commit -m "feat: apply verified bibliography entries"
```

### Task 7: Apply Missing BibTeX Configuration Safely

**Files:**
- Modify: `tests/manage_latex_bibliography/test_apply.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing TeX mutation tests**

Append:

```python
def test_apply_adds_missing_bibtex_commands_before_end_document(
    bibliography_module, tmp_path
):
    tex = tmp_path / "main.tex"
    tex.write_text("\\documentclass{article}\n\\begin{document}\nX\n\\end{document}\n")
    proposal = {
        "schema_version": 1,
        "project_root": str(tmp_path),
        "main_tex": "main.tex",
        "bibliography_system": "bibtex",
        "target_bib": "references.bib",
        "file_digests": {"main.tex": bibliography_module.sha256_file(tex)},
        "citations": [],
        "new_entries": [],
        "existing_entry_corrections": [],
        "inferred_references": [],
        "tex_changes": [{
            "source": "main.tex",
            "kind": "add-bibliography",
            "style": "aea",
            "target": "references",
            "status": "verified",
        }],
        "unresolved": [],
        "verification_report": [],
    }

    bibliography_module.apply_proposal(proposal)

    text = tex.read_text()
    assert "\\bibliographystyle{aea}\n\\bibliography{references}\n" in text
    assert text.index("\\bibliography{references}") < text.index("\\end{document}")


def test_scan_preserves_existing_non_aea_style(
    bibliography_module, tmp_path
):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\bibliographystyle{plain}\n"
        "\\bibliography{refs}\n"
    )

    proposal = bibliography_module.build_scan_proposal(tmp_path)

    assert proposal["tex_changes"] == []
    assert proposal["warnings"] == [
        "existing bibliography style preserved: plain"
    ]
```

- [ ] **Step 2: Run tests to verify RED**

```bash
python -m pytest tests/manage_latex_bibliography/test_apply.py -v
```

Expected: the command-insertion test fails.

- [ ] **Step 3: Implement validated TeX changes**

Add:

```python
def apply_tex_changes(proposal: dict[str, object], root: Path) -> list[str]:
    changed = []
    if proposal["bibliography_system"] != "bibtex":
        if proposal.get("tex_changes"):
            raise ValueError("cannot apply BibTeX commands to biblatex project")
        return changed
    for change in proposal.get("tex_changes", []):
        if change.get("status") != "verified":
            raise ValueError("TeX change must be verified")
        source = contained_path(root / change["source"], root)
        text = source.read_text(encoding="utf-8")
        if BIBSTYLE_PATTERN.search(text) or BIBLIOGRAPHY_PATTERN.search(text):
            raise ValueError("bibliography configuration changed since scan")
        marker = "\\end{document}"
        if marker not in text:
            raise ValueError(f"missing {marker} in {change['source']}")
        commands = (
            f"\\bibliographystyle{{{change['style']}}}\n"
            f"\\bibliography{{{change['target']}}}\n"
        )
        text = text.replace(marker, commands + marker, 1)
        atomic_write(source, text)
        changed.append(change["source"])
    return changed
```

In `apply_proposal`, call it immediately before constructing `result`:

```python
    changed_tex = apply_tex_changes(proposal, root)
```

Add `"changed_tex": changed_tex` to `result`.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/manage_latex_bibliography -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_apply.py
git commit -m "feat: configure missing BibTeX bibliography"
```

### Task 8: Download `aea.bst` Securely from the Official Host

**Files:**
- Create: `tests/manage_latex_bibliography/test_aea_download.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write failing secure archive tests**

Create `tests/manage_latex_bibliography/test_aea_download.py`:

```python
from __future__ import annotations

import io
import zipfile

import pytest


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def test_extract_aea_style_accepts_exactly_one_regular_file(
    bibliography_module, tmp_path
):
    data = archive_bytes({"folder/aea.bst": b"% official style\n"})

    result = bibliography_module.extract_aea_style(data, tmp_path)

    assert (tmp_path / "aea.bst").read_bytes() == b"% official style\n"
    assert result["sha256"] == bibliography_module.sha256_bytes(
        b"% official style\n"
    )


@pytest.mark.parametrize(
    "files",
    [
        {"../aea.bst": b"bad"},
        {"one/aea.bst": b"one", "two/aea.bst": b"two"},
        {"other.bst": b"missing"},
    ],
)
def test_extract_aea_style_rejects_unsafe_archives(
    bibliography_module, tmp_path, files
):
    with pytest.raises(ValueError):
        bibliography_module.extract_aea_style(archive_bytes(files), tmp_path)


def test_extract_aea_style_rejects_duplicate_members(
    bibliography_module, tmp_path
):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("aea.bst", b"one")
        archive.writestr("aea.bst", b"two")

    with pytest.raises(ValueError, match="duplicate archive member"):
        bibliography_module.extract_aea_style(buffer.getvalue(), tmp_path)


def test_install_requires_official_final_host(
    bibliography_module, tmp_path
):
    def downloader(url):
        return (
            "https://mirror.example/aea.zip",
            archive_bytes({"aea.bst": b"style"}),
        )

    with pytest.raises(ValueError, match="official AEA host"):
        bibliography_module.install_aea_style(tmp_path, downloader=downloader)
```

- [ ] **Step 2: Run tests to verify RED**

```bash
python -m pytest \
  tests/manage_latex_bibliography/test_aea_download.py -v
```

Expected: failures because download functions are missing.

- [ ] **Step 3: Implement bounded ZIP extraction and provenance**

Add imports, constants, and functions:

```python
import urllib.request
import zipfile
from io import BytesIO
from urllib.parse import urlparse

AEA_TEMPLATE_URL = "https://www.aeaweb.org/journals/templates/latex_templates"
MAX_ARCHIVE_BYTES = 5_000_000
MAX_ARCHIVE_ENTRIES = 100
MAX_UNCOMPRESSED_BYTES = 20_000_000


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def default_downloader(url: str) -> tuple[str, bytes]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "social-science-research-skills/0.1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
        final_url = response.geturl()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("AEA template archive exceeds size limit")
    return final_url, data


def extract_aea_style(data: bytes, project: Path) -> dict[str, str]:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("AEA template archive exceeds size limit")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("AEA template archive has too many entries")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("AEA template archive expands beyond size limit")
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        for member in members:
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe path in AEA template archive")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("links are not allowed in AEA template archive")
        styles = [
            member
            for member in members
            if not member.is_dir() and Path(member.filename).name == "aea.bst"
        ]
        if len(styles) != 1:
            raise ValueError("archive must contain exactly one aea.bst")
        member = styles[0]
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("aea.bst cannot be a symbolic link")
        contents = archive.read(member)
    destination = project.resolve() / "aea.bst"
    digest = sha256_bytes(contents)
    if destination.exists():
        if sha256_file(destination) == digest:
            return {"path": str(destination), "sha256": digest, "status": "unchanged"}
        raise ValueError("refusing to overwrite a different aea.bst")
    atomic_write(destination, contents.decode("utf-8"))
    return {"path": str(destination), "sha256": digest, "status": "installed"}


def install_aea_style(
    project: Path,
    *,
    downloader=default_downloader,
) -> dict[str, str]:
    final_url, data = downloader(AEA_TEMPLATE_URL)
    parsed = urlparse(final_url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or not (
        hostname == "aeaweb.org"
        or hostname.endswith(".aeaweb.org")
    ):
        raise ValueError("download did not end on the official AEA host")
    result = extract_aea_style(data, project)
    result.update(
        {
            "source_url": final_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    atomic_write(
        project.resolve() / "aea-style-download.json",
        json.dumps(result, indent=2, sort_keys=True) + "\n",
    )
    return result
```

- [ ] **Step 4: Wire confirmed download and test it**

Replace the final `main` branch:

```python
    else:
        if not args.confirm_download:
            raise SystemExit("--confirm-download is required")
        install_aea_style(args.project)
```

Run:

```bash
python -m pytest tests/manage_latex_bibliography/test_aea_download.py -v
python -m ruff check \
  skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_aea_download.py
```

Expected: all secure download tests pass.

- [ ] **Step 5: Commit the downloader**

```bash
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  tests/manage_latex_bibliography/test_aea_download.py
git commit -m "feat: download AEA style from official source"
```

### Task 9: Document the Agent Research and Verification Workflow

**Files:**
- Create: `skills/manage-latex-bibliography/SKILL.md`
- Create: `skills/manage-latex-bibliography/references/verification-rules.md`
- Create: `skills/manage-latex-bibliography/references/title-case-rules.md`
- Create: `skills/manage-latex-bibliography/agents/openai.yaml`
- Modify: `tests/test_skill_structure.py`

- [ ] **Step 1: Generalize the failing structure tests**

Replace the single-skill constant and tests in `tests/test_skill_structure.py`
with parameterized coverage:

```python
SKILLS = {
    "rename-and-organize-references": [
        "scripts/rename_references.py",
        "references/mapping-format.md",
    ],
    "manage-latex-bibliography": [
        "scripts/manage_bibliography.py",
        "references/verification-rules.md",
        "references/title-case-rules.md",
    ],
}


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_required_frontmatter(name):
    skill = ROOT / "skills" / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert f"\nname: {name}\n" in text
    assert re.search(r"\ndescription: .+\n", text)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_contains_no_machine_specific_paths(name):
    skill = ROOT / "skills" / name
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in skill.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    forbidden = [
        "/Users/",
        "/home/linshih",
        ".gemini/config/plugins/superpowers",
        "conda run -n",
    ]
    assert all(value not in text for value in forbidden)


@pytest.mark.parametrize(("name", "expected"), SKILLS.items())
def test_skill_references_existing_bundled_files(name, expected):
    skill = ROOT / "skills" / name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert all(value in text for value in expected)
    assert all((skill / value).is_file() for value in expected)


def test_bibliography_skill_does_not_bundle_aea_style():
    skill = ROOT / "skills" / "manage-latex-bibliography"

    assert not list(skill.rglob("aea.bst"))
```

Add `import pytest`.

- [ ] **Step 2: Run structure tests to verify RED**

```bash
python -m pytest tests/test_skill_structure.py -v
```

Expected: failures because skill documentation files do not exist.

- [ ] **Step 3: Write `SKILL.md` with explicit gates**

Create `skills/manage-latex-bibliography/SKILL.md`:

```markdown
---
name: manage-latex-bibliography
description: Use when a LaTeX project needs a new or updated BibTeX bibliography, missing citation entries, verified metadata, headline-style titles, or optional AEA bibliography-style setup.
---

# Manage LaTeX Bibliography

## Workflow

1. Confirm the project root or main `.tex` file.
2. Locate this skill directory and assign its absolute path to `SKILL_DIR`.
3. Scan without modifying the project:

   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" scan \
     --project /path/to/project \
     --output /path/to/project/bibliography-proposal.json
   ```

4. Research every missing explicit citation key. Also inspect prose for likely
   uncited works, but never add a prose-inferred citation without user approval.
5. Follow `references/verification-rules.md`. Prefer publisher pages, then
   Crossref, recognized indexes, and Google Scholar.
6. Give each candidate to an independent subagent for a fresh online check. If
   subagents are unavailable, perform a separate second lookup without relying
   on first-pass conclusions.
7. Follow `references/title-case-rules.md`. Record field sources, retrieval
   dates, conflicts, verifier identity, status, and required approvals in the
   proposal.
8. Ask the user to approve every prose-inferred reference and every correction
   to an existing entry.
9. Validate:

   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" validate \
     --proposal /path/to/project/bibliography-proposal.json
   ```

10. Apply only after validation succeeds:

    ```bash
    python "$SKILL_DIR/scripts/manage_bibliography.py" apply \
      --proposal /path/to/project/bibliography-proposal.json
    ```

11. Review `bibliography-apply-result.json` and compile the project when a TeX
    toolchain is available.

## AEA Style

This skill does not distribute `aea.bst`. For a traditional BibTeX project,
ask the user before downloading the official AEA template. After confirmation:

```bash
python "$SKILL_DIR/scripts/manage_bibliography.py" install-aea-style \
  --project /path/to/project \
  --confirm-download
```

Never use an unofficial mirror. Preserve an existing bibliography style. For
`biblatex` or `biber`, maintain entries but do not activate `aea.bst` or convert
the project.

## Safety Rules

- Never invent bibliographic metadata.
- Never treat a citation key as proof of publication identity.
- Never apply unresolved or unverified entries.
- Never apply inferred references or existing-entry corrections without user
  approval.
- Re-scan when any tracked `.tex` or `.bib` file changed.
- Do not bypass duplicate identifier, project containment, archive, or
  overwrite failures.
```

- [ ] **Step 4: Write the two focused references and agent metadata**

Create `references/verification-rules.md` with:

```markdown
# Bibliographic Verification Rules

## Source Priority

1. Official publisher or journal page.
2. Crossref DOI metadata.
3. Recognized journal or bibliographic index.
4. Google Scholar.

## Required Checks

Check publication identity, author order, year, title, venue, volume, issue,
pages or article number, publisher, edition, DOI, and URL whenever applicable.
Use BibTeX entry-type requirements enforced by the helper as the minimum, not
the completeness target.

## Independent Verification

The verifier must repeat the lookup and record its identity. It must not accept
the first researcher's candidate without checking the cited sources. When no
subagent exists, start a separate second pass and do not reuse unsupported
first-pass assumptions.

## Conflicts

Record conflicting values and their URLs. Prefer a higher-priority source only
when it clearly describes the same publication. Leave unresolved identity or
required fields unwritten. Never infer missing metadata from the current date,
a citation key, or a nearby publication.

## Approval

Verified entries for explicit citation keys may be added. Prose-inferred
references and corrections to existing entries require explicit user approval.
```

Create `references/title-case-rules.md` with:

```markdown
# Title Case and BibTeX Protection

Use Chicago-style headline capitalization. Capitalize the first and last word,
major words, and the first word after a colon. Lowercase articles, coordinating
conjunctions, and short prepositions unless they are first, last, or follow a
colon.

Protect case-sensitive content with braces:

```bibtex
title = {The Effects of {AI} on {U.S.} Labor Markets}
```

Preserve existing braces around abbreviations, proper names, technical terms,
LaTeX commands, and mathematics. Add protection only when the publication
title and reliable sources support the capitalization. The helper performs
mechanical title casing; the verifier remains responsible for semantic case
protection.
```

Create `agents/openai.yaml`:

```yaml
interface:
  display_name: "Manage LaTeX Bibliography"
  short_description: "Verify and maintain LaTeX BibTeX entries"
  default_prompt: "Use $manage-latex-bibliography to scan my LaTeX project, verify missing references, and propose safe bibliography updates."
```

- [ ] **Step 5: Run structure tests and commit**

```bash
python -m pytest tests/test_skill_structure.py -v
python -m ruff check tests/test_skill_structure.py
git add tests/test_skill_structure.py \
  skills/manage-latex-bibliography/SKILL.md \
  skills/manage-latex-bibliography/references \
  skills/manage-latex-bibliography/agents/openai.yaml
git commit -m "docs: add bibliography verification workflow"
```

### Task 10: Update README and Verify the Complete Feature

**Files:**
- Modify: `README.md`
- Optionally modify: `pyproject.toml` only if implementation imports a new runtime package; the planned implementation should not require one.

- [ ] **Step 1: Replace the temporary README note**

Remove:

```text
% Remove this after implementation.

I would like to add a new skill to create .bib file. It need to include the aea.bst file. All the entry must follow headline style. And a subagent to check whether all the entries are correct by searching the internet.
```

Add under `## Skills`:

```markdown
### `manage-latex-bibliography`

Scans LaTeX projects for missing citations, creates reviewable bibliography
proposals, and applies independently verified BibTeX entries with Chicago-style
headline capitalization.

The skill can configure a traditional BibTeX project for the AEA bibliography
style. It does not redistribute `aea.bst`; after explicit user confirmation,
the helper downloads the current LaTeX template directly from the official AEA
website and extracts the style into the user's project.
```

- [ ] **Step 2: Run the complete automated test suite**

```bash
python -m pytest -v
```

Expected: all tests pass; any optional TeX compilation test is explicitly
skipped only when the toolchain is unavailable.

- [ ] **Step 3: Run repository lint and CLI smoke tests**

```bash
python -m ruff check .
python skills/manage-latex-bibliography/scripts/manage_bibliography.py --help
python skills/manage-latex-bibliography/scripts/manage_bibliography.py scan --help
python skills/manage-latex-bibliography/scripts/manage_bibliography.py validate --help
python skills/manage-latex-bibliography/scripts/manage_bibliography.py apply --help
python skills/manage-latex-bibliography/scripts/manage_bibliography.py \
  install-aea-style --help
```

Expected: Ruff reports `All checks passed!`; every command exits zero and shows
the documented arguments.

- [ ] **Step 4: Verify packaging and copyright boundaries**

Run:

```bash
find skills/manage-latex-bibliography -type f | sort
git status --short
git diff --check
```

Expected:

- No `aea.bst`, AEA ZIP, downloaded provenance report, or temporary project
  output exists under `skills/manage-latex-bibliography`.
- `git diff --check` produces no output.
- The repository-root untracked `aea.bst` remains untouched and unstaged.

- [ ] **Step 5: Commit documentation and final verification**

```bash
git add README.md
git commit -m "docs: publish LaTeX bibliography skill"
```

- [ ] **Step 6: Review the branch before integration**

Run:

```bash
git log --oneline --decorate -12
git diff HEAD~10..HEAD --stat
python -m pytest
python -m ruff check .
```

Expected: commits are scoped by task, all tests pass, and Ruff succeeds. Then
invoke `superpowers:requesting-code-review` before merging or publishing.
