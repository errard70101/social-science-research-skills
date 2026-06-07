#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.parse
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FETCH_ARTIFACT_NAME = "summarize-paper-fetch.json"
EXTRACT_ARTIFACT_NAME = "summarize-paper-extract.json"

ARXIV_ABS_PATTERN = re.compile(
    r"^https?://arxiv\.org/abs/(?P<id>[\w./-]+?)(?:v\d+)?/?$"
)
NBER_PAPER_PATTERN = re.compile(
    r"^https?://(?:www\.)?nber\.org/papers/(?P<id>w?\d+)/?$"
)
CITATION_PDF_META = re.compile(
    r"<meta\b(?=[^>]*\bname=[\"']citation_pdf_url[\"'])"
    r"[^>]*\bcontent=[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE,
)
DOI_PATTERN = re.compile(
    r"^(?:doi:)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)$", re.IGNORECASE
)
CAPTION_PATTERN = re.compile(
    r"^(?P<kind>Table|Figure)\s+(?P<number>[A-Za-z0-9]+)"
    r"[\.:—\-]\s*(?P<caption>.+?)$",
    re.IGNORECASE,
)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@contextmanager
def _default_http_client():
    import httpx

    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": "social-science-research-skills/0.1"},
        timeout=30.0,
    ) as client:
        yield client


def _safe_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name or "download.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for counter in range(1, 1000):
        attempt = directory / f"{stem}-{counter}{suffix}"
        if not attempt.exists():
            return attempt
    raise RuntimeError(f"could not find a free filename for {filename}")


def _rewrite_known_url(url: str) -> tuple[str, str | None]:
    match = ARXIV_ABS_PATTERN.match(url)
    if match:
        return (
            f"https://arxiv.org/pdf/{match.group('id')}.pdf",
            "arxiv",
        )
    match = NBER_PAPER_PATTERN.match(url)
    if match:
        identifier = match.group("id")
        return (
            f"https://www.nber.org/papers/{identifier}.pdf",
            "nber",
        )
    return url, None


def _is_pdf_response(response) -> bool:
    return (
        response.headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
        == "application/pdf"
    )


def _save_pdf_bytes(
    output_dir: Path, source_url: str, content: bytes
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_path(
        output_dir, _safe_filename_from_url(source_url)
    )
    destination.write_bytes(content)
    return destination


def _resolve_url(
    url: str,
    output_dir: Path,
    http_client_factory: Callable[[], Any],
) -> dict[str, Any]:
    rewritten, hop = _rewrite_known_url(url)
    resolution_path = ["url"]
    if hop:
        resolution_path.append(hop)

    with http_client_factory() as client:
        response = client.get(rewritten)
        if _is_pdf_response(response):
            saved = _save_pdf_bytes(output_dir, rewritten, response.content)
            return {
                "pdf_path": str(saved.resolve()),
                "resolution_path": resolution_path,
                "source_url": rewritten,
                "retrieved_at": _utc_now_iso(),
                "sha256": _sha256_bytes(response.content),
                "unresolved": None,
            }
        meta_match = CITATION_PDF_META.search(
            response.content.decode("utf-8", errors="replace")
        )
        if meta_match:
            pdf_url = meta_match.group("url")
            pdf_response = client.get(pdf_url)
            if _is_pdf_response(pdf_response):
                saved = _save_pdf_bytes(
                    output_dir, pdf_url, pdf_response.content
                )
                return {
                    "pdf_path": str(saved.resolve()),
                    "resolution_path": resolution_path
                    + ["citation-pdf-meta"],
                    "source_url": pdf_url,
                    "retrieved_at": _utc_now_iso(),
                    "sha256": _sha256_bytes(pdf_response.content),
                    "unresolved": None,
                }
    return {
        "pdf_path": None,
        "resolution_path": resolution_path,
        "source_url": rewritten,
        "retrieved_at": _utc_now_iso(),
        "sha256": None,
        "unresolved": (
            "response content-type is not application/pdf and no "
            "citation_pdf_url meta tag was present"
        ),
    }


def _looks_like_doi(value: str) -> bool:
    return bool(DOI_PATTERN.match(value.strip()))


def _normalize_doi(value: str) -> str:
    match = DOI_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"not a valid DOI: {value}")
    return match.group(1).lower()


