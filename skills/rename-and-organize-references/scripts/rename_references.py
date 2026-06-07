#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from pypdf import PdfReader

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
KIND_SUFFIXES = {
    "main-paper": "",
    "appendix": "_Appendix",
    "slides": "_Slides",
    "replication": "_Replication",
}
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


class MetadataProvider(Protocol):
    def lookup_doi(self, doi: str) -> dict[str, Any] | None: ...

    def search_title(self, title: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ResolutionResult:
    metadata: dict[str, Any]
    confidence: str
    provenance: str


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
        has_inferred_author = False
        has_unresolved_author = False
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            display_name = str(author.get("display_name") or "")
            structured_family = str(author.get("family_name") or "").strip()
            author_metadata = {
                "display_name": display_name,
                "family_name": structured_family,
            }
            if not structured_family:
                raw_name = str(authorship.get("raw_author_name") or display_name)
                inferred_family = _infer_author_family_name(raw_name)
                if inferred_family:
                    author_metadata["family_name"] = inferred_family
                    author_metadata["family_name_inferred"] = True
                    has_inferred_author = True
                else:
                    has_unresolved_author = True
            authors.append(author_metadata)
        if has_unresolved_author:
            metadata_quality = "unresolved-author-names"
        elif has_inferred_author:
            metadata_quality = "inferred-author-names"
        else:
            metadata_quality = "structured-author-names"
        metadata = {
            "title": work.get("title"),
            "year": work.get("publication_year"),
            "authors": authors,
            "doi": normalize_doi(str(work.get("doi") or "")),
            "source": "openalex",
        }
        if metadata_quality != "structured-author-names":
            metadata["metadata_quality"] = metadata_quality
            metadata["requires_review"] = True
        return metadata

    def lookup_doi(self, doi: str) -> dict[str, Any] | None:
        encoded = urllib.parse.quote(doi, safe="")
        return self._metadata(
            self._request(f"{self.base_url}/https://doi.org/{encoded}")
        )

    def search_title(self, title: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"search": title, "per-page": 1})
        results = self._request(f"{self.base_url}?{query}").get("results", [])
        return self._metadata(results[0]) if results else None


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


def _infer_author_family_name(value: str) -> str:
    comma_parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(comma_parts) == 2 and not _is_name_suffix(comma_parts[1]):
        return comma_parts[0]
    tokens = value.split()
    if len(tokens) == 2 and not _is_name_suffix(tokens[-1]):
        return tokens[-1]
    return ""


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
    author_entries = metadata.get("authors", [])
    authors = format_authors(author_entries)
    year_value = metadata.get("year")
    title = clean_title(str(metadata.get("title") or ""))
    if not authors or year_value is None or year_value == "":
        raise ValueError("authors and year are required to generate a filename")
    if any(not family_name(author) for author in author_entries):
        raise ValueError("all authors must have a resolvable family name")
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


def read_pdf_candidate(path: Path) -> dict[str, Any]:
    reader = PdfReader(path)
    text = "\n".join(
        page.extract_text() or "" for page in reader.pages[: min(3, len(reader.pages))]
    )
    doi_match = DOI_PATTERN.search(text)
    metadata = reader.metadata
    candidate = {
        "doi": normalize_doi(doi_match.group(0)) if doi_match else "",
        "title": str(getattr(metadata, "title", "") or ""),
        "authors": _parse_pdf_authors(str(getattr(metadata, "author", "") or "")),
        "source": "pdf-metadata",
    }
    year = _pdf_metadata_year(metadata)
    if year is not None:
        candidate["year"] = year
    return candidate


