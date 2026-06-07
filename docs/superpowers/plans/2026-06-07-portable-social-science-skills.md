# Portable Social Science Research Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify one canonical `rename-and-organize-references` skill plus a portable installer for Antigravity, Claude Code, Codex, OpenCode, and GitHub Copilot CLI.

**Architecture:** Keep each skill self-contained under `skills/<name>/`. The first skill uses one importable Python CLI for proposal generation, mapping validation, and application; the repository-level installer validates and copies or links canonical skill directories into client discovery paths. Tests load scripts directly from their file paths so the distributed skill does not need to become a Python package.

**Tech Stack:** Python 3.10+, `argparse`, `dataclasses`, `difflib`, `json`, `pathlib`, `shutil`, `urllib`, `pypdf`, `pytest`, and `ruff`.

---

## File Map

- `pyproject.toml`: Python version, runtime/development dependencies, pytest, and Ruff configuration.
- `LICENSE`: MIT license for reuse and redistribution.
- `skills/rename-and-organize-references/scripts/rename_references.py`: Self-contained skill CLI and importable implementation.
- `skills/rename-and-organize-references/SKILL.md`: Agent-facing workflow and safety instructions.
- `skills/rename-and-organize-references/references/mapping-format.md`: Mapping schema and review guidance.
- `skills/rename-and-organize-references/agents/openai.yaml`: Optional Codex UI metadata.
- `scripts/install.py`: Standard-library multi-client installer.
- `tests/conftest.py`: Direct script-module loading helpers.
- `tests/rename_and_organize_references/test_naming.py`: Naming and DOI tests.
- `tests/rename_and_organize_references/test_propose.py`: Offline proposal tests.
- `tests/rename_and_organize_references/test_mapping.py`: Mapping validation tests.
- `tests/rename_and_organize_references/test_apply.py`: Filesystem apply and result-log tests.
- `tests/test_install.py`: Installer tests.
- `tests/test_skill_structure.py`: Agent Skills structure and portability checks.
- `README.md`: Supported clients, installation, dependencies, inventory, and contribution workflow.

## Task 1: Establish Project Tooling and Test Loading

**Files:**
- Create: `pyproject.toml`
- Create: `LICENSE`
- Create: `tests/conftest.py`
- Create: `tests/test_scaffold.py`
- Create: `skills/rename-and-organize-references/scripts/rename_references.py`
- Create: `scripts/install.py`

- [ ] **Step 1: Write the module-loading test helpers**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def rename_module() -> ModuleType:
    return load_script(
        "rename_references",
        REPO_ROOT
        / "skills"
        / "rename-and-organize-references"
        / "scripts"
        / "rename_references.py",
    )


@pytest.fixture(scope="session")
def install_module() -> ModuleType:
    return load_script("install_skills", REPO_ROOT / "scripts" / "install.py")
```

- [ ] **Step 2: Create minimal script entry points and scaffold tests**

Create `skills/rename-and-organize-references/scripts/rename_references.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Propose, validate, and apply academic reference renames."
    )
    parser.add_subparsers(dest="command", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `tests/test_scaffold.py`:

```python
from __future__ import annotations


def test_rename_cli_parser_loads(rename_module):
    assert rename_module.build_parser().prog


def test_installer_cli_parser_loads(install_module):
    assert install_module.build_parser().prog
```

Create `scripts/install.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Install portable research skills.")


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Add project configuration**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "social-science-research-skills"
version = "0.1.0"
description = "Portable Agent Skills for social science research workflows"
requires-python = ">=3.10"
dependencies = ["pypdf>=5.0"]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.11",
]

[tool.setuptools]
py-modules = []

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Create `LICENSE` using the standard MIT License text, copyright:

```text
Copyright (c) 2026 Lin Shih-Yang
```

- [ ] **Step 4: Install development dependencies and verify collection**

Run:

```bash
python -m pip install -e '.[dev]'
python -m pytest --collect-only
python -m ruff check .
```

Expected:

- Editable installation succeeds.
- Pytest reports no collection errors.
- Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit the tooling scaffold**

```bash
git add pyproject.toml LICENSE tests/conftest.py tests/test_scaffold.py \
  skills/rename-and-organize-references/scripts/rename_references.py \
  scripts/install.py
git commit -m "chore: scaffold portable skills project"
```

## Task 2: Implement Deterministic Naming and DOI Utilities

**Files:**
- Create: `tests/rename_and_organize_references/test_naming.py`
- Modify: `skills/rename-and-organize-references/scripts/rename_references.py`

- [ ] **Step 1: Write failing normalization tests**

Create `tests/rename_and_organize_references/test_naming.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/rename_and_organize_references/test_naming.py -v
```

Expected: failures because `format_authors`, `clean_title`, `normalize_doi`,
and `build_filename` do not exist.

- [ ] **Step 3: Implement the naming functions**

Add these constants and functions to `rename_references.py`:

```python
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
KIND_SUFFIXES = {
    "main-paper": "",
    "appendix": "_Appendix",
    "slides": "_Slides",
    "replication": "_Replication",
}


def ascii_token(value: str, *, allow_hyphen: bool = True) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    allowed = r"[^A-Za-z0-9-]+" if allow_hyphen else r"[^A-Za-z0-9]+"
    return re.sub(allowed, "", ascii_value)


def clean_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_title)
    return "_".join(words)