def _resolve_via_unpaywall(
    doi: str, client, output_dir: Path
) -> dict[str, Any] | None:
    email = os.environ.get("UNPAYWALL_EMAIL")
    if not email:
        return None
    response = client.get(
        f"https://api.unpaywall.org/v2/{doi}?email={email}"
    )
    if response.status_code >= 400:
        return None
    payload = response.json()
    best = payload.get("best_oa_location") or {}
    pdf_url = best.get("url_for_pdf")
    if not pdf_url:
        return None
    pdf_response = client.get(pdf_url)
    if not _is_pdf_response(pdf_response):
        return None
    saved = _save_pdf_bytes(output_dir, pdf_url, pdf_response.content)
    return {
        "pdf_path": str(saved.resolve()),
        "source_url": pdf_url,
        "sha256": _sha256_bytes(pdf_response.content),
    }


def _resolve_doi(
    doi: str,
    output_dir: Path,
    http_client_factory: Callable[[], Any],
) -> dict[str, Any]:
    normalized = _normalize_doi(doi)
    doi_url = f"https://doi.org/{normalized}"
    with http_client_factory() as client:
        response = client.get(doi_url)
        if _is_pdf_response(response):
            saved = _save_pdf_bytes(
                output_dir, doi_url, response.content
            )
            return {
                "pdf_path": str(saved.resolve()),
                "resolution_path": ["doi"],
                "source_url": doi_url,
                "retrieved_at": _utc_now_iso(),
                "sha256": _sha256_bytes(response.content),
                "unresolved": None,
            }
        upgrade = _resolve_via_unpaywall(normalized, client, output_dir)
        if upgrade:
            return {
                "pdf_path": upgrade["pdf_path"],
                "resolution_path": ["doi", "unpaywall"],
                "source_url": upgrade["source_url"],
                "retrieved_at": _utc_now_iso(),
                "sha256": upgrade["sha256"],
                "unresolved": None,
            }
    if os.environ.get("UNPAYWALL_EMAIL"):
        message = (
            "DOI did not resolve to an open-access PDF and Unpaywall "
            "did not find one"
        )
    else:
        message = (
            "DOI resolved to a non-PDF response and UNPAYWALL_EMAIL is "
            "not set; cannot consult Unpaywall"
        )
    return {
        "pdf_path": None,
        "resolution_path": ["doi"],
        "source_url": doi_url,
        "retrieved_at": _utc_now_iso(),
        "sha256": None,
        "unresolved": message,
    }


