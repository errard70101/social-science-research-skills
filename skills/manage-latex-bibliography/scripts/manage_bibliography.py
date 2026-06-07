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
