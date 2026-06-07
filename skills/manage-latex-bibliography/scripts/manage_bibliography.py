#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATUSES = {
    "candidate",
    "verified",
    "needs-user-confirmation",
    "approved",
    "rejected",
    "unresolved",
}
PROPOSAL_FIELDS = {
    "schema_version",
    "project_root",
    "main_tex",
    "bibliography_system",
    "target_bib",
    "citations",
    "new_entries",
    "existing_entry_corrections",
    "inferred_references",
    "tex_changes",
    "unresolved",
    "verification_report",
    "warnings",
    "file_digests",
}
ENTRY_FIELDS = {
    "citation_key",
    "entry_type",
    "fields",
    "sources",
    "conflicts",
    "status",
    "verifier",
    "requires_user_approval",
    "user_approval",
}
CORRECTION_FIELDS = ENTRY_FIELDS | {"before_fields"}
SUPPORTED_ENTRY_TYPES = {
    "article",
    "book",
    "incollection",
    "inproceedings",
    "phdthesis",
    "techreport",
    "unpublished",
    "misc",
}
REQUIRED_ENTRY_FIELDS = {
    "article": ({"author", "title", "journal", "year"},),
    "book": ({"title", "publisher", "year"},),
    "incollection": ({"author", "title", "booktitle", "publisher", "year"},),
    "inproceedings": ({"author", "title", "booktitle", "year"},),
    "phdthesis": ({"author", "title", "school", "year"},),
    "techreport": ({"author", "title", "institution", "year"},),
    "unpublished": ({"author", "title", "year", "note"},),
    "misc": ({"title", "year"},),
}

INPUT_COMMAND_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
CITATION_COMMAND_RE = re.compile(
    r"""
    \\(?:
        citeauthor|citeyear|citealp|citealt|citep|citet|cite|
        parencite|textcite|autocite
    )
    \*?
    (?:\s*\[[^\]]*\]){0,2}
    \s*\{([^{}]*)\}
    """,
    re.VERBOSE,
)
BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^{}]*)\}")
BIBLIOGRAPHY_STYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^{}]*)\}")
USEPACKAGE_RE = re.compile(r"\\usepackage(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}")
ADD_BIB_RESOURCE_RE = re.compile(r"\\addbibresource(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}")
BIBTEX_ENTRY_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_-]*)\s*([({])")
DOI_PREFIX_RE = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE
)
BIBTEX_DIRECTIVES = {"comment", "preamble", "string"}
TRAILING_DOI_PUNCTUATION = ".,;:"
DELIMITER_PAIRS = {")": "(", "]": "[", "}": "{"}
TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uncommented_tex(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return "\n".join(strip_tex_comment(line) for line in text.splitlines())


def select_main_tex(project: Path) -> tuple[Path, Path]:
    selected = project.resolve()
    if selected.is_file():
        if selected.suffix.lower() != ".tex":
            raise ValueError("project file must be a .tex file")
        return selected.parent, selected
    if not selected.is_dir():
        raise ValueError(f"project does not exist: {selected}")

    candidates = [
        path.resolve()
        for path in sorted(selected.glob("*.tex"))
        if re.search(r"\\documentclass(?:\s*\[[^\]]*\])?\s*\{", _uncommented_tex(path))
    ]
    if len(candidates) != 1:
        raise ValueError(
            "project directory must contain exactly one top-level .tex file "
            "with \\documentclass"
        )
    return selected, candidates[0]


def _resolve_project_path(path: Path, root: Path) -> tuple[Path, Path]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{resolved_path} is outside project root") from exc
    return resolved_path, resolved_root


def strip_tex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        position = index - 1
        while position >= 0 and line[position] == "\\":
            backslashes += 1
            position -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def tex_reference_path(reference: str) -> Path:
    path = Path(reference.strip())
    if path.suffix == "":
        return path.with_suffix(".tex")
    return path


def discover_tex_files(main: Path, root: Path) -> list[Path]:
    resolved_main, resolved_root = _resolve_project_path(main, root)
    discovered: set[Path] = set()

    def visit(source: Path) -> None:
        if source in discovered:
            return
        if not source.is_file():
            raise FileNotFoundError(source)
        discovered.add(source)

        lines = source.read_text(encoding="utf-8").splitlines()
        uncommented_text = "\n".join(strip_tex_comment(line) for line in lines)
        for match in INPUT_COMMAND_RE.finditer(uncommented_text):
            included = tex_reference_path(match.group(1))
            candidate, _ = _resolve_project_path(
                source.parent / included, resolved_root
            )
            visit(candidate)

    visit(resolved_main)
    return [resolved_main, *sorted(discovered - {resolved_main})]


def scan_citations(source: Path, root: Path) -> list[dict[str, str | int]]:
    resolved_source, resolved_root = _resolve_project_path(source, root)
    if not resolved_source.is_file():
        raise FileNotFoundError(resolved_source)
    relative_source = resolved_source.relative_to(resolved_root).as_posix()
    citations: list[dict[str, str | int]] = []

    text = resolved_source.read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), 1):
        uncommented = strip_tex_comment(line)
        for match in CITATION_COMMAND_RE.finditer(uncommented):
            for raw_key in match.group(1).split(","):
                key = raw_key.strip()
                if key:
                    citations.append(
                        {
                            "key": key,
                            "source": relative_source,
                            "line": line_number,
                        }
                    )
    return citations


