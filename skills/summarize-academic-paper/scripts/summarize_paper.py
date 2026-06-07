#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


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
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