def family_name(author: Mapping[str, Any]) -> str:
    structured = str(author.get("family_name") or "").strip()
    if structured:
        return ascii_token(structured)
    display = str(author.get("display_name") or "").strip()
    tokens = [token for token in re.split(r"[\s,]+", display) if token]
    return ascii_token(tokens[-1]) if tokens else ""


def format_authors(authors: Sequence[Mapping[str, Any]]) -> str:
    names = [family_name(author) for author in authors]
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) <= 3:
        return "_".join(names)
    return f"{names[0]}_et_al"


def normalize_doi(value: str) -> str:
    candidate = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    while candidate and candidate[-1] in ".,;:)]}":
        candidate = candidate[:-1]
    return candidate


def truncate_stem(prefix: str, suffix: str, extension: str, max_length: int) -> str:
    available = max_length - len(suffix) - len(extension)
    if available < 1:
        raise ValueError("max_length is too small for the required suffix")
    return prefix[:available].rstrip("_-") + suffix + extension


def build_filename(
    metadata: Mapping[str, Any],
    *,
    kind: str,
    max_length: int = 180,
) -> str:
    authors = format_authors(metadata.get("authors", []))
    year = metadata.get("year")
    title = clean_title(str(metadata.get("title") or ""))
    if not authors or not year:
        raise ValueError("authors and year are required to generate a filename")
    if not title:
        raise ValueError("title is required to generate a filename")
    if kind not in KIND_SUFFIXES:
        raise ValueError(f"unsupported item kind: {kind}")
    extension = "" if kind == "replication" else ".pdf"
    prefix = f"{authors}_{year}_{title}"
    return truncate_stem(prefix, KIND_SUFFIXES[kind], extension, max_length)
```

- [ ] **Step 4: Run naming tests and lint**

Run:

```bash
python -m pytest tests/rename_and_organize_references/test_naming.py -v
python -m ruff check \
  skills/rename-and-organize-references/scripts/rename_references.py \
  tests/rename_and_organize_references/test_naming.py
```

Expected: all naming tests pass and Ruff reports no violations.

- [ ] **Step 5: Commit naming behavior**

```bash
git add skills/rename-and-organize-references/scripts/rename_references.py \
  tests/rename_and_organize_references/test_naming.py
git commit -m "feat: add deterministic reference naming"
```

## Task 3: Generate Offline-Safe Rename Proposals

**Files:**
- Create: `tests/rename_and_organize_references/test_propose.py`
- Modify: `skills/rename-and-organize-references/scripts/rename_references.py`

- [ ] **Step 1: Write failing proposal tests**

Create `tests/rename_and_organize_references/test_propose.py`:

```python
from __future__ import annotations

import json


class StubProvider:
    def lookup_doi(self, doi):
        assert doi == "10.1234/example"
        return {
            "title": "Trade and Credit",
            "year": 2024,
            "authors": [{"family_name": "Lee"}],
            "doi": doi,
            "source": "stub",
        }

    def search_title(self, title):
        return None


def test_propose_writes_mapping_without_renaming_sources(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "download.pdf"
    source.write_bytes(b"fake-pdf")
    output = tmp_path / "proposal.json"
    monkeypatch.setattr(
        rename_module, "read_pdf_candidate", lambda path: {"doi": "10.1234/example"}
    )

    mapping = rename_module.propose(tmp_path, output, provider=StubProvider())

    assert source.exists()
    assert not (tmp_path / "Lee_2024_Trade_and_Credit.pdf").exists()
    assert mapping["items"][0]["source"] == "download.pdf"
    assert mapping["items"][0]["destination"] == "Lee_2024_Trade_and_Credit.pdf"
    assert json.loads(output.read_text()) == mapping


def test_propose_marks_missing_metadata_unresolved(
    rename_module, tmp_path, monkeypatch
):
    source = tmp_path / "unknown.pdf"
    source.write_bytes(b"fake-pdf")
    monkeypatch.setattr(rename_module, "read_pdf_candidate", lambda path: {})

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=None
    )

    assert mapping["items"] == []
    assert mapping["unresolved"][0]["source"] == "unknown.pdf"
    assert "metadata" in mapping["unresolved"][0]["reason"]


def test_title_search_requires_similarity_threshold(rename_module):
    candidate = {"title": "A Completely Different Paper"}

    assert (
        rename_module.accept_title_match(
            "Trade Credit and Firm Dynamics", candidate, threshold=0.9
        )
        is False
    )


def test_propose_groups_appendix_and_replication_materials(
    rename_module, tmp_path, monkeypatch
):
    (tmp_path / "study.pdf").write_bytes(b"paper")
    (tmp_path / "study_appendix.pdf").write_bytes(b"appendix")
    (tmp_path / "study_replication").mkdir()
    monkeypatch.setattr(
        rename_module, "read_pdf_candidate", lambda path: {"doi": "10.1234/example"}
    )

    mapping = rename_module.propose(
        tmp_path, tmp_path / "proposal.json", provider=StubProvider()
    )

    destinations = {item["destination"] for item in mapping["items"]}
    assert "Lee_2024_Trade_and_Credit.pdf" in destinations
    assert "Lee_2024_Trade_and_Credit_Appendix.pdf" in destinations
    assert "Lee_2024_Trade_and_Credit_Replication" in destinations
