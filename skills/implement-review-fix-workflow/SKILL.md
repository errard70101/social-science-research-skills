---
name: implement-review-fix-workflow
description: Use when developing or maintaining repository skills, skill scripts, prompt contracts, references, or related tests through a dry-run-first implement-review-fix workflow.
---

# Implement, Review, Fix Workflow

## Overview

Use this skill for focused work under `skills/` and directly related tests,
references, scripts, and documentation.

The Python runner owns workflow control. Configured non-interactive CLI commands
own implementation and review actions. Superpowers skills own the development
methodology. OpenCode agents are optional interactive fallback only.

## Workflow

1. Read `references/prompt-contracts.md`.
2. Start with dry-run prompt generation and stub commands.
3. Do not use real Codex, Antigravity, or other CLI orchestration until dry-run,
   report validation, stub workflow, and loop tests pass.
4. Store workflow artifacts under `.skill-workflow-runs/`.
5. Require every implementer and reviewer report to include `## Skills used`.

## Runner

Use the bundled runner through this skill directory:

```bash
python "$SKILL_DIR/scripts/implement_review_fix_workflow.py" --help
```

For the first milestone, use dry-run or stub commands only.

## Safety Rules

- Preserve unrelated user changes.
- Never stage, commit, push, or create PRs unless the user explicitly asks.
- Fail if the reviewer command modifies files.
- Reject reports with missing `## Skills used` or malformed `Verdict:` lines.
- Keep real CLI command templates configurable until their syntax is verified.