def _parse_pdf_authors(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    authors = []
    for display_name in (part.strip() for part in value.split(";")):
        parts = [part.strip() for part in display_name.split(",")]
        if len(parts) != 2 or not all(parts):
            return []
        family = ascii_token(parts[0])
        if not family:
            return []
        authors.append({"display_name": display_name, "family_name": parts[0]})
    return authors


def _pdf_metadata_year(metadata: Any) -> int | None:
    candidates = [getattr(metadata, "year", None)]
    if isinstance(metadata, Mapping):
        candidates.extend([metadata.get("/Year"), metadata.get("Year")])
    for value in candidates:
        if isinstance(value, str) and re.fullmatch(r"[0-9]{4}", value.strip()):
            return int(value)
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return int(normalize_year(value))
            except ValueError:
                continue
    return None


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
    if candidate_stem == main_stem:
        return True
    if not candidate_stem.startswith(main_stem):
        return False
    return candidate_stem[len(main_stem)] in {"_", "-", ".", " "}


def _has_required_metadata(metadata: Mapping[str, Any]) -> bool:
    try:
        build_filename(metadata, kind="main-paper")
    except (TypeError, ValueError):
        return False
    return True


def resolve_metadata(
    path: Path,
    *,
    provider: MetadataProvider | None,
    threshold: float = 0.9,
) -> ResolutionResult | None:
    try:
        local = read_pdf_candidate(path)
    except Exception:
        local = {}
    if _has_required_metadata(local):
        return ResolutionResult(dict(local), "review", "pdf-metadata")
    if provider and local.get("doi"):
        try:
            metadata = provider.lookup_doi(str(local["doi"]))
        except Exception:
            metadata = None
        if metadata and _has_required_metadata(metadata):
            confidence = "review" if metadata.get("requires_review") else "high"
            return ResolutionResult(dict(metadata), confidence, "doi-lookup")
    query = str(local.get("title") or path.stem.replace("_", " "))
    if provider and query:
        try:
            candidate = provider.search_title(query)
        except Exception:
            candidate = None
        if (
            candidate
            and accept_title_match(query, candidate, threshold=threshold)
            and _has_required_metadata(candidate)
        ):
            return ResolutionResult(dict(candidate), "review", "title-search")
    return None


def propose(
    directory: Path,
    output: Path,
    *,
    provider: MetadataProvider | None,
) -> dict[str, Any]:
    root = directory.resolve()
    output_path = output.resolve()
    items = []
    unresolved = []
    entries = sorted(root.iterdir())
    main_papers = [
        path
        for path in entries
        if path.resolve() != output_path
        and path.is_file()
        and path.suffix.casefold() == ".pdf"
        and classify_related(path) is None
    ]
    related_owners: dict[Path, Path] = {}
    for candidate in entries:
        if classify_related(candidate) is None:
            continue
        matching_mains = [
            main for main in main_papers if related_to(main, candidate)
        ]
        if matching_mains:
            related_owners[candidate] = max(
                matching_mains,
                key=lambda main: len(main.stem),
            )
    claimed: set[Path] = set()
    for path in main_papers:
        claimed.add(path)
        resolution = resolve_metadata(path, provider=provider)
        if not resolution:
            unresolved.append(
                {
                    "source": path.name,
                    "reason": "required metadata could not be resolved",
                }
            )
            continue
        metadata = resolution.metadata
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
                "confidence": resolution.confidence,
                "provenance": resolution.provenance,
                "metadata": metadata,
            }
        )
        for candidate in entries:
            kind = classify_related(candidate)
            if (
                candidate in claimed
                or kind is None
                or related_owners.get(candidate) != path
            ):
                continue
            try:
                related_destination = build_filename(metadata, kind=kind)
            except ValueError as error:
                unresolved.append({"source": candidate.name, "reason": str(error)})
                claimed.add(candidate)
                continue
            items.append(
                {
                    "source": candidate.name,
                    "destination": related_destination,
                    "kind": kind,
                    "confidence": resolution.confidence,
                    "provenance": resolution.provenance,
                    "metadata": metadata,
                }
            )
            claimed.add(candidate)
    for path in entries:
        if path in claimed or path.resolve() == output_path:
            continue
        is_pdf = path.is_file() and path.suffix.casefold() == ".pdf"
        if is_pdf or classify_related(path):
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


def contained_path(root: Path, relative: str) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or relative_path == Path(".")
        or ".." in relative_path.parts
    ):
        return None
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / relative_path).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def validate_mapping(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, Mapping):
        return ["mapping must be an object"]

    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        errors.append("schema_version must equal 1")

    root_value = data.get("root")
    if not isinstance(root_value, str) or not root_value.strip():
        errors.append("root must be a nonempty string")
        return errors
    try:
        root = Path(root_value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        errors.append(f"root is invalid: {root_value}")
        return errors
    try:
        root_is_dir = root.is_dir()
    except (OSError, ValueError):
        root_is_dir = False
    if not root_is_dir:
        errors.append(f"root is not a directory: {root}")

    unresolved = data.get("unresolved", [])
    if unresolved != []:
        errors.append("mapping contains unresolved items")

    items = data.get("items")
    if not isinstance(items, list):
        errors.append("items must be a list")
        return errors

    sources: set[Path] = set()
    destinations: set[Path] = set()
    valid_items: list[tuple[int, Mapping[str, Any], Path, Path]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"item {index} must be an object")
            continue

        if item.get("confidence") != "high":
            errors.append(f"item {index} confidence must be high")
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in KIND_SUFFIXES:
            errors.append(f"item {index} has unsupported kind: {kind}")

        source_value = item.get("source")
        destination_value = item.get("destination")
        source = (
            contained_path(root, source_value)
            if isinstance(source_value, str)
            else None
        )
        destination = (
            contained_path(root, destination_value)
            if isinstance(destination_value, str)
            else None
        )
        if source is None:
            errors.append(f"item {index} source must be a nonempty path within root")
        if destination is None:
            errors.append(
                f"item {index} destination must be a nonempty path within root"
            )
        if source is None or destination is None:
            continue

        if source == destination:
            errors.append(f"item {index} source and destination must differ")
        if source in sources:
            errors.append(f"duplicate source: {source_value}")
        if destination in destinations:
            errors.append(f"duplicate destination: {destination_value}")
        sources.add(source)
        destinations.add(destination)
        valid_items.append((index, item, source, destination))

        if not source.exists():
            errors.append(f"source does not exist: {source_value}")

    for _, item, _, destination in valid_items:
        if destination in sources:
            errors.append(
                f"destination is another source: {item.get('destination')}"
            )
        elif destination.exists():
            errors.append(
                f"destination already exists: {item.get('destination')}"
            )

    for _, item, source, _ in valid_items:
        if not source.is_dir():
            continue
        for _, _, _, destination in valid_items:
            if source == destination:
                continue
            try:
                destination.relative_to(source)
            except ValueError:
                continue
            errors.append(
                f"directory destination overlaps source: {item.get('source')}"
            )

    return errors


def load_mapping(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Propose, validate, and apply academic reference renames."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    propose_parser = subparsers.add_parser("propose")
    propose_parser.add_argument("--directory", required=True, type=Path)
    propose_parser.add_argument("--output", required=True, type=Path)
    propose_parser.add_argument(
        "--offline",
        action="store_true",
        help="Disable OpenAlex metadata lookups.",
    )
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--mapping", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "propose":
        provider = None if args.offline else OpenAlexProvider()
        propose(args.directory, args.output, provider=provider)
    if args.command == "validate":
        try:
            data = load_mapping(args.mapping)
        except (OSError, json.JSONDecodeError) as error:
            print(f"ERROR: unable to load mapping: {error}", file=sys.stderr)
            return 1
        errors = validate_mapping(data)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("Mapping is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
