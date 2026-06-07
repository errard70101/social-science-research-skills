#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
