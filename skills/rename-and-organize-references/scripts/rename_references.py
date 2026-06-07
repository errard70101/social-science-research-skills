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
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


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
    comma_parts = [part.strip() for part in display.split(",") if part.strip()]
    if len(comma_parts) > 1:
        if any(_is_name_suffix(part) for part in comma_parts[1:]):
            return ""
        return ascii_token(comma_parts[0])
    tokens = display.split()
    if not tokens or _is_name_suffix(tokens[-1]):
        return ""
    return ascii_token(tokens[-1])


def _is_name_suffix(value: str) -> bool:
    return ascii_token(value, allow_hyphen=False).lower() in NAME_SUFFIXES


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


def normalize_year(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("year must be a four-digit integer")
    if isinstance(value, int):
        candidate = str(value)
    elif isinstance(value, str):
        candidate = value.strip()
    else:
        raise ValueError("year must be a four-digit integer")
    if re.fullmatch(r"[0-9]{4}", candidate) is None or int(candidate) < 1000:
        raise ValueError("year must be a four-digit integer")
    return candidate


def truncate_stem(
    title: str,
    suffix: str,
    extension: str,
    max_length: int,
    *,
    preserved_prefix: str = "",
) -> str:
    available = max_length - len(preserved_prefix) - len(suffix) - len(extension)
    if available < 1:
        raise ValueError("max_length leaves no room for a nonempty title")
    truncated_title = title[:available].rstrip("_-")
    if not truncated_title:
        raise ValueError("max_length leaves no room for a nonempty title")
    return preserved_prefix + truncated_title + suffix + extension


def build_filename(
    metadata: Mapping[str, Any],
    *,
    kind: str,
    max_length: int = 180,
) -> str:
    authors = format_authors(metadata.get("authors", []))
    year_value = metadata.get("year")
    title = clean_title(str(metadata.get("title") or ""))
    if not authors or year_value is None or year_value == "":
        raise ValueError("authors and year are required to generate a filename")
    year = normalize_year(year_value)
    if not title:
        raise ValueError("title is required to generate a filename")
    if kind not in KIND_SUFFIXES:
        raise ValueError(f"unsupported item kind: {kind}")
    extension = "" if kind == "replication" else ".pdf"
    preserved_prefix = f"{authors}_{year}_"
    return truncate_stem(
        title,
        KIND_SUFFIXES[kind],
        extension,
        max_length,
        preserved_prefix=preserved_prefix,
    )


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