```

- [ ] **Step 2: Run proposal tests and verify RED**

Run:

```bash
python -m pytest tests/rename_and_organize_references/test_propose.py -v
```

Expected: failures because proposal and metadata-provider functions are absent.

- [ ] **Step 3: Implement metadata providers and proposal generation**

Add imports:

```python
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
```

Add provider and local extraction behavior:

```python
class MetadataProvider(Protocol):
    def lookup_doi(self, doi: str) -> dict[str, Any] | None: ...
    def search_title(self, title: str) -> dict[str, Any] | None: ...


class OpenAlexProvider:
    base_url = "https://api.openalex.org/works"

    def _request(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "social-science-research-skills/0.1"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def _metadata(self, work: Mapping[str, Any]) -> dict[str, Any]:
        authors = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            authors.append(
                {
                    "display_name": author.get("display_name", ""),
                    "family_name": author.get("family_name", ""),
                }
            )
        return {
            "title": work.get("title"),
            "year": work.get("publication_year"),
            "authors": authors,
            "doi": normalize_doi(str(work.get("doi") or "")),
            "source": "openalex",
        }

    def lookup_doi(self, doi: str) -> dict[str, Any] | None:
        encoded = urllib.parse.quote(doi, safe="")
        return self._metadata(
            self._request(f"{self.base_url}/https://doi.org/{encoded}")
        )

    def search_title(self, title: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"search": title, "per-page": 1})
        results = self._request(f"{self.base_url}?{query}").get("results", [])
        return self._metadata(results[0]) if results else None


def read_pdf_candidate(path: Path) -> dict[str, Any]:
    reader = PdfReader(path)
    text = "\n".join(
        page.extract_text() or "" for page in reader.pages[: min(3, len(reader.pages))]
    )
    doi_match = DOI_PATTERN.search(text)
    metadata = reader.metadata
    return {
        "doi": normalize_doi(doi_match.group(0)) if doi_match else "",
        "title": str(getattr(metadata, "title", "") or ""),
        "author": str(getattr(metadata, "author", "") or ""),
    }


def accept_title_match(
    query: str, candidate: Mapping[str, Any], *, threshold: float = 0.9
) -> bool:
    candidate_title = str(candidate.get("title") or "")
    ratio = SequenceMatcher(None, query.casefold(), candidate_title.casefold()).ratio()
    return ratio >= threshold


def classify_related(path: Path) -> str | None:
    name = path.stem.casefold() if path.is_file() else path.name.casefold()
    if "appendix" in name:
        return "appendix"
    if "slide" in name or "presentation" in name:
        return "slides"
    if path.is_dir() and ("replication" in name or name.endswith("_code")):
        return "replication"
    return None


def related_to(main: Path, candidate: Path) -> bool:
    main_stem = main.stem.casefold()
    candidate_stem = (
        candidate.stem.casefold() if candidate.is_file() else candidate.name.casefold()
    )
    return candidate_stem.startswith(main_stem)
```

Add proposal generation:

```python
def resolve_metadata(
    path: Path,
    *,
    provider: MetadataProvider | None,
    threshold: float = 0.9,
) -> dict[str, Any] | None:
    try:
        local = read_pdf_candidate(path)
    except Exception:
        local = {}
    if provider and local.get("doi"):
        try:
            return provider.lookup_doi(local["doi"])
        except Exception:
            pass
    query = str(local.get("title") or path.stem.replace("_", " "))
    if provider and query:
        try:
            candidate = provider.search_title(query)
        except Exception:
            candidate = None
        if candidate and accept_title_match(query, candidate, threshold=threshold):
            return candidate
    return None


def propose(
    directory: Path,
    output: Path,
    *,
    provider: MetadataProvider | None,
) -> dict[str, Any]:
    root = directory.resolve()
    items = []
    unresolved = []
    entries = sorted(root.iterdir())
    main_papers = [
        path
        for path in entries
        if path.is_file()
        and path.suffix.casefold() == ".pdf"
        and classify_related(path) is None
    ]
    claimed: set[Path] = set()
    for path in main_papers:
        metadata = resolve_metadata(path, provider=provider)
        if not metadata:
            unresolved.append(
                {"source": path.name, "reason": "required metadata could not be resolved"}
            )
            continue
        try:
            destination = build_filename(metadata, kind="main-paper")
        except ValueError as error:
            unresolved.append({"source": path.name, "reason": str(error)})
            continue
        items.append(
            {
                "source": path.name,
                "destination": destination,
                "kind": "main-paper",
                "confidence": "high" if metadata.get("doi") else "review",
                "metadata": metadata,
            }
        )
        claimed.add(path)
        for candidate in entries:
            kind = classify_related(candidate)
            if candidate in claimed or kind is None or not related_to(path, candidate):
                continue
            items.append(
                {
                    "source": candidate.name,
                    "destination": build_filename(metadata, kind=kind),
                    "kind": kind,
                    "confidence": "high" if metadata.get("doi") else "review",
                    "metadata": metadata,
                }
            )
            claimed.add(candidate)
    for path in entries:
        if path in claimed or path == output:
            continue
        if (path.is_file() and path.suffix.casefold() == ".pdf") or classify_related(path):
            unresolved.append(
                {"source": path.name, "reason": "related material could not be grouped"}
            )
    mapping = {
        "schema_version": 1,
        "root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "unresolved": unresolved,
    }
    output.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    return mapping
