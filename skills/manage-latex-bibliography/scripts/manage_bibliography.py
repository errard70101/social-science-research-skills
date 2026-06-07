#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


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