def resolve_input(
    input_value: str,
    output_dir: Path,
    http_client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    candidate = Path(input_value).expanduser()
    if candidate.is_file() and candidate.suffix.lower() == ".pdf":
        resolved = candidate.resolve()
        return {
            "pdf_path": str(resolved),
            "resolution_path": ["local"],
            "source_url": None,
            "retrieved_at": _utc_now_iso(),
            "sha256": _sha256_file(resolved),
            "unresolved": None,
        }
    if input_value.startswith(("http://", "https://")):
        return _resolve_url(
            input_value,
            output_dir,
            http_client_factory or _default_http_client,
        )
    if _looks_like_doi(input_value):
        return _resolve_doi(
            input_value,
            output_dir,
            http_client_factory or _default_http_client,
        )
    return {
        "pdf_path": None,
        "resolution_path": [],
        "source_url": None,
        "retrieved_at": _utc_now_iso(),
        "sha256": None,
        "unresolved": (
            f"input is neither a local PDF, a URL, nor a DOI: {input_value!r}"
        ),
    }


def fetch(input_value: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = resolve_input(input_value, output_dir)
    artifact = {"schema_version": 1, "input": input_value, **payload}
    (output_dir / FETCH_ARTIFACT_NAME).write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def _default_reader_factory(pdf_path: Path):
    from pypdf import PdfReader

    return PdfReader(str(pdf_path))


def _extract_pages(reader) -> list[dict[str, Any]]:
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - pypdf raises varied errors per page; keep going
            text = ""
        pages.append({"page": index, "text": text})
    return pages


AUTHOR_SPLIT_PATTERN = re.compile(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*")
TITLE_NOISE_PREFIXES = ("abstract", "draft", "preliminary", "comments")


def _candidate_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped:
            current.append(stripped)
            continue
        if current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def guess_title(first_page_text: str) -> str | None:
    for block in _candidate_blocks(first_page_text):
        lower = block.lower()
        if lower.startswith(TITLE_NOISE_PREFIXES):
            continue
        if len(block) < 6 or len(block.split()) < 2:
            continue
        if block[0].islower():
            continue
        return block
    return None


def _looks_like_author_block(block: str) -> bool:
    if not block or any(ch.isdigit() for ch in block):
        return False
    parts = [part.strip() for part in AUTHOR_SPLIT_PATTERN.split(block)]
    parts = [part for part in parts if part]
    if not parts:
        return False
    for part in parts:
        words = part.split()
        if len(words) < 2 or len(words) > 5:
            return False
        if not words[0][0].isupper() or not words[-1][0].isupper():
            return False
    return True


def guess_authors(first_page_text: str) -> list[str]:
    blocks = _candidate_blocks(first_page_text)
    if not blocks:
        return []
    for block in blocks[1:5]:
        if _looks_like_author_block(block):
            return [
                part.strip()
                for part in AUTHOR_SPLIT_PATTERN.split(block)
                if part.strip()
            ]
    return []


def _extract_embedded_metadata(reader) -> dict[str, str]:
    metadata = getattr(reader, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return {
            str(key): str(value)
            for key, value in metadata.items()
        }
    return {str(key): str(value) for key, value in metadata.items()}


def collect_caption_candidates(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        for line in page.get("text", "").splitlines():
            stripped = line.strip()
            match = CAPTION_PATTERN.match(stripped)
            if not match:
                continue
            kind = match.group("kind").lower()
            number = match.group("number")
            label = f"{kind.capitalize()} {number}"
            caption = match.group("caption").strip()
            candidates.append(
                {
                    "label": label,
                    "caption": caption,
                    "page": page["page"],
                    "kind": kind,
                }
            )
    return candidates


def extract(
    fetch_path: Path,
    output_path: Path,
    reader_factory: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    fetch_artifact = json.loads(fetch_path.read_text(encoding="utf-8"))
    if fetch_artifact.get("unresolved"):
        raise ValueError(
            "fetch artifact is unresolved; cannot extract: "
            f"{fetch_artifact['unresolved']}"
        )
    pdf_path = Path(fetch_artifact["pdf_path"])
    reader = (reader_factory or _default_reader_factory)(pdf_path)
    pages = _extract_pages(reader)
    metadata = _extract_embedded_metadata(reader)
    first_page_text = pages[0]["text"] if pages else ""
    title_guess = guess_title(first_page_text) or metadata.get("/Title")
    author_guesses = guess_authors(first_page_text)
    warnings: list[str] = []
    if not any(page["text"].strip() for page in pages):
        warnings.append("no-extractable-text")
    if not author_guesses:
        warnings.append("author-guess-empty")
    artifact = {
        "schema_version": 1,
        "pdf_path": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "embedded_metadata": metadata,
        "title_guess": title_guess,
        "author_guesses": author_guesses,
        "table_candidates": collect_caption_candidates(pages),
        "warnings": warnings,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Turn an economics paper into a two-page LaTeX summary "
            "via a fetch | extract | render pipeline."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output-dir", type=Path, required=True)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--fetch", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--extract", type=Path, required=True)
    render.add_argument("--content", type=Path, required=True)
    render.add_argument("--output-tex", type=Path, required=True)
    render.add_argument("--include-table", default=None)
    render.add_argument("--include-figure", default=None)
    render.add_argument("--reproduce-tables", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        fetch(input_value=args.input, output_dir=args.output_dir)
    elif args.command == "extract":
        extract(fetch_path=args.fetch, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
