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


def discover_skills(skills_root: Path | None = None) -> list[str]:
    """Discover all skill directory names under skills/ directory.

    Args:
        skills_root: Path to the skills directory. Defaults to repo_root/skills.

    Returns:
        Sorted list of skill directory names.
    """
    if skills_root is None:
        skills_root = Path(__file__).resolve().parents[1] / "skills"
    return sorted(path.name for path in skills_root.iterdir() if path.is_dir())


def _parse_frontmatter_value(raw: str) -> str | list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",")]
    return raw.strip('"')


def parse_frontmatter(path: Path) -> dict[str, str | list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path} is missing YAML frontmatter")
    values: dict[str, str | list[str]] = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = _parse_frontmatter_value(value)
    return values


def validate_skill(skill: Path) -> None:
    skill_file = skill / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{skill} does not contain SKILL.md")
    metadata = parse_frontmatter(skill_file)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if not isinstance(name, str) or name != skill.name:
        raise ValueError("SKILL.md name must match the skill directory")
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("skill name must be lowercase hyphen-case")
    if not isinstance(description, str) or not description:
        raise ValueError("SKILL.md description is required")


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def skill_requires(skill: Path) -> list[str]:
    """Return the `requires:` list from a skill's frontmatter, or []."""
    return _as_list(parse_frontmatter(skill / "SKILL.md").get("requires"))


def skill_capabilities(skill: Path) -> list[str]:
    """Return the `capabilities:` list from a skill's frontmatter, or []."""
    return _as_list(parse_frontmatter(skill / "SKILL.md").get("capabilities"))


def discover_capabilities(skills_root: Path) -> dict[str, list[str]]:
    """Map capability name -> sorted list of skills that provide it."""
    providers: dict[str, list[str]] = {}
    for path in sorted(skills_root.iterdir()):
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            continue
        for capability in skill_capabilities(path):
            providers.setdefault(capability, []).append(path.name)
    for capability in providers:
        providers[capability].sort()
    return providers


def resolve_dependencies(
    selected: list[Path],
    skills_root: Path,
) -> tuple[list[Path], list[str]]:
    """Expand `selected` with required skills and capability providers.

    Returns (expanded_skill_paths, warnings). Missing capability providers
    produce warnings rather than errors (graceful degradation).
    """
    by_name = {p.name: p for p in skills_root.iterdir() if p.is_dir()}
    providers = discover_capabilities(skills_root)
    expanded: dict[str, Path] = {p.name: p for p in selected}
    warnings: list[str] = []
    queue: list[Path] = list(selected)

    while queue:
        current = queue.pop()
        for requirement in skill_requires(current):
            if requirement in by_name and requirement not in expanded:
                expanded[requirement] = by_name[requirement]
                queue.append(by_name[requirement])
                continue
            if requirement in providers:
                if any(name in expanded for name in providers[requirement]):
                    continue
                provider_name = providers[requirement][0]
                expanded[provider_name] = by_name[provider_name]
                queue.append(by_name[provider_name])
                continue
            warnings.append(
                f"{current.name} requires '{requirement}' but no installed "
                "skill or capability provider was found; the parent skill "
                "will run in graceful-degradation mode."
            )

    return sorted(expanded.values(), key=lambda p: p.name), warnings


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
    parser.add_argument(
        "--no-resolve-deps",
        action="store_true",
        help=(
            "Disable automatic resolution of `requires:` dependencies "
            "from SKILL.md frontmatter."
        ),
    )
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
    if not args.no_resolve_deps and not args.all:
        skills, warnings = resolve_dependencies(skills, skills_root)
        for warning in warnings:
            print(f"WARNING: {warning}")
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
