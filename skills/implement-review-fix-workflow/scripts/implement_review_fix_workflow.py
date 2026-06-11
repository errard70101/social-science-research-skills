from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

IMPLEMENTER_VERDICTS = {"implemented", "blocked", "no changes needed"}
REVIEWER_VERDICTS = {"accept", "request changes", "reject"}

IMPLEMENTER_SECTIONS = [
    "Skills used",
    "Plan",
    "Changes made",
    "Validation",
    "Blocked decisions",
    "Files changed",
]
REVIEWER_SECTIONS = [
    "Skills used",
    "Critical",
    "Important",
    "Minor",
    "Validation gaps",
    "Decision points for user",
]


class ReportError(ValueError):
    pass


class WorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class Report:
    verdict: str
    sections: dict[str, str]

    def has_items(self, section: str) -> bool:
        body = self.sections.get(section, "")
        items = [
            line.strip() for line in body.splitlines() if line.strip().startswith("-")
        ]
        return any(item not in {"- None.", "- None"} for item in items)


@dataclass(frozen=True)
class WorkflowResult:
    verdict: str
    run_dir: Path
    implementation_reports: list[Path]
    review_reports: list[Path]


def parse_report(text: str, *, kind: str) -> Report:
    verdict_match = re.search(r"^Verdict:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if verdict_match is None:
        raise ReportError("Missing Verdict line")

    verdict = verdict_match.group(1).strip()
    if kind == "implementer":
        allowed = IMPLEMENTER_VERDICTS
        required = IMPLEMENTER_SECTIONS
    elif kind == "reviewer":
        allowed = REVIEWER_VERDICTS
        required = REVIEWER_SECTIONS
    else:
        raise ReportError(f"Unknown report kind: {kind}")

    if verdict not in allowed:
        raise ReportError(f"Malformed Verdict for {kind}: {verdict}")

    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()

    for section in required:
        if section not in sections:
            raise ReportError(f"Missing ## {section} section")

    return Report(verdict=verdict, sections=sections)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "skill-workflow"


def create_run_dir(runs_dir: Path, task: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"{stamp}-{slugify(task)}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = runs_dir / f"{base.name}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def render_implementer_prompt(
    *,
    task: str,
    target_paths: list[str],
    report_path: Path,
    fix_report: Path | None = None,
) -> str:
    targets = "\n".join(f"- {path}" for path in target_paths)
    fix_context = ""
    if fix_report is not None:
        fix_context = f"\nReview report to address: {fix_report}\n"
    return f"""# Implementer Prompt

Task: {task}

Target paths:
{targets}
{fix_context}
Write your report to: {report_path}

Required superpowers skills when applicable:
- writing-plans
- test-driven-development
- systematic-debugging
- verification-before-completion
- writing-skills

The report must contain `## Skills used` and all implementer report sections.
"""


def render_reviewer_prompt(
    *, task: str, implementation_report: Path, report_path: Path
) -> str:
    return f"""# Reviewer Prompt

Task: {task}

Implementation report: {implementation_report}
Write your report to: {report_path}

Required superpowers skills when applicable:
- requesting-code-review
- verification-before-completion

Do not modify files. The runner will compare git snapshots before and after
your command and fail if files changed.

The report must contain `## Skills used` and all reviewer report sections.
"""


def expand_command(
    template: str, *, prompt: Path, report: Path, workdir: Path, repo: Path
) -> list[str]:
    values = {
        "prompt": str(prompt),
        "report": str(report),
        "workdir": str(workdir),
        "repo": str(repo),
    }
    return shlex.split(template.format(**values))


def run_command(command: list[str], *, repo: Path, timeout: float) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(
            "command timed out; it may be waiting for permission or input: "
            f"{' '.join(command)}"
        ) from exc
    if completed.returncode != 0:
        raise WorkflowError(
            "command failed with exit "
            f"{completed.returncode}: {' '.join(command)}\n{completed.stderr}"
        )


def read_required_report(path: Path, *, kind: str) -> Report:
    if not path.is_file():
        raise WorkflowError(f"Missing {kind} report: {path}")
    try:
        return parse_report(path.read_text(encoding="utf-8"), kind=kind)
    except ReportError as exc:
        raise WorkflowError(str(exc)) from exc


def git_snapshot(repo: Path, exclude: Path | None = None) -> str:
    status = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    exclude_rel: str | None = None
    if exclude is not None:
        try:
            exclude_rel = exclude.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            exclude_rel = None
        if exclude_rel is not None:
            quoted_prefix = f'"{exclude_rel}/'
            unquoted_prefix = f"{exclude_rel}/"
            lines = []
            for line in status.splitlines():
                path = line[3:]
                if (
                    path == exclude_rel
                    or path == f'"{exclude_rel}"'
                    or path.startswith(unquoted_prefix)
                    or path.startswith(quoted_prefix)
                ):
                    continue
                lines.append(line)
            status = "\n".join(lines) + ("\n" if lines else "")
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    untracked_hashes: list[str] = []
    for path in untracked.split("\0"):
        if not path:
            continue
        if exclude_rel is not None and (
            path == exclude_rel or path.startswith(f"{exclude_rel}/")
        ):
            continue
        try:
            data = (repo / path).read_bytes()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            continue
        digest = hashlib.sha256(data).hexdigest()
        untracked_hashes.append(f"{digest} {path}")
    untracked_block = "\n".join(sorted(untracked_hashes))
    return f"{status}\n---DIFF---\n{diff}\n---UNTRACKED---\n{untracked_block}"


def run_workflow(
    *,
    repo: Path,
    task: str,
    target_paths: list[str],
    implementer_cmd: str,
    reviewer_cmd: str,
    runs_dir: Path,
    dry_run: bool,
    max_fix_cycles: int,
    command_timeout: float = 300,
) -> WorkflowResult:
    run_dir = create_run_dir(runs_dir, task)
    implementer_prompt = run_dir / "implementer-1-prompt.md"
    reviewer_prompt = run_dir / "reviewer-1-prompt.md"
    implementation_report = run_dir / "implementer-1-report.md"
    review_report = run_dir / "reviewer-1-report.md"
    if dry_run:
        implementer_prompt.write_text(
            render_implementer_prompt(
                task=task,
                target_paths=target_paths,
                report_path=implementation_report,
            ),
            encoding="utf-8",
        )
        reviewer_prompt.write_text(
            render_reviewer_prompt(
                task=task,
                implementation_report=implementation_report,
                report_path=review_report,
            ),
            encoding="utf-8",
        )
        return WorkflowResult(
            verdict="dry-run",
            run_dir=run_dir,
            implementation_reports=[],
            review_reports=[],
        )

    implementation_reports: list[Path] = []
    review_reports: list[Path] = []
    previous_review_report: Path | None = None
    max_attempts = max_fix_cycles + 1

    for attempt in range(1, max_attempts + 1):
        implementer_prompt = run_dir / f"implementer-{attempt}-prompt.md"
        reviewer_prompt = run_dir / f"reviewer-{attempt}-prompt.md"
        implementation_report = run_dir / f"implementer-{attempt}-report.md"
        review_report = run_dir / f"reviewer-{attempt}-report.md"

        implementer_prompt.write_text(
            render_implementer_prompt(
                task=task,
                target_paths=target_paths,
                report_path=implementation_report,
                fix_report=previous_review_report,
            ),
            encoding="utf-8",
        )
        run_command(
            expand_command(
                implementer_cmd,
                prompt=implementer_prompt,
                report=implementation_report,
                workdir=run_dir,
                repo=repo,
            ),
            repo=repo,
            timeout=command_timeout,
        )
        implementer_report = read_required_report(
            implementation_report, kind="implementer"
        )
        implementation_reports.append(implementation_report)

        if implementer_report.verdict == "blocked":
            return WorkflowResult(
                verdict=implementer_report.verdict,
                run_dir=run_dir,
                implementation_reports=implementation_reports,
                review_reports=review_reports,
            )

        reviewer_prompt.write_text(
            render_reviewer_prompt(
                task=task,
                implementation_report=implementation_report,
                report_path=review_report,
            ),
            encoding="utf-8",
        )
        before_review = git_snapshot(repo, exclude=run_dir)
        run_command(
            expand_command(
                reviewer_cmd,
                prompt=reviewer_prompt,
                report=review_report,
                workdir=run_dir,
                repo=repo,
            ),
            repo=repo,
            timeout=command_timeout,
        )
        after_review = git_snapshot(repo, exclude=run_dir)
        if after_review != before_review:
            raise WorkflowError("reviewer modified files")
        reviewer_report = read_required_report(review_report, kind="reviewer")
        review_reports.append(review_report)

        needs_fix = reviewer_report.has_items("Critical") or reviewer_report.has_items(
            "Important"
        )
        if not needs_fix or attempt == max_attempts:
            return WorkflowResult(
                verdict=reviewer_report.verdict,
                run_dir=run_dir,
                implementation_reports=implementation_reports,
                review_reports=review_reports,
            )
        previous_review_report = review_report

    raise WorkflowError("review-fix loop ended unexpectedly")


def write_final_report(result: WorkflowResult) -> Path:
    path = result.run_dir / "workflow-final-report.md"
    implementation_reports = (
        "\n".join(f"- {report}" for report in result.implementation_reports)
        or "- None."
    )
    review_reports = (
        "\n".join(f"- {report}" for report in result.review_reports) or "- None."
    )
    path.write_text(
        f"""Verdict: {result.verdict}

## Implementation reports
{implementation_reports}

## Review reports
{review_reports}
""",
        encoding="utf-8",
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run implement-review-fix workflow")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--target", action="append", dest="targets", required=True)
    parser.add_argument("--implementer-cmd", required=True)
    parser.add_argument("--reviewer-cmd", required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path(".skill-workflow-runs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-fix-cycles", type=int, default=2)
    parser.add_argument("--command-timeout", type=float, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runs_dir = args.runs_dir
    if not runs_dir.is_absolute():
        runs_dir = args.repo / runs_dir
    result = run_workflow(
        repo=args.repo,
        task=args.task,
        target_paths=args.targets,
        implementer_cmd=args.implementer_cmd,
        reviewer_cmd=args.reviewer_cmd,
        runs_dir=runs_dir,
        dry_run=args.dry_run,
        max_fix_cycles=args.max_fix_cycles,
        command_timeout=args.command_timeout,
    )
    final_report = write_final_report(result)
    print(f"Verdict: {result.verdict}")
    print(f"Run directory: {result.run_dir}")
    print(f"Final report: {final_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
