from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = (
    ROOT
    / "skills"
    / "implement-review-fix-workflow"
    / "scripts"
    / "implement_review_fix_workflow.py"
)


def load_runner():
    spec = importlib.util.spec_from_file_location("skill_workflow", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_reviewer_report(verdict: str = "accept") -> str:
    return f"""Verdict: {verdict}

## Skills used
- requesting-code-review: Used for review.

## Critical
- None.

## Important
- None.

## Minor
- None.

## Validation gaps
- None.

## Decision points for user
- None.
"""


def valid_implementer_report(verdict: str = "implemented") -> str:
    return f"""Verdict: {verdict}

## Skills used
- writing-skills: Used for skill changes.

## Plan
- Inspect files.

## Changes made
- Updated files.

## Validation
- Command: python -m pytest tests/implement_review_fix_workflow/test_runner.py -q
  Result: pass
  Notes: Tests passed.

## Blocked decisions
- None.

## Files changed
- skills/implement-review-fix-workflow/SKILL.md
"""


def test_parse_reviewer_report_accepts_required_sections():
    runner = load_runner()

    report = runner.parse_report(valid_reviewer_report(), kind="reviewer")

    assert report.verdict == "accept"
    assert report.has_items("Important") is False


def test_parse_report_requires_skills_used_section():
    runner = load_runner()
    text = valid_reviewer_report().replace("## Skills used\n", "")

    try:
        runner.parse_report(text, kind="reviewer")
    except runner.ReportError as exc:
        assert "## Skills used" in str(exc)
    else:
        raise AssertionError("missing Skills used section was accepted")


def test_parse_report_rejects_malformed_verdict():
    runner = load_runner()
    text = valid_reviewer_report(verdict="maybe")

    try:
        runner.parse_report(text, kind="reviewer")
    except runner.ReportError as exc:
        assert "Verdict" in str(exc)
    else:
        raise AssertionError("malformed verdict was accepted")


def test_dry_run_writes_prompts_without_invoking_commands(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".skill-workflow-runs"

    result = runner.run_workflow(
        repo=repo,
        task="Add validation to a skill.",
        target_paths=["skills/example-skill/SKILL.md"],
        implementer_cmd="python should-not-run.py --report {report}",
        reviewer_cmd="python should-not-run.py --report {report}",
        runs_dir=runs_dir,
        dry_run=True,
        max_fix_cycles=2,
    )

    assert result.verdict == "dry-run"
    assert result.run_dir.parent == runs_dir
    assert (result.run_dir / "implementer-1-prompt.md").is_file()
    assert (result.run_dir / "reviewer-1-prompt.md").is_file()
    implementer_prompt = (result.run_dir / "implementer-1-prompt.md").read_text(
        encoding="utf-8"
    )
    reviewer_prompt = (result.run_dir / "reviewer-1-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "writing-skills" in implementer_prompt
    assert "verification-before-completion" in implementer_prompt
    assert "requesting-code-review" in reviewer_prompt
    assert "## Skills used" in reviewer_prompt


def init_git_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)


def write_stub_cli(path: Path) -> None:
    path.write_text(
        '''from __future__ import annotations

import argparse
from pathlib import Path


IMPLEMENTER = """Verdict: implemented

## Skills used
- writing-skills: Used for skill changes.

## Plan
- Inspect files.

## Changes made
- Updated files.

## Validation
- Command: python -m pytest tests/implement_review_fix_workflow/test_runner.py -q
  Result: pass
  Notes: Stub validation passed.

## Blocked decisions
- None.

## Files changed
- generated.txt
"""

REVIEWER = """Verdict: accept

## Skills used
- requesting-code-review: Used for review.

## Critical
- None.

## Important
- None.

## Minor
- None.

## Validation gaps
- None.

## Decision points for user
- None.
"""


parser = argparse.ArgumentParser()
parser.add_argument("--kind", required=True)
parser.add_argument("--report", required=True)
parser.add_argument("--repo", required=True)
parser.add_argument("--workdir", required=True)
args = parser.parse_args()

report = Path(args.report)
report.parent.mkdir(parents=True, exist_ok=True)
if args.kind == "implementer":
    Path(args.repo, "generated.txt").write_text("implemented\\n", encoding="utf-8")
    report.write_text(IMPLEMENTER, encoding="utf-8")
elif args.kind == "reviewer":
    report.write_text(REVIEWER, encoding="utf-8")
else:
    raise SystemExit(f"unknown kind: {args.kind}")
''',
        encoding="utf-8",
    )


def test_stub_workflow_accepts_clean_review(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    result = runner.run_workflow(
        repo=repo,
        task="Update a skill.",
        target_paths=["skills/example-skill/SKILL.md"],
        implementer_cmd=(
            f"{sys.executable} {stub} --kind implementer --report {{report}} "
            "--repo {repo} --workdir {workdir}"
        ),
        reviewer_cmd=(
            f"{sys.executable} {stub} --kind reviewer --report {{report}} "
            "--repo {repo} --workdir {workdir}"
        ),
        runs_dir=repo / ".skill-workflow-runs",
        dry_run=False,
        max_fix_cycles=2,
    )

    assert result.verdict == "accept"
    assert (repo / "generated.txt").read_text(encoding="utf-8") == "implemented\n"
    assert len(result.implementation_reports) == 1
    assert len(result.review_reports) == 1


def test_command_timeout_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=(f'{sys.executable} -c "import time; time.sleep(1)"'),
            reviewer_cmd=(
                f"{sys.executable} {stub} --kind reviewer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
            command_timeout=0.01,
        )
    except runner.WorkflowError as exc:
        message = str(exc)
        assert "timed out" in message
        assert "permission or input" in message
    else:
        raise AssertionError("timed out command was accepted")


def test_command_nonzero_exit_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=f'{sys.executable} -c "raise SystemExit(7)"',
            reviewer_cmd=(
                f"{sys.executable} {stub} --kind reviewer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
        )
    except runner.WorkflowError as exc:
        assert "exit 7" in str(exc)
    else:
        raise AssertionError("nonzero command was accepted")


def test_missing_report_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=f'{sys.executable} -c "raise SystemExit(0)"',
            reviewer_cmd=(
                f"{sys.executable} {stub} --kind reviewer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
        )
    except runner.WorkflowError as exc:
        assert "Missing implementer report" in str(exc)
    else:
        raise AssertionError("missing implementer report was accepted")


def write_mutating_reviewer(path: Path) -> None:
    path.write_text(
        '''from __future__ import annotations

import argparse
from pathlib import Path


REVIEWER = """Verdict: accept

## Skills used
- requesting-code-review: Used for review.

## Critical
- None.

## Important
- None.

## Minor
- None.

## Validation gaps
- None.

## Decision points for user
- None.
"""


parser = argparse.ArgumentParser()
parser.add_argument("--report", required=True)
parser.add_argument("--repo", required=True)
parser.add_argument("--workdir", required=True)
args = parser.parse_args()

Path(args.repo, "reviewer-change.txt").write_text("bad\\n", encoding="utf-8")
Path(args.report).write_text(REVIEWER, encoding="utf-8")
''',
        encoding="utf-8",
    )


def test_reviewer_modifies_files_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stub_cli.py"
    mutating_reviewer = tmp_path / "mutating_reviewer.py"
    write_stub_cli(stub)
    write_mutating_reviewer(mutating_reviewer)

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=(
                f"{sys.executable} {stub} --kind implementer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            reviewer_cmd=(
                f"{sys.executable} {mutating_reviewer} --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
        )
    except runner.WorkflowError as exc:
        assert "reviewer modified files" in str(exc)
    else:
        raise AssertionError("mutating reviewer was accepted")


def write_stateful_stub(path: Path, reviewer_mode: str) -> None:
    path.write_text(
        f'''from __future__ import annotations

import argparse
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--kind", required=True)
parser.add_argument("--report", required=True)
parser.add_argument("--repo", required=True)
parser.add_argument("--workdir", required=True)
args = parser.parse_args()

workdir = Path(args.workdir)
log = workdir / "calls.log"
previous = log.read_text(encoding="utf-8") if log.exists() else ""
log.write_text(previous + args.kind + "\\n", encoding="utf-8")
report = Path(args.report)

if args.kind == "implementer":
    Path(args.repo, "generated.txt").write_text(
        previous + "implemented\\n", encoding="utf-8"
    )
    report.write_text("""Verdict: implemented

## Skills used
- writing-skills: Used for skill changes.

## Plan
- Inspect files.

## Changes made
- Updated files.

## Validation
- Command: python -m pytest tests/implement_review_fix_workflow/test_runner.py -q
  Result: pass
  Notes: Stub validation passed.

## Blocked decisions
- None.

## Files changed
- generated.txt
""", encoding="utf-8")
    raise SystemExit(0)

review_count = previous.count("reviewer") + 1
mode = "{reviewer_mode}"
if mode == "important-then-accept" and review_count == 1:
    important = "- Fix the missing validation."
    verdict = "request changes"
elif mode == "always-important":
    important = "- Fix the missing validation."
    verdict = "request changes"
else:
    important = "- None."
    verdict = "accept"

minor = "- Improve wording." if mode == "minor-only" else "- None."
report.write_text(f"""Verdict: {{verdict}}

## Skills used
- requesting-code-review: Used for review.

## Critical
- None.

## Important
{{important}}

## Minor
{{minor}}

## Validation gaps
- None.

## Decision points for user
- None.
""", encoding="utf-8")
''',
        encoding="utf-8",
    )


def workflow_with_stateful_stub(tmp_path: Path, reviewer_mode: str):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "stateful_stub.py"
    write_stateful_stub(stub, reviewer_mode)
    result = runner.run_workflow(
        repo=repo,
        task="Update a skill.",
        target_paths=["skills/example-skill/SKILL.md"],
        implementer_cmd=(
            f"{sys.executable} {stub} --kind implementer --report {{report}} "
            "--repo {repo} --workdir {workdir}"
        ),
        reviewer_cmd=(
            f"{sys.executable} {stub} --kind reviewer --report {{report}} "
            "--repo {repo} --workdir {workdir}"
        ),
        runs_dir=repo / ".skill-workflow-runs",
        dry_run=False,
        max_fix_cycles=2,
    )
    calls = (result.run_dir / "calls.log").read_text(encoding="utf-8").splitlines()
    return result, calls


def test_important_finding_triggers_one_fix_pass(tmp_path):
    result, calls = workflow_with_stateful_stub(tmp_path, "important-then-accept")

    assert result.verdict == "accept"
    assert calls == ["implementer", "reviewer", "implementer", "reviewer"]


def test_minor_finding_does_not_trigger_fix_pass(tmp_path):
    result, calls = workflow_with_stateful_stub(tmp_path, "minor-only")

    assert result.verdict == "accept"
    assert calls == ["implementer", "reviewer"]


def test_loop_stops_after_two_failed_fix_cycles(tmp_path):
    result, calls = workflow_with_stateful_stub(tmp_path, "always-important")

    assert result.verdict == "request changes"
    assert calls == [
        "implementer",
        "reviewer",
        "implementer",
        "reviewer",
        "implementer",
        "reviewer",
    ]


def test_cli_dry_run_writes_final_report(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".skill-workflow-runs"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--repo",
            str(repo),
            "--task",
            "Update a skill.",
            "--target",
            "skills/example-skill/SKILL.md",
            "--implementer-cmd",
            "python should-not-run.py --report {report}",
            "--reviewer-cmd",
            "python should-not-run.py --report {report}",
            "--runs-dir",
            str(runs_dir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "dry-run" in completed.stdout
    assert "Run directory:" in completed.stdout
    run_dirs = list(runs_dir.iterdir())
    assert len(run_dirs) == 1
    final_report = run_dirs[0] / "workflow-final-report.md"
    assert final_report.is_file()
    final_report_text = final_report.read_text(encoding="utf-8")
    assert "Verdict: dry-run" in final_report_text
    assert "## Implementation reports\n- None." in final_report_text
    assert "## Review reports\n- None." in final_report_text


def test_parse_implementer_report_rejects_missing_sections():
    runner = load_runner()
    text = valid_implementer_report().replace("## Plan\n- Inspect files.\n\n", "")

    try:
        runner.parse_report(text, kind="implementer")
    except runner.ReportError as exc:
        assert "## Plan" in str(exc)
    else:
        raise AssertionError("missing Plan section was accepted")


def test_parse_implementer_report_rejects_malformed_verdict():
    runner = load_runner()
    text = valid_implementer_report(verdict="maybe")

    try:
        runner.parse_report(text, kind="implementer")
    except runner.ReportError as exc:
        assert "Verdict" in str(exc)
    else:
        raise AssertionError("malformed verdict was accepted")


def test_implementer_blocked_stops_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    stub = tmp_path / "blocked_stub.py"
    stub.write_text(
        '''
import argparse
from pathlib import Path

IMPLEMENTER = """Verdict: blocked

## Skills used
- none

## Plan
- none

## Changes made
- none

## Validation
- none

## Blocked decisions
- We are blocked.

## Files changed
- none
"""
parser = argparse.ArgumentParser()
parser.add_argument("--report", required=True)
args, _ = parser.parse_known_args()
Path(args.report).write_text(IMPLEMENTER, encoding="utf-8")
''',
        encoding="utf-8",
    )

    result = runner.run_workflow(
        repo=repo,
        task="Update a skill.",
        target_paths=["skills/example-skill/SKILL.md"],
        implementer_cmd=(f"{sys.executable} {stub} --report {{report}}"),
        reviewer_cmd=(
            f"{sys.executable} -c 'raise SystemExit(\"Reviewer should not run\")'"
        ),
        runs_dir=repo / ".skill-workflow-runs",
        dry_run=False,
        max_fix_cycles=2,
    )

    assert result.verdict == "blocked"
    assert len(result.implementation_reports) == 1
    assert len(result.review_reports) == 0


def test_reviewer_modifies_untracked_dir_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # Create an untracked directory
    untracked_dir = repo / "untracked"
    untracked_dir.mkdir()
    (untracked_dir / "existing.txt").write_text("existing", encoding="utf-8")

    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    mutating_reviewer = tmp_path / "mutating_reviewer.py"
    mutating_reviewer.write_text(
        '''from __future__ import annotations

import argparse
from pathlib import Path

REVIEWER = """Verdict: accept

## Skills used
- none

## Critical
- None.

## Important
- None.

## Minor
- None.

## Validation gaps
- None.

## Decision points for user
- None.
"""

parser = argparse.ArgumentParser()
parser.add_argument("--report", required=True)
parser.add_argument("--repo", required=True)
args, _ = parser.parse_known_args()

# Modify inside untracked dir by creating a new file
Path(args.repo, "untracked", "new.txt").write_text("changed\\n", encoding="utf-8")
Path(args.report).write_text(REVIEWER, encoding="utf-8")
''',
        encoding="utf-8",
    )

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=(
                f"{sys.executable} {stub} --kind implementer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            reviewer_cmd=(
                f"{sys.executable} {mutating_reviewer} --report {{report}} "
                "--repo {repo}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
        )
    except runner.WorkflowError as exc:
        assert "reviewer modified files" in str(exc)
    else:
        raise AssertionError("mutating reviewer in untracked dir was accepted")


def test_reviewer_edits_existing_untracked_file_fails_workflow(tmp_path):
    runner = load_runner()
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # Pre-existing untracked file at repo root
    (repo / "scratch.txt").write_text("before", encoding="utf-8")

    stub = tmp_path / "stub_cli.py"
    write_stub_cli(stub)

    mutating_reviewer = tmp_path / "mutating_reviewer.py"
    mutating_reviewer.write_text(
        '''from __future__ import annotations

import argparse
from pathlib import Path

REVIEWER = """Verdict: accept

## Skills used
- none

## Critical
- None.

## Important
- None.

## Minor
- None.

## Validation gaps
- None.

## Decision points for user
- None.
"""

parser = argparse.ArgumentParser()
parser.add_argument("--report", required=True)
parser.add_argument("--repo", required=True)
args, _ = parser.parse_known_args()

# Overwrite contents of an existing untracked file
Path(args.repo, "scratch.txt").write_text("after\\n", encoding="utf-8")
Path(args.report).write_text(REVIEWER, encoding="utf-8")
''',
        encoding="utf-8",
    )

    try:
        runner.run_workflow(
            repo=repo,
            task="Update a skill.",
            target_paths=["skills/example-skill/SKILL.md"],
            implementer_cmd=(
                f"{sys.executable} {stub} --kind implementer --report {{report}} "
                "--repo {repo} --workdir {workdir}"
            ),
            reviewer_cmd=(
                f"{sys.executable} {mutating_reviewer} --report {{report}} "
                "--repo {repo}"
            ),
            runs_dir=repo / ".skill-workflow-runs",
            dry_run=False,
            max_fix_cycles=2,
        )
    except runner.WorkflowError as exc:
        assert "reviewer modified files" in str(exc)
    else:
        raise AssertionError("reviewer editing existing untracked file was accepted")