def _bibliography_path(reference: str) -> Path:
    path = Path(reference.strip())
    if path.suffix == "":
        return path.with_suffix(".bib")
    return path


def detect_bibliography(sources: list[Path], root: Path) -> dict[str, object]:
    resolved_root = root.resolve()
    targets: set[str] = set()
    styles: set[str] = set()
    uses_biblatex = False

    for source in sources:
        resolved_source, _ = _resolve_project_path(source, resolved_root)
        if not resolved_source.is_file():
            raise FileNotFoundError(resolved_source)
        text = resolved_source.read_text(encoding="utf-8")
        uncommented = "\n".join(strip_tex_comment(line) for line in text.splitlines())

        for match in USEPACKAGE_RE.finditer(uncommented):
            packages = {package.strip() for package in match.group(1).split(",")}
            if "biblatex" in packages:
                uses_biblatex = True

        for match in ADD_BIB_RESOURCE_RE.finditer(uncommented):
            uses_biblatex = True
            target, _ = _resolve_project_path(
                resolved_source.parent / _bibliography_path(match.group(1)),
                resolved_root,
            )
            targets.add(target.relative_to(resolved_root).as_posix())

        for match in BIBLIOGRAPHY_RE.finditer(uncommented):
            for reference in match.group(1).split(","):
                if not reference.strip():
                    continue
                target, _ = _resolve_project_path(
                    resolved_source.parent / _bibliography_path(reference),
                    resolved_root,
                )
                targets.add(target.relative_to(resolved_root).as_posix())

        for match in BIBLIOGRAPHY_STYLE_RE.finditer(uncommented):
            style = match.group(1).strip()
            if style:
                styles.add(style)

    return {
        "system": "biblatex" if uses_biblatex else "bibtex",
        "targets": sorted(targets),
        "styles": sorted(styles),
    }


def _find_entry_end(text: str, opener_index: int, opener: str) -> int:
    quote = False
    escaped = False
    brace_depth = 1 if opener == "{" else 0
    base_brace_depth = brace_depth
    parenthesis_depth = 1 if opener == "(" else 0

    for index in range(opener_index + 1, len(text)):
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "{":
                brace_depth += 1
            elif character == "}":
                brace_depth -= 1
            elif character == '"' and brace_depth == base_brace_depth:
                quote = False
            continue

        if character == '"' and brace_depth == base_brace_depth:
            quote = True
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            if brace_depth:
                brace_depth -= 1
                if opener == "{" and brace_depth == 0:
                    return index
        elif opener == "(" and brace_depth == 0:
            if character == "(":
                parenthesis_depth += 1
            elif character == ")":
                parenthesis_depth -= 1
                if parenthesis_depth == 0:
                    return index

    raise ValueError(f"unbalanced BibTeX entry at index {opener_index}")