```

- [ ] **Step 4: Add the `propose` CLI arguments**

Extend `build_parser()`:

```python
subparsers = parser.add_subparsers(dest="command", required=True)
propose_parser = subparsers.add_parser("propose")
propose_parser.add_argument("--directory", required=True, type=Path)
propose_parser.add_argument("--output", required=True, type=Path)
propose_parser.add_argument(
    "--offline",
    action="store_true",
    help="Disable OpenAlex metadata lookups.",
)
```

Dispatch from `main()`:

```python
args = build_parser().parse_args(argv)
if args.command == "propose":
    provider = None if args.offline else OpenAlexProvider()
    propose(args.directory, args.output, provider=provider)
return 0
```

- [ ] **Step 5: Run proposal and regression tests**

Run:

```bash
python -m pytest tests/rename_and_organize_references -v
python -m ruff check .
```

Expected: all tests pass without network access.

- [ ] **Step 6: Commit proposal generation**

```bash
git add skills/rename-and-organize-references/scripts/rename_references.py \
  tests/rename_and_organize_references/test_propose.py
git commit -m "feat: generate reviewable rename proposals"
```

## Task 4: Validate Mapping Safety Before Filesystem Changes

**Files:**
- Create: `tests/rename_and_organize_references/test_mapping.py`
- Modify: `skills/rename-and-organize-references/scripts/rename_references.py`

- [ ] **Step 1: Write failing mapping validation tests**

Create `tests/rename_and_organize_references/test_mapping.py`:

```python
from __future__ import annotations


def mapping(root, items, unresolved=None):
    return {
        "schema_version": 1,
        "root": str(root),
        "generated_at": "2026-06-07T12:00:00+00:00",
        "items": items,
        "unresolved": unresolved or [],
    }


def test_validate_rejects_path_traversal(rename_module, tmp_path):
    data = mapping(
        tmp_path,
        [{"source": "paper.pdf", "destination": "../escape.pdf", "kind": "main-paper"}],
    )
    (tmp_path / "paper.pdf").touch()

    errors = rename_module.validate_mapping(data)

    assert any("within root" in error for error in errors)


