# Inter-Skill Dependencies and Graceful Degradation

This document describes how skills declare and resolve their dependencies on
other skills, and how parent skills behave when a dependency is not available.

It addresses the three concerns raised in issue #4:

1. **Missing Dependencies** — installing a parent skill without its dependents.
2. **Contract Breakage** — hardcoded references to a specific dependent skill.
3. **Implicit Coupling** — parent skills that cannot adapt to alternative tools.

## 1. Frontmatter contract

`SKILL.md` frontmatter supports two optional list fields:

```yaml
---
name: example-skill
description: ...
requires: [literature-search]
capabilities: [literature-search]
---
```

- `requires:` — a list of either **skill names** (`literature-search-repec`) or
  **capability names** (`literature-search`). A skill name resolves to that
  specific skill; a capability name resolves to any installed skill that
  advertises the capability.
- `capabilities:` — a list of abstract capabilities the skill provides. Other
  skills can request the capability rather than naming this skill directly.

Both fields use inline-array syntax (`[a, b, c]`). The installer parses them
without an external YAML dependency.

## 2. Installer behavior

`scripts/install.py` runs the following pipeline when the user selects a
specific subset of skills (`--skill X --skill Y`, not `--all`):

1. Validate every selected skill's frontmatter.
2. Walk `requires:` transitively, pulling in:
   - any required skill that exists in this repository, and
   - the first installed provider for any required capability.
3. Print a `WARNING:` for any requirement that has no matching skill or
   capability provider. Installation continues; the parent skill is expected
   to run in graceful-degradation mode.

The default installs everything, so the dependency walk is most relevant for
partial installs and downstream consumers that ship a curated subset.

Disable the walk with `--no-resolve-deps` when you want strict, unexpanded
behavior (e.g., reproducing an exact prior install).

## 3. Capability-based invocation in prompts

Parent skills' `SKILL.md` instructions should request **capabilities**, not
specific skill names, whenever multiple equivalent tools could satisfy the
need. For example:

> Use any available literature-search skill (RePEc, OpenAlex, etc.) to
> retrieve ground-truth metadata.

This lets an agent pick from whichever search skills happen to be installed
in the current environment.

## 4. Graceful degradation

When a parent skill cannot find a dependency at runtime, it must degrade
rather than crash:

- **manage-latex-bibliography** — if no literature-search skill is available,
  `verify-existing` still runs against Crossref directly; new-entry workflows
  produce entries tagged `[UNVERIFIED]` and the agent must notify the user
  rather than fabricating metadata.
- **rename-and-organize-references** — `propose` already falls back to local
  PDF metadata when OpenAlex is unreachable, and uses `--offline` to
  short-circuit the network path entirely. Unresolved entries are surfaced in
  the proposal's `unresolved` array rather than dropped.

The general rule: **never invent metadata to paper over a missing dependency.**
Flag the gap, return partial results, and let the user decide.
