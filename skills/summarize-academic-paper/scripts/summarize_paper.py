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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
