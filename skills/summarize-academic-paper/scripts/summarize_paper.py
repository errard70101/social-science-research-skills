#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FETCH_ARTIFACT_NAME = "summarize-paper-fetch.json"


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


def resolve_input(
    input_value: str,
    output_dir: Path,
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
    raise NotImplementedError("non-local resolution not yet implemented")


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