def test_validate_rejects_duplicate_sources(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    data = mapping(
        tmp_path,
        [
            {"source": "paper.pdf", "destination": "one.pdf", "kind": "main-paper"},
            {"source": "paper.pdf", "destination": "two.pdf", "kind": "appendix"},
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("duplicate source" in error for error in errors)


def test_validate_rejects_unrelated_destination_collision(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    (tmp_path / "target.pdf").touch()
    data = mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "target.pdf",
                "kind": "main-paper",
            }
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("already exists" in error for error in errors)


def test_validate_refuses_unresolved_or_review_confidence(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    data = mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "target.pdf",
                "kind": "main-paper",
                "confidence": "review",
            }
        ],
        unresolved=[{"source": "other.pdf", "reason": "metadata"}],
    )

    errors = rename_module.validate_mapping(data)

    assert any("unresolved" in error for error in errors)
    assert any("confidence" in error for error in errors)


def test_validate_rejects_destination_that_is_another_source(rename_module, tmp_path):
    (tmp_path / "one.pdf").touch()
    (tmp_path / "two.pdf").touch()
    data = mapping(
        tmp_path,
        [
            {"source": "one.pdf", "destination": "two.pdf", "kind": "main-paper"},
            {"source": "two.pdf", "destination": "three.pdf", "kind": "main-paper"},
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("another source" in error for error in errors)
```

- [ ] **Step 2: Run mapping tests and verify RED**

Run:

```bash
python -m pytest tests/rename_and_organize_references/test_mapping.py -v
```

Expected: failures because `validate_mapping` does not exist.

- [ ] **Step 3: Implement schema, containment, overlap, and collision checks**

Add:

```python
def contained_path(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def validate_mapping(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    root_value = data.get("root")
    if not isinstance(root_value, str):
        return errors + ["root must be a string"]
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        errors.append(f"root is not a directory: {root}")
    unresolved = data.get("unresolved", [])
    if unresolved:
        errors.append("mapping contains unresolved items")

    items = data.get("items")
    if not isinstance(items, list):
        return errors + ["items must be a list"]

    sources: set[Path] = set()
    destinations: set[Path] = set()
    source_paths: list[Path] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"item {index} must be an object")
            continue
        if item.get("confidence", "high") != "high":
            errors.append(f"item {index} confidence requires review")
        source = contained_path(root, str(item.get("source", "")))
        destination = contained_path(root, str(item.get("destination", "")))
        if source is None or destination is None:
            errors.append(f"item {index} paths must remain within root")
            continue
        if source in sources:
            errors.append(f"duplicate source: {item.get('source')}")
        if destination in destinations:
            errors.append(f"duplicate destination: {item.get('destination')}")
        sources.add(source)
        destinations.add(destination)
        source_paths.append(source)
        if not source.exists():
            errors.append(f"source does not exist: {item.get('source')}")

    for destination in destinations:
        if destination.exists() and destination not in sources:
            errors.append(f"destination already exists: {destination.name}")
        if destination in sources:
            errors.append(f"destination is another source: {destination.name}")

    for source in source_paths:
        if not source.is_dir():
            continue
        for destination in destinations:
            if destination == source:
                continue
            try:
                destination.relative_to(source)
            except ValueError:
                continue
            errors.append(f"directory destination overlaps source: {source.name}")
    return errors


def load_mapping(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Add the `validate` CLI**

Add parser configuration:

```python
validate_parser = subparsers.add_parser("validate")
validate_parser.add_argument("--mapping", required=True, type=Path)
```

Add dispatch:

```python
if args.command == "validate":
    errors = validate_mapping(load_mapping(args.mapping))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Mapping is valid.")
```

Add `import sys`.

- [ ] **Step 5: Run mapping and regression tests**

Run:

```bash
python -m pytest tests/rename_and_organize_references -v
python -m ruff check .
```

Expected: all tests pass.

- [ ] **Step 6: Commit mapping validation**

```bash
git add skills/rename-and-organize-references/scripts/rename_references.py \
  tests/rename_and_organize_references/test_mapping.py
git commit -m "feat: validate rename mappings safely"
```

## Task 5: Apply Reviewed Mappings and Record Recoverable Results

**Files:**
- Create: `tests/rename_and_organize_references/test_apply.py`
- Modify: `skills/rename-and-organize-references/scripts/rename_references.py`

- [ ] **Step 1: Write failing apply tests**

Create `tests/rename_and_organize_references/test_apply.py`:

```python
from __future__ import annotations

import json


def valid_mapping(root, items):
    return {
        "schema_version": 1,
        "root": str(root),
        "generated_at": "2026-06-07T12:00:00+00:00",
        "items": items,
        "unresolved": [],
    }


def test_apply_moves_files_and_writes_result(rename_module, tmp_path):
    (tmp_path / "paper.pdf").write_text("paper")
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "Lee_2024_Trade.pdf",
                "kind": "main-paper",
                "confidence": "high",
            }
        ],
    )
    result_path = tmp_path / "result.json"

    result = rename_module.apply_mapping(data, result_path)

    assert not (tmp_path / "paper.pdf").exists()
    assert (tmp_path / "Lee_2024_Trade.pdf").read_text() == "paper"
    assert result["status"] == "completed"
    assert result["completed"][0]["reverse"]["source"] == "Lee_2024_Trade.pdf"
    assert json.loads(result_path.read_text()) == result


def test_apply_refuses_invalid_mapping_before_changes(rename_module, tmp_path):
    (tmp_path / "paper.pdf").write_text("paper")
    (tmp_path / "target.pdf").write_text("existing")
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "target.pdf",
                "kind": "main-paper",
                "confidence": "high",
            }
        ],
    )

    try:
        rename_module.apply_mapping(data, tmp_path / "result.json")
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("invalid mapping must be rejected")

    assert (tmp_path / "paper.pdf").exists()


def test_apply_logs_partial_completion_on_runtime_failure(
    rename_module, tmp_path, monkeypatch
):
    (tmp_path / "one.pdf").touch()
    (tmp_path / "two.pdf").touch()
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "one.pdf",
                "destination": "one-new.pdf",
                "kind": "main-paper",
                "confidence": "high",
            },
            {
                "source": "two.pdf",
                "destination": "two-new.pdf",
                "kind": "main-paper",
                "confidence": "high",
            },
        ],
    )
    original_move = rename_module.shutil.move
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated failure")
        return original_move(source, destination)

    monkeypatch.setattr(rename_module.shutil, "move", fail_second)
    result_path = tmp_path / "result.json"

    try:
        rename_module.apply_mapping(data, result_path)
    except OSError:
        pass
    else:
        raise AssertionError("runtime failure must be propagated")

    result = json.loads(result_path.read_text())
    assert result["status"] == "failed"
    assert len(result["completed"]) == 1
```

- [ ] **Step 2: Run apply tests and verify RED**

Run:

```bash
python -m pytest tests/rename_and_organize_references/test_apply.py -v
```

Expected: failures because `apply_mapping` is absent.

- [ ] **Step 3: Implement deterministic operation ordering and result logging**

Add `import shutil` and:

```python
def ordered_items(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(
        data["items"],
        key=lambda item: (
            -len(Path(str(item["source"])).parts),
            str(item["source"]),
        ),
    )


def write_result(path: Path, result: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def apply_mapping(data: Mapping[str, Any], result_path: Path) -> dict[str, Any]:
    errors = validate_mapping(data)
    if errors:
        raise ValueError("; ".join(errors))
    root = Path(str(data["root"])).expanduser().resolve()
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "root": str(root),
        "completed": [],
        "error": None,
    }
    write_result(result_path, result)
    try:
        for item in ordered_items(data):
            source = root / str(item["source"])
            destination = root / str(item["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            result["completed"].append(
                {
                    "source": item["source"],
                    "destination": item["destination"],
                    "kind": item.get("kind"),
                    "reverse": {
                        "source": item["destination"],
                        "destination": item["source"],
                    },
                }
            )
            write_result(result_path, result)
    except Exception as error:
        result["status"] = "failed"
        result["error"] = str(error)
        write_result(result_path, result)
        raise
    result["status"] = "completed"
    write_result(result_path, result)
    return result
```

- [ ] **Step 4: Add the `apply` CLI**

Add parser configuration:

```python
apply_parser = subparsers.add_parser("apply")
apply_parser.add_argument("--mapping", required=True, type=Path)
apply_parser.add_argument("--result", type=Path)
```

Add dispatch:

```python
if args.command == "apply":
    result_path = args.result or args.mapping.with_name(
        f"{args.mapping.stem}-result.json"
    )
    try:
        apply_mapping(load_mapping(args.mapping), result_path)
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Result written to {result_path}")
```

- [ ] **Step 5: Run all first-skill tests**

Run:

```bash
python -m pytest tests/rename_and_organize_references -v
python -m ruff check .
```

Expected: all first-skill tests pass.

- [ ] **Step 6: Commit apply behavior**

```bash
git add skills/rename-and-organize-references/scripts/rename_references.py \
  tests/rename_and_organize_references/test_apply.py
git commit -m "feat: apply reviewed rename mappings"
```

## Task 6: Build the Multi-Client Installer

**Files:**
- Create: `tests/test_install.py`
- Modify: `scripts/install.py`

- [ ] **Step 1: Write failing installer tests**

Create `tests/test_install.py`:

```python
from __future__ import annotations


def make_skill(root, name="example-skill"):
    skill = root / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing.\n---\n"
    )
    return skill


def test_resolve_targets_deduplicates_shared_agents_directory(
    install_module, tmp_path
):
    home = tmp_path / "home"

    destinations = install_module.resolve_destinations(
        ["codex", "opencode", "copilot"], home=home
    )

    assert destinations == [home / ".agents" / "skills"]


def test_copy_install_replaces_only_selected_skill(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"
    unrelated = destination / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "SKILL.md").write_text("keep")

    install_module.install_skill(skill, destination, link=False, dry_run=False)

    assert (destination / "example-skill" / "SKILL.md").exists()
    assert (unrelated / "SKILL.md").read_text() == "keep"


def test_link_install_creates_symlink(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"

    install_module.install_skill(skill, destination, link=True, dry_run=False)

    assert (destination / "example-skill").is_symlink()


def test_dry_run_does_not_modify_destination(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"

    install_module.install_skill(skill, destination, link=False, dry_run=True)

    assert not destination.exists()


def test_validate_skill_rejects_mismatched_name(install_module, tmp_path):
    skill = make_skill(tmp_path, name="folder-name")
    (skill / "SKILL.md").write_text(
        "---\nname: different-name\ndescription: Use when testing.\n---\n"
    )

    try:
        install_module.validate_skill(skill)
    except ValueError as error:
        assert "must match" in str(error)
    else:
        raise AssertionError("mismatched skill names must fail")
```

- [ ] **Step 2: Run installer tests and verify RED**

Run:

```bash
python -m pytest tests/test_install.py -v
```

Expected: failures because installer functions are absent.

- [ ] **Step 3: Implement target resolution and skill validation**

Replace `scripts/install.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


TARGET_PATHS = {
    "antigravity": Path(".gemini/antigravity/skills"),
    "claude": Path(".claude/skills"),
    "codex": Path(".agents/skills"),
    "opencode": Path(".agents/skills"),
    "copilot": Path(".agents/skills"),
}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path} is missing YAML frontmatter")
    values = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def validate_skill(skill: Path) -> None:
    skill_file = skill / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{skill} does not contain SKILL.md")
    metadata = parse_frontmatter(skill_file)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if name != skill.name:
        raise ValueError("SKILL.md name must match the skill directory")
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("skill name must be lowercase hyphen-case")
    if not description:
        raise ValueError("SKILL.md description is required")


def resolve_destinations(targets: list[str], *, home: Path) -> list[Path]:
    resolved = []
    seen = set()
    for target in targets:
        destination = (home / TARGET_PATHS[target]).resolve()
        if destination not in seen:
            resolved.append(destination)
            seen.add(destination)
    return resolved
```

- [ ] **Step 4: Implement copy, link, replacement, and dry-run behavior**

Append:

```python
def install_skill(
    skill: Path,
    destination: Path,
    *,
    link: bool,
    dry_run: bool,
) -> None:
    validate_skill(skill)
    target = destination / skill.name
    action = "link" if link else "copy"
    print(f"{action}: {skill} -> {target}")
    if dry_run:
        return
    destination.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    if link:
        target.symlink_to(skill.resolve(), target_is_directory=True)
    else:
        shutil.copytree(skill, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install portable research skills.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--skill", action="append")
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGET_PATHS),
        help="Install only for the selected client; repeatable.",
    )
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--link", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    skills_root = repo_root / "skills"
    if args.all:
        skills = sorted(path for path in skills_root.iterdir() if path.is_dir())
    else:
        skills = [skills_root / name for name in args.skill]
    for skill in skills:
        validate_skill(skill)
    if args.destination:
        destinations = [args.destination.expanduser().resolve()]
    else:
        targets = args.target or list(TARGET_PATHS)
        destinations = resolve_destinations(targets, home=Path.home())
    for destination in destinations:
        for skill in skills:
            install_skill(
                skill,
                destination,
                link=args.link,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run installer tests and a CLI dry-run**

Run:

```bash
python -m pytest tests/test_install.py -v
python scripts/install.py --all --dry-run
python -m ruff check .
```

Expected:

- Installer tests pass.
- Dry-run prints three distinct destinations: Antigravity, Claude, and the
  shared `.agents/skills` path.
- No destination is created by the dry-run.

- [ ] **Step 6: Commit the installer**

```bash
git add scripts/install.py tests/test_install.py
git commit -m "feat: install skills across supported clients"
```

## Task 7: Write the Skill, Schema Reference, and Repository Documentation

**Files:**
- Create: `skills/rename-and-organize-references/SKILL.md`
- Create: `skills/rename-and-organize-references/references/mapping-format.md`
- Create: `skills/rename-and-organize-references/agents/openai.yaml`
- Create: `tests/test_skill_structure.py`
- Create: `README.md`

- [ ] **Step 1: Write failing structure and portability tests**

Create `tests/test_skill_structure.py`:

```python
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "rename-and-organize-references"


def test_skill_has_required_frontmatter():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "\nname: rename-and-organize-references\n" in text
    assert re.search(r"\ndescription: .+\n", text)


def test_skill_contains_no_machine_specific_paths():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL.rglob("*")
        if path.is_file()
    )
    forbidden = [
        "/Users/",
        "/home/linshih",
        ".gemini/config/plugins/superpowers",
        "conda run -n",
    ]
    assert all(value not in text for value in forbidden)


def test_skill_references_existing_bundled_files():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    expected = [
        "scripts/rename_references.py",
        "references/mapping-format.md",
    ]
    assert all(value in text for value in expected)
    assert all((SKILL / value).is_file() for value in expected)
```

- [ ] **Step 2: Run structure tests and verify RED**

Run:

```bash
python -m pytest tests/test_skill_structure.py -v
```

Expected: failures because `SKILL.md` and references do not yet exist.

- [ ] **Step 3: Write the agent-facing skill**

Create `skills/rename-and-organize-references/SKILL.md`:

```markdown
---
name: rename-and-organize-references
description: Use when academic paper PDFs, appendices, slides, or replication materials need consistent author-year-title filenames and a reviewed, safe reorganization plan.
---

# Rename and Organize References

## Workflow

1. Identify the target reference directory and confirm its scope.
2. Locate this skill directory, assign its absolute path to `SKILL_DIR`, and
   invoke the bundled script through that variable.
3. Generate a proposal before changing files:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" propose \
     --directory /path/to/references \
     --output /path/to/references/proposed-renames.json
   ```

4. Review `unresolved`, every item with non-high confidence, metadata, and all
   source/destination pairs. Edit the JSON only when the correction is supported
   by the paper or a reliable metadata source.
5. Read `references/mapping-format.md` when editing or diagnosing a proposal.
6. Validate the reviewed mapping:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" validate \
     --mapping /path/to/references/proposed-renames.json
   ```

7. Apply only after validation succeeds and the user approves the exact mapping:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" apply \
     --mapping /path/to/references/proposed-renames.json
   ```

8. Inspect the result JSON and verify every completed destination.

Use `--offline` with `propose` when network access is unavailable or not
permitted.

## Naming Convention

- Main paper: `[Authors]_[Year]_[Title].pdf`
- Appendix: `[Authors]_[Year]_[Title]_Appendix.pdf`
- Slides: `[Authors]_[Year]_[Title]_Slides.pdf`
- Replication directory: `[Authors]_[Year]_[Title]_Replication/`

For one to three authors, retain family names in publication order. For four or
more authors, use the first family name followed by `_et_al`.

## Safety Rules

- Never run `apply` on an unreviewed proposal.
- Never invent an author, publication year, or title.
- Treat unresolved metadata and title-search matches as review items.
- Do not bypass collision, containment, or duplicate-operation failures.
- Warn that renaming replication directories can break hard-coded paths inside
  research code; this skill does not rewrite those paths.
- Preserve the result JSON because it records completed operations and reverse
  paths after a failure.

## Dependencies

Use Python 3.10 or newer and install `pypdf`:

```bash
python -m pip install "pypdf>=5.0"
```
```

- [ ] **Step 4: Document the mapping schema**

Create `skills/rename-and-organize-references/references/mapping-format.md` with:

```markdown
# Rename Mapping Format

## Top-Level Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Must be `1`. |
| `root` | string | Absolute reference-directory path. |
| `generated_at` | string | UTC ISO 8601 generation time. |
| `items` | array | Reviewed rename operations. |
| `unresolved` | array | Files that cannot yet be applied. |

## Item Fields

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Existing path relative to `root`. |
| `destination` | string | Planned path relative to `root`. |
| `kind` | string | `main-paper`, `appendix`, `slides`, or `replication`. |
| `confidence` | string | Must be `high` before application. |
| `metadata` | object | Title, year, ordered authors, DOI, and source. |

## Review Checklist

- Confirm the DOI belongs to the source paper.
- Confirm author order and family names.
- Confirm publication year and title.
- Confirm appendix, slides, and replication materials belong to the main paper.
- Resolve or remove every `unresolved` entry.
- Change every accepted item's confidence to `high`.
- Confirm no destination overwrites unrelated material.

All item paths must remain relative to `root`. The validator rejects traversal,
duplicate sources or destinations, unresolved items, low-confidence items, and
unrelated destination collisions.
```

- [ ] **Step 5: Add optional Codex UI metadata**

Create `skills/rename-and-organize-references/agents/openai.yaml`:

```yaml
interface:
  display_name: "Rename and Organize References"
  short_description: "Safely standardize academic reference files"
  default_prompt: "Use $rename-and-organize-references to propose and review consistent names for my academic reference files."
```

- [ ] **Step 6: Write the repository README**

Create `README.md` with these exact sections:

```markdown
# Social Science Research Skills

Portable Agent Skills for repeatable social science research workflows.

## Supported Clients

- Google Antigravity
- Claude Code
- OpenAI Codex
- OpenCode
- GitHub Copilot CLI

## Install

```bash
git clone https://github.com/linshih-yang/social-science-research-skills.git
cd social-science-research-skills
python scripts/install.py --all
```

Install for one client:

```bash
python scripts/install.py \
  --skill rename-and-organize-references \
  --target claude
```

Preview without changing files:

```bash
python scripts/install.py --all --dry-run
```

Use symbolic links while developing:

```bash
python scripts/install.py --all --link
```

The installer copies skills by default. Codex, OpenCode, and Copilot CLI share
`~/.agents/skills`; Antigravity and Claude Code use their own skill directories.

## Skills

### `rename-and-organize-references`

Creates a reviewable mapping for academic paper PDFs and related materials,
validates it, and applies deterministic author-year-title names.

Runtime dependency:

```bash
python -m pip install "pypdf>=5.0"
```

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
```

Add each canonical skill under `skills/<skill-name>/`. The directory name must
match the `name` in `SKILL.md`. Keep bundled paths relative and avoid
client-specific or machine-specific assumptions.
```

- [ ] **Step 7: Run structure and full regression tests**

Run:

```bash
python -m pytest -v
python -m ruff check .
git diff --check
```

Expected: all tests pass, Ruff passes, and Git reports no whitespace errors.

- [ ] **Step 8: Run end-to-end CLI checks from an arbitrary directory**

Run:

```bash
repo_root="$(pwd)"
tmp_root="$(mktemp -d)"
cd "$tmp_root"
python "$repo_root/scripts/install.py" \
  --skill rename-and-organize-references \
  --destination "$tmp_root/installed" \
  --dry-run
python "$repo_root/skills/rename-and-organize-references/scripts/rename_references.py" \
  --help
cd "$repo_root"
rm -rf "$tmp_root"
```

Expected:

- Installer dry-run reports the intended skill destination.
- Rename CLI help lists `propose`, `validate`, and `apply`.
- No script relies on the repository as the current working directory.

- [ ] **Step 9: Commit skill and documentation**

```bash
git add README.md \
  skills/rename-and-organize-references/SKILL.md \
  skills/rename-and-organize-references/references/mapping-format.md \
  skills/rename-and-organize-references/agents/openai.yaml \
  tests/test_skill_structure.py
git commit -m "docs: publish first portable research skill"
```

## Task 8: Perform Final Acceptance Verification

**Files:**
- Modify only files implicated by verification failures.

- [ ] **Step 1: Verify the complete automated suite**

Run:

```bash
python -m pytest -v
python -m ruff check .
git diff --check
```

Expected: all commands exit successfully.

- [ ] **Step 2: Verify installer destination deduplication**

Run:

```bash
python scripts/install.py \
  --skill rename-and-organize-references \
  --target codex \
  --target opencode \
  --target copilot \
  --dry-run
```

Expected: the shared `~/.agents/skills/rename-and-organize-references`
destination appears exactly once.

- [ ] **Step 3: Verify proposal generation is read-only**

Create a temporary empty PDF-like fixture and run offline proposal generation:

```bash
tmp_root="$(mktemp -d)"
printf 'not a real pdf' > "$tmp_root/unknown.pdf"
python skills/rename-and-organize-references/scripts/rename_references.py \
  propose \
  --directory "$tmp_root" \
  --output "$tmp_root/proposed-renames.json" \
  --offline
test -f "$tmp_root/unknown.pdf"
test -f "$tmp_root/proposed-renames.json"
python -c 'import json,sys; data=json.load(open(sys.argv[1])); assert data["items"] == []; assert data["unresolved"]' "$tmp_root/proposed-renames.json"
rm -rf "$tmp_root"
```

Expected: the source remains and the proposal contains an unresolved item.

- [ ] **Step 4: Verify repository state and commit any verification fixes**

Run:

```bash
git status --short
git log --oneline --decorate -8
```

Expected: the worktree is clean and the implementation is represented by
focused commits. If verification required fixes, commit only those fixes:

```bash
git add README.md pyproject.toml scripts tests skills
git commit -m "fix: address acceptance verification findings"
```
