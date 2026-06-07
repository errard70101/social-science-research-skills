#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

TARGET_PATHS = {
    "antigravity": Path(".gemini/antigravity/skills"),
    "claude": Path(".claude/skills"),
    "codex": Path(".agents/skills"),
    "opencode": Path(".agents/skills"),
    "copilot": Path(".agents/skills"),
}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path} is missing YAML frontmatter")
    values = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def validate_skill(skill: Path) -> None:
    skill_file = skill / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{skill} does not contain SKILL.md")
    metadata = parse_frontmatter(skill_file)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if name != skill.name:
        raise ValueError("SKILL.md name must match the skill directory")
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("skill name must be lowercase hyphen-case")
    if not description:
        raise ValueError("SKILL.md description is required")


def resolve_destinations(targets: list[str], *, home: Path) -> list[Path]:
    resolved = []
    seen = set()
    for target in targets:
        destination = (home / TARGET_PATHS[target]).resolve()
        if destination not in seen:
            resolved.append(destination)
            seen.add(destination)
    return resolved


def install_skill(
    skill: Path,
    destination: Path,
    *,
    link: bool,
    dry_run: bool,
) -> None:
    validate_skill(skill)
    target = destination / skill.name
    action = "link" if link else "copy"
    print(f"{action}: {skill} -> {target}")
    if dry_run:
        return
    destination.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    if link:
        target.symlink_to(skill.resolve(), target_is_directory=True)
    else:
        shutil.copytree(skill, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install portable research skills.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--skill", action="append")
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGET_PATHS),
        help="Install only for the selected client; repeatable.",
    )
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--link", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    skills_root = repo_root / "skills"
    if args.all:
        skills = sorted(path for path in skills_root.iterdir() if path.is_dir())
    else:
        skills = [skills_root / name for name in args.skill]
    for skill in skills:
        validate_skill(skill)
    if args.destination:
        destinations = [args.destination.expanduser().resolve()]
    else:
        targets = args.target or list(TARGET_PATHS)
        destinations = resolve_destinations(targets, home=Path.home())
    for destination in destinations:
        for skill in skills:
            install_skill(
                skill,
                destination,
                link=args.link,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
