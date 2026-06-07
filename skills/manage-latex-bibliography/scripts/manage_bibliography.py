#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

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
BIBLATEX_PACKAGE_RE = re.compile(r"\\usepackage(?:\s*\[[^\]]*\])?\s*\{\s*biblatex\s*\}")
ADD_BIB_RESOURCE_RE = re.compile(r"\\addbibresource(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}")
BIBTEX_ENTRY_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_-]*)\s*([({])")
DOI_PREFIX_RE = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE
)


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

        if BIBLATEX_PACKAGE_RE.search(uncommented):
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


def parse_bibtex_entries(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    search_start = 0

    while match := BIBTEX_ENTRY_RE.search(text, search_start):
        entry_start = match.start()
        opener = match.group(2)
        opener_index = match.end() - 1
        entry_end = _find_entry_end(text, opener_index, opener)
        parts = _split_bibtex_parts(text[opener_index + 1 : entry_end])
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
        search_start = entry_end + 1

    return entries


def normalize_doi(value: str) -> str:
    normalized = DOI_PREFIX_RE.sub("", value.strip())
    return normalized.rstrip(".,;:)]}").strip().lower()


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
            normalized_isbn = str(isbn).strip().lower().replace("-", "")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