def _split_bibtex_parts(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    brace_depth = 0
    quote = False
    escaped = False

    for index, character in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "{":
                brace_depth += 1
            elif character == "}":
                brace_depth -= 1
            elif character == '"' and brace_depth == 0:
                quote = False
            continue

        if character == '"' and brace_depth == 0:
            quote = True
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif character == "," and brace_depth == 0:
            parts.append(text[start:index])
            start = index + 1

    if quote or brace_depth:
        raise ValueError("unbalanced BibTeX entry")
    parts.append(text[start:])
    return parts


def _strip_outer_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2:
        if value[0] == "{" and value[-1] == "}":
            return value[1:-1]
        if value[0] == '"' and value[-1] == '"':
            return value[1:-1]
    return value


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    position = index - 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _mask_comment(masked: list[str], text: str, index: int) -> int:
    while index < len(text) and text[index] not in "\r\n":
        masked[index] = " "
        index += 1
    return index


def _mask_entry_comments(
    masked: list[str], text: str, opener_index: int, opener: str
) -> int:
    index = opener_index + 1
    entry_brace_depth = 1 if opener == "{" else 0
    entry_parenthesis_depth = 1 if opener == "(" else 0
    value_brace_depth = 0
    quoted_value = False
    bare_value = False
    awaiting_value = False
    escaped = False

    while index < len(text):
        character = text[index]

        if quoted_value:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted_value = False
            index += 1
            continue

        if value_brace_depth:
            if not _is_escaped(text, index):
                if character == "{":
                    value_brace_depth += 1
                    if opener == "{":
                        entry_brace_depth += 1
                elif character == "}":
                    value_brace_depth -= 1
                    if opener == "{":
                        entry_brace_depth -= 1
            index += 1
            continue

        if bare_value:
            if character == ",":
                bare_value = False
            elif (opener, character) in {("{", "}"), ("(", ")")}:
                return index
            index += 1
            continue

        if character == "%" and not _is_escaped(text, index):
            index = _mask_comment(masked, text, index)
            continue

        if awaiting_value:
            if character.isspace():
                index += 1
                continue
            awaiting_value = False
            if character == "{":
                value_brace_depth = 1
                if opener == "{":
                    entry_brace_depth += 1
            elif character == '"':
                quoted_value = True
            else:
                bare_value = True
            index += 1
            continue

        if character == "=":
            awaiting_value = True
        elif opener == "{":
            if character == "{":
                entry_brace_depth += 1
            elif character == "}":
                entry_brace_depth -= 1
                if entry_brace_depth == 0:
                    return index
        elif character == "(":
            entry_parenthesis_depth += 1
        elif character == ")":
            entry_parenthesis_depth -= 1
            if entry_parenthesis_depth == 0:
                return index
        index += 1

    raise ValueError(f"unbalanced BibTeX entry at index {opener_index}")


def _mask_bibtex_comments(text: str) -> str:
    masked = list(text)
    index = 0

    while index < len(text):
        entry_match = BIBTEX_ENTRY_RE.match(text, index)
        if entry_match:
            opener_index = entry_match.end() - 1
            index = (
                _mask_entry_comments(masked, text, opener_index, entry_match.group(2))
                + 1
            )
            continue

        if text[index] != "%":
            index += 1
            continue

        if _is_escaped(text, index):
            index += 1
            continue

        index = _mask_comment(masked, text, index)

    return "".join(masked)


def parse_bibtex_entries(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    searchable_text = _mask_bibtex_comments(text)
    search_start = 0

    while match := BIBTEX_ENTRY_RE.search(searchable_text, search_start):
        entry_start = match.start()
        opener = match.group(2)
        opener_index = match.end() - 1
        entry_end = _find_entry_end(searchable_text, opener_index, opener)
        search_start = entry_end + 1
        if match.group(1).lower() in BIBTEX_DIRECTIVES:
            continue

        parts = _split_bibtex_parts(searchable_text[opener_index + 1 : entry_end])
        key = parts[0].strip()
        fields: dict[str, str] = {}

        for part in parts[1:]:
            if not part.strip():
                continue
            name, separator, value = part.partition("=")
            if not separator:
                continue
            fields[name.strip().lower()] = _strip_outer_value(value)

        entries.append(
            {
                "type": match.group(1).lower(),
                "key": key,
                "fields": fields,
                "start": entry_start,
                "end": entry_end,
            }
        )

    return entries


def _strip_unmatched_trailing_delimiters(value: str) -> str:
    while value and value[-1] in DELIMITER_PAIRS:
        closer = value[-1]
        opener = DELIMITER_PAIRS[closer]
        if value.count(closer) <= value.count(opener):
            break
        value = value[:-1].rstrip(TRAILING_DOI_PUNCTUATION)
    return value


def normalize_doi(value: str) -> str:
    normalized = DOI_PREFIX_RE.sub("", value.strip())
    normalized = normalized.rstrip(TRAILING_DOI_PUNCTUATION).strip()
    return _strip_unmatched_trailing_delimiters(normalized).lower()


def find_duplicate_identifiers(entries: list[dict[str, object]]) -> list[str]:
    identifiers: dict[str, dict[str, set[str]]] = {"DOI": {}, "ISBN": {}}

    for entry in entries:
        key = str(entry["key"])
        fields = entry.get("fields", {})
        if not isinstance(fields, dict):
            continue

        doi = fields.get("doi")
        if doi:
            normalized_doi = normalize_doi(str(doi))
            identifiers["DOI"].setdefault(normalized_doi, set()).add(key)

        isbn = fields.get("isbn")
        if isbn:
            normalized_isbn = re.sub(r"[\s-]+", "", str(isbn).lower())
            identifiers["ISBN"].setdefault(normalized_isbn, set()).add(key)

    messages: list[str] = []
    for kind in ("DOI", "ISBN"):
        for identifier, keys in sorted(identifiers[kind].items()):
            if len(keys) > 1:
                messages.append(
                    f"duplicate {kind} {identifier}: "
                    + ", ".join(sorted(keys, key=str.casefold))
                )
    return messages


def _ascii_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


def _first_author_family(author_field: str) -> str:
    first_author = re.split(r"\s+and\s+", author_field, maxsplit=1, flags=re.I)[0]
    first_author = first_author.replace("{", "").replace("}", "").strip()
    if not first_author:
        return ""
    family = (
        first_author.split(",", maxsplit=1)[0]
        if "," in first_author
        else first_author.split()[-1]
    )
    return _ascii_identifier(family)


def _semantic_title_words(title: str) -> list[str]:
    plain = re.sub(r"\\[A-Za-z]+", " ", title)
    plain = re.sub(r"[{}$]", " ", plain)
    return [
        _ascii_identifier(word)
        for word in re.findall(r"[A-Za-z0-9]+", plain)
        if word.lower() not in TITLE_STOP_WORDS and _ascii_identifier(word)
    ]


def generate_citation_key(fields: dict[str, str], existing: set[str]) -> str:
    author = _first_author_family(fields.get("author", ""))
    year = re.sub(r"\D", "", fields.get("year", ""))
    words = _semantic_title_words(fields.get("title", ""))
    if not author or not year or not words:
        raise ValueError("author, year, and title are required for citation key")
    for count in range(1, len(words) + 1):
        candidate = f"{author}{year}{''.join(words[:count])}"
        if candidate not in existing:
            return candidate
    raise ValueError("unable to generate unique semantic citation key")


def _protected_title_segments(value: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    plain_start = 0
    index = 0
    while index < len(value):
        end = None
        if value[index] == "{":
            end = _find_entry_end(value, index, "{")
        elif value[index] == "$" and not _is_escaped(value, index):
            end = value.find("$", index + 1)
            if end < 0:
                raise ValueError("unbalanced math in title")
        elif value[index] == "\\":
            command = re.match(r"\\(?:[A-Za-z]+|.)", value[index:])
            if command:
                end = index + len(command.group()) - 1
        if end is None:
            index += 1
            continue
        if plain_start < index:
            segments.append((value[plain_start:index], False))
        segments.append((value[index : end + 1], True))
        index = end + 1
        plain_start = index
    if plain_start < len(value):
        segments.append((value[plain_start:], False))
    return segments


def headline_title(value: str) -> str:
    tokens: list[tuple[str, str]] = []
    for segment, protected in _protected_title_segments(value):
        if protected:
            tokens.append((segment, "protected"))
            continue
        for token in re.findall(r"\s+|[A-Za-z]+(?:['-][A-Za-z]+)*|.", segment):
            kind = (
                "word"
                if re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", token)
                else "other"
            )
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
                capitalize_next
                or index == last_word
                or lower not in TITLE_STOP_WORDS
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


def _empty_entry(key: str) -> dict[str, object]:
    return {
        "citation_key": key,
        "entry_type": None,
        "fields": {},
        "sources": [],
        "conflicts": [],
        "status": "candidate",
        "verifier": None,
        "requires_user_approval": False,
        "user_approval": None,
    }


def _select_target(
    bibliography: dict[str, object],
) -> tuple[str, list[str], list[dict[str, str]]]:
    system = str(bibliography["system"])
    targets = bibliography["targets"]
    styles = bibliography["styles"]
    if not isinstance(targets, list) or not isinstance(styles, list):
        raise ValueError("invalid bibliography detection result")

    warnings: list[str] = []
    tex_changes: list[dict[str, str]] = []
    if len(targets) > 1:
        raise ValueError("expected exactly one bibliography target")
    if system == "biblatex":
        if not targets:
            raise ValueError("biblatex project must declare exactly one target")
        warnings.append("biblatex detected; aea.bst is not activated")
        return str(targets[0]), warnings, tex_changes

    target = str(targets[0]) if targets else "references.bib"
    non_aea_styles = sorted(style for style in styles if style != "aea")
    if non_aea_styles:
        warnings.append(
            "existing bibliography style preserved: " + ", ".join(non_aea_styles)
        )
    return target, warnings, tex_changes


def build_scan_proposal(project: Path) -> dict[str, object]:
    root, main = select_main_tex(project)
    sources = discover_tex_files(main, root)
    bibliography = detect_bibliography(sources, root)
    target_bib, warnings, tex_changes = _select_target(bibliography)
    target_path, _ = _resolve_project_path(root / target_bib, root)

    existing_entries: list[dict[str, object]] = []
    if target_path.exists():
        if not target_path.is_file():
            raise ValueError(f"bibliography target is not a file: {target_bib}")
        existing_entries = parse_bibtex_entries(target_path.read_text(encoding="utf-8"))

    citations = [
        citation for source in sources for citation in scan_citations(source, root)
    ]
    existing_keys = {str(entry["key"]) for entry in existing_entries}
    missing_keys = sorted(
        {str(citation["key"]) for citation in citations} - existing_keys,
        key=str.casefold,
    )

    if bibliography["system"] == "bibtex" and not bibliography["targets"]:
        commands = ["\\bibliography{references}"]
        if not bibliography["styles"]:
            commands.insert(0, "\\bibliographystyle{aea}")
        tex_changes.append(
            {
                "file": main.relative_to(root).as_posix(),
                "status": "verified",
                "action": "insert-before-end-document",
                "commands": commands,
            }
        )

    digest_paths = list(sources)
    if target_path.is_file():
        digest_paths.append(target_path)
    file_digests = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(set(digest_paths))
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "main_tex": main.relative_to(root).as_posix(),
        "bibliography_system": bibliography["system"],
        "target_bib": target_bib,
        "citations": citations,
        "new_entries": [_empty_entry(key) for key in missing_keys],
        "existing_entry_corrections": [],
        "inferred_references": [],
        "tex_changes": tex_changes,
        "unresolved": [],
        "verification_report": [],
        "warnings": warnings,
        "file_digests": file_digests,
    }


def _require_exact_fields(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{label} schema mismatch; missing={missing}, unknown={unknown}"
        )


def validate_entry(
    entry: object, label: str = "entry", *, correction: bool = False
) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_fields(
        entry, CORRECTION_FIELDS if correction else ENTRY_FIELDS, label
    )
    if correction and not isinstance(entry["before_fields"], dict):
        raise ValueError(f"{label} before_fields must be an object")

    status = entry["status"]
    if status not in STATUSES:
        raise ValueError(f"{label} has unknown status: {status}")
    if not isinstance(entry["citation_key"], str) or not entry["citation_key"].strip():
        raise ValueError(f"{label} requires a citation key")
    fields = entry["fields"]
    if not isinstance(fields, dict):
        raise ValueError(f"{label} fields must be an object")
    if status == "rejected":
        return

    entry_type = entry["entry_type"]
    if entry_type not in SUPPORTED_ENTRY_TYPES:
        raise ValueError(f"{label} has unsupported entry type: {entry_type}")

    alternatives = REQUIRED_ENTRY_FIELDS[str(entry_type)]
    if not any(required <= set(fields) for required in alternatives):
        options = ["+".join(sorted(required)) for required in alternatives]
        raise ValueError(
            f"{label} missing required fields for {entry_type}: " + " or ".join(options)
        )

    if status in {"verified", "approved"}:
        if not entry["verifier"]:
            raise ValueError(f"{label} requires a verifier")
        if not isinstance(entry["sources"], list) or not entry["sources"]:
            raise ValueError(f"{label} requires sources")
    if entry["requires_user_approval"] and not entry["user_approval"]:
        raise ValueError(f"{label} requires user approval")


def _validate_entry_group(
    proposal: dict[str, Any],
    field: str,
    allowed_statuses: set[str],
    *,
    approval_required: bool = False,
) -> list[dict[str, Any]]:
    entries = proposal[field]
    if not isinstance(entries, list):
        raise ValueError(f"{field} must be a list")
    accepted: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        label = f"{field}[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        status = entry.get("status")
        if status not in STATUSES:
            raise ValueError(f"{label} has unknown status: {status}")
        if status not in allowed_statuses:
            raise ValueError(
                f"{label} must be verified, approved, or rejected as applicable"
            )
        validate_entry(entry, label, correction=field == "existing_entry_corrections")
        if status == "rejected":
            continue
        if approval_required and (
            status != "approved"
            or entry.get("requires_user_approval") is not True
            or entry.get("user_approval") is not True
        ):
            kind = "inferred reference" if field == "inferred_references" else label
            raise ValueError(f"{kind} requires user approval")
        accepted.append(entry)
    return accepted


def _entry_for_duplicate_check(entry: dict[str, Any]) -> dict[str, object]:
    return {
        "key": entry["citation_key"],
        "fields": dict(entry["fields"]),
    }


def _validate_duplicates(
    existing: list[dict[str, object]],
    additions: list[dict[str, Any]],
) -> None:
    existing_keys = {str(entry["key"]) for entry in existing}
    addition_keys = [str(entry["citation_key"]) for entry in additions]
    duplicate_keys = sorted(
        existing_keys & set(addition_keys)
        | {key for key in addition_keys if addition_keys.count(key) > 1},
        key=str.casefold,
    )
    if duplicate_keys:
        raise ValueError("duplicate citation keys: " + ", ".join(duplicate_keys))

    messages = find_duplicate_identifiers(
        [*existing, *[_entry_for_duplicate_check(entry) for entry in additions]]
    )
    if messages:
        raise ValueError("; ".join(messages))


def validate_proposal(proposal: object) -> None:
    if not isinstance(proposal, dict):
        raise ValueError("proposal must be an object")
    _require_exact_fields(proposal, PROPOSAL_FIELDS, "proposal")
    if proposal["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version: {proposal['schema_version']}")
    if proposal["bibliography_system"] not in {"bibtex", "biblatex"}:
        raise ValueError("invalid bibliography system")

    root = Path(str(proposal["project_root"])).resolve()
    if not root.is_dir():
        raise ValueError(f"project root does not exist: {root}")
    main, _ = _resolve_project_path(root / str(proposal["main_tex"]), root)
    if not main.is_file():
        raise ValueError("main_tex does not exist")
    target, _ = _resolve_project_path(root / str(proposal["target_bib"]), root)

    file_digests = proposal["file_digests"]
    if not isinstance(file_digests, dict):
        raise ValueError("file_digests must be an object")
    sources = discover_tex_files(main, root)
    detected_bibliography = detect_bibliography(sources, root)
    detected_target, _, _ = _select_target(detected_bibliography)
    if proposal["bibliography_system"] != detected_bibliography["system"]:
        raise ValueError("bibliography system no longer matches scanned sources")
    if proposal["target_bib"] != detected_target:
        raise ValueError("bibliography target no longer matches scanned sources")

    expected_paths = {path.relative_to(root).as_posix() for path in sources}
    target_relative = target.relative_to(root).as_posix()
    if target.is_file():
        expected_paths.add(target_relative)
        if target_relative not in file_digests:
            raise ValueError(f"stale bibliography target: {target_relative}")
    if set(file_digests) != expected_paths:
        raise ValueError(
            "file digest coverage mismatch; "
            f"expected={sorted(expected_paths)}, actual={sorted(file_digests)}"
        )
    for relative_path, expected_digest in file_digests.items():
        path, _ = _resolve_project_path(root / str(relative_path), root)
        if not path.is_file() or sha256_file(path) != expected_digest:
            raise ValueError(f"stale file digest: {relative_path}")

    for field in (
        "citations",
        "tex_changes",
        "unresolved",
        "verification_report",
        "warnings",
    ):
        if not isinstance(proposal[field], list):
            raise ValueError(f"{field} must be a list")
        for index, item in enumerate(proposal[field]):
            if (
                isinstance(item, dict)
                and "status" in item
                and item["status"] not in STATUSES
            ):
                raise ValueError(
                    f"{field}[{index}] has unknown status: {item['status']}"
                )

    new_entries = _validate_entry_group(
        proposal, "new_entries", {"verified", "approved", "rejected"}
    )
    corrections = _validate_entry_group(
        proposal,
        "existing_entry_corrections",
        {"verified", "approved", "rejected"},
        approval_required=True,
    )
    inferred_entries = _validate_entry_group(
        proposal,
        "inferred_references",
        {"verified", "approved", "rejected"},
        approval_required=True,
    )

    existing_entries: list[dict[str, object]] = []
    if target.is_file():
        existing_entries = parse_bibtex_entries(target.read_text(encoding="utf-8"))
    existing_keys = [str(entry["key"]) for entry in existing_entries]
    duplicate_existing_keys = sorted(
        {key for key in existing_keys if existing_keys.count(key) > 1},
        key=str.casefold,
    )
    if duplicate_existing_keys:
        raise ValueError(
            "duplicate citation keys in existing bibliography: "
            + ", ".join(duplicate_existing_keys)
        )
    existing_by_key = {str(entry["key"]): entry for entry in existing_entries}
    correction_keys = [str(entry["citation_key"]) for entry in corrections]
    missing_correction_keys = sorted(set(correction_keys) - set(existing_by_key))
    if missing_correction_keys:
        raise ValueError(
            "corrections reference missing citation keys: "
            + ", ".join(missing_correction_keys)
        )
    if len(correction_keys) != len(set(correction_keys)):
        raise ValueError("duplicate correction citation keys")
    for correction in corrections:
        existing_by_key[str(correction["citation_key"])] = _entry_for_duplicate_check(
            correction
        )
    _validate_duplicates(
        list(existing_by_key.values()), [*new_entries, *inferred_entries]
    )


def render_entry(entry: dict[str, Any]) -> str:
    fields = {str(key): str(value) for key, value in entry["fields"].items()}
    fields["title"] = headline_title(fields["title"])
    lines = [f"@{entry['entry_type']}{{{entry['citation_key']},"]
    names = sorted(fields, key=str.casefold)
    for index, name in enumerate(names):
        suffix = "," if index < len(names) - 1 else ""
        lines.append(f"  {name} = {{{fields[name]}}}{suffix}")
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


def _accepted_entries(
    proposal: dict[str, Any], field: str
) -> list[dict[str, Any]]:
    return [
        entry
        for entry in proposal[field]
        if entry["status"] in {"verified", "approved"}
    ]


def prepare_tex_changes(
    proposal: dict[str, Any], root: Path
) -> list[tuple[Path, str]]:
    changes = proposal["tex_changes"]
    if not changes:
        return []
    if proposal["bibliography_system"] != "bibtex":
        raise ValueError("cannot apply BibTeX commands to a biblatex project")
    if len(changes) != 1:
        raise ValueError("expected at most one TeX bibliography change")

    change = changes[0]
    expected_fields = {"file", "status", "action", "commands"}
    if not isinstance(change, dict) or set(change) != expected_fields:
        raise ValueError("invalid TeX change schema")
    if change["status"] != "verified":
        raise ValueError("TeX change must be verified")
    if change["action"] != "insert-before-end-document":
        raise ValueError("unsupported TeX change action")
    if change["file"] != proposal["main_tex"]:
        raise ValueError("TeX change must target the main document")
    commands = change["commands"]
    if not isinstance(commands, list) or not all(
        isinstance(command, str) for command in commands
    ):
        raise ValueError("TeX change commands must be strings")

    source, _ = _resolve_project_path(root / str(change["file"]), root)
    sources = discover_tex_files(source, root)
    config = detect_bibliography(sources, root)
    expected_commands = ["\\bibliography{references}"]
    if not config["styles"]:
        expected_commands.insert(0, "\\bibliographystyle{aea}")
    if config["targets"] or commands != expected_commands:
        raise ValueError("bibliography configuration changed since scan")

    text = source.read_text(encoding="utf-8")
    marker = "\\end{document}"
    marker_index = text.rfind(marker)
    if marker_index < 0:
        raise ValueError(f"missing {marker} in {change['file']}")
    prefix = text[:marker_index]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    replacement = prefix + "\n".join(commands) + "\n" + text[marker_index:]
    return [(source, replacement)]


def apply_proposal(proposal: dict[str, Any]) -> dict[str, object]:
    validate_proposal(proposal)
    root = Path(str(proposal["project_root"])).resolve()
    prepared_tex = prepare_tex_changes(proposal, root)
    target, _ = _resolve_project_path(root / str(proposal["target_bib"]), root)
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    parsed = parse_bibtex_entries(text)
    existing_by_key = {str(entry["key"]): entry for entry in parsed}

    corrections = _accepted_entries(proposal, "existing_entry_corrections")
    for correction in corrections:
        current = existing_by_key[str(correction["citation_key"])]
        if correction["before_fields"] != current["fields"]:
            raise ValueError(
                f"{correction['citation_key']} before_fields do not match"
            )
    for correction in sorted(
        corrections,
        key=lambda item: int(existing_by_key[str(item["citation_key"])]["start"]),
        reverse=True,
    ):
        current = existing_by_key[str(correction["citation_key"])]
        start = int(current["start"])
        end = int(current["end"])
        text = text[:start] + render_entry(correction) + text[end + 1 :]

    additions = [
        *_accepted_entries(proposal, "new_entries"),
        *_accepted_entries(proposal, "inferred_references"),
    ]
    if additions:
        if text and not text.endswith("\n"):
            separator = "\n\n"
        elif text and not text.endswith("\n\n"):
            separator = "\n"
        else:
            separator = ""
        text += separator + "\n\n".join(render_entry(entry) for entry in additions)
        text += "\n"

    atomic_write(target, text)
    for source, replacement in prepared_tex:
        atomic_write(source, replacement)
    applied = [*corrections, *additions]
    rejected = [
        entry
        for field in (
            "new_entries",
            "existing_entry_corrections",
            "inferred_references",
        )
        for entry in proposal[field]
        if entry["status"] == "rejected"
    ]
    result: dict[str, object] = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "applied": [entry["citation_key"] for entry in applied],
        "applied_entries": [
            {
                "citation_key": entry["citation_key"],
                "sources": entry["sources"],
                "verifier": entry["verifier"],
            }
            for entry in applied
        ],
        "skipped": [entry["citation_key"] for entry in rejected],
        "unresolved": proposal["unresolved"],
        "verification_report": proposal["verification_report"],
        "changed_tex": [
            source.relative_to(root).as_posix() for source, _ in prepared_tex
        ],
    }
    atomic_write(
        root / "bibliography-apply-result.json",
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan, validate, and update a LaTeX bibliography."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--project", type=Path, required=True)
    scan_parser.add_argument("--output", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--proposal", type=Path, required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--proposal", type=Path, required=True)

    install_parser = subparsers.add_parser("install-aea-style")
    install_parser.add_argument("--project", type=Path, required=True)
    install_parser.add_argument("--confirm-download", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install-aea-style" and not args.confirm_download:
        raise SystemExit("--confirm-download is required")
    if args.command == "scan":
        proposal = build_scan_proposal(args.project)
        args.output.write_text(
            json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif args.command == "validate":
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        validate_proposal(proposal)
    elif args.command == "apply":
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        apply_proposal(proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
