# Portable Social Science Research Skills Design

## Objective

Create a public repository of reusable social science research skills that can
be installed across machines and used by:

1. Google Antigravity
2. Claude Code
3. OpenAI Codex
4. OpenCode
5. GitHub Copilot CLI

The first distributed skill will be `rename-and-organize-references`.

## Compatibility Contract

Each canonical skill follows the Agent Skills directory convention:

```text
skill-name/
├── SKILL.md
├── scripts/
├── references/
├── assets/
└── agents/
```

Only `SKILL.md` is required. Optional directories are included only when the
skill uses them.

`SKILL.md` must:

- Use YAML frontmatter containing `name` and `description`.
- Use a lowercase, hyphenated directory name matching `name`.
- Describe triggering conditions clearly in `description`.
- Refer to bundled files with paths relative to the skill directory.
- Avoid assumptions about a specific AI CLI, operating system, username,
  Conda environment, or repository checkout path.

Product-specific metadata may live under `agents/` but must remain optional.
The core workflow must work for agents that ignore such metadata.

## Repository Structure

```text
social-science-research-skills/
├── skills/
│   └── rename-and-organize-references/
│       ├── SKILL.md
│       ├── agents/
│       │   └── openai.yaml
│       ├── scripts/
│       │   └── rename_references.py
│       └── references/
│           └── mapping-format.md
├── scripts/
│   └── install.py
├── tests/
│   ├── test_install.py
│   └── rename_and_organize_references/
│       └── test_rename_references.py
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── .gitignore
├── LICENSE
├── pyproject.toml
└── README.md
```

Canonical skill sources live under `skills/`. Hidden directories such as
`.claude/` and `.agents/` are installation targets, not source directories.

## Installation Design

Provide a standard-library Python installer:

```bash
python scripts/install.py --all
python scripts/install.py --skill rename-and-organize-references
python scripts/install.py --skill rename-and-organize-references --target claude
```

The installer supports `antigravity`, `claude`, `codex`, `opencode`, and
`copilot` as target names. Target paths are defined in one mapping and can be
overridden with `--destination`.

Default user-level destinations:

| Target | Destination |
|---|---|
| Antigravity | `~/.gemini/antigravity/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.agents/skills/` |
| OpenCode | `~/.agents/skills/` |
| GitHub Copilot CLI | `~/.agents/skills/` |

Codex, OpenCode, and Copilot share the Agent Skills destination. The installer
deduplicates identical resolved destinations.

Installation defaults to copying so that an installed skill remains usable if
the repository moves or is deleted. `--link` creates symbolic links for local
development. Reinstalling replaces only the selected skill after validating
the source. It must not delete unrelated skills.

Before replacement, the installer reports the destination. `--dry-run`
performs validation and prints planned actions without changing files.

## First Skill Workflow

`rename-and-organize-references` standardizes academic papers and related
materials using:

```text
[Authors]_[Year]_[Title].pdf
[Authors]_[Year]_[Title]_Appendix.pdf
[Authors]_[Year]_[Title]_Slides.pdf
[Authors]_[Year]_[Title]_Replication/
```

The skill instructs the agent to:

1. Scan a user-selected directory.
2. Extract candidate metadata locally from filenames, PDF metadata, and DOI
   text.
3. Query OpenAlex only when network access is available and local metadata is
   insufficient.
4. Write a JSON proposal without changing source files.
5. Review ambiguous matches and unresolved files with the user.
6. Apply only an explicitly reviewed proposal.
7. Verify that every planned source and destination has the expected state.

The script is a deterministic helper. The agent remains responsible for
reviewing uncertain metadata and the effects of renaming replication folders.

## Script Interface

Use a single CLI with these subcommands:

```bash
python scripts/rename_references.py propose \
  --directory references \
  --output proposed-renames.json

python scripts/rename_references.py validate \
  --mapping proposed-renames.json

python scripts/rename_references.py apply \
  --mapping proposed-renames.json
```

`propose` is read-only except for its explicitly named output file.

`validate` checks:

- Mapping schema and version.
- Source existence.
- Destination uniqueness.
- Destination containment within the declared root.
- Collisions with files not included in the mapping.
- Duplicate or overlapping operations.

`apply` runs validation again, refuses invalid or ambiguous mappings, and
records completed operations in a result JSON file. It must never silently add
numeric suffixes because that changes a reviewed proposal.

## Mapping Format

The mapping is versioned and separates metadata from file operations:

```json
{
  "schema_version": 1,
  "root": "/home/researcher/references",
  "generated_at": "2026-06-07T12:00:00Z",
  "items": [
    {
      "source": "paper.pdf",
      "destination": "Author_2024_Title.pdf",
      "kind": "main-paper",
      "confidence": "high",
      "metadata": {
        "title": "Title",
        "year": 2024,
        "authors": ["Author"],
        "doi": "10.xxxx/example",
        "source": "openalex"
      }
    }
  ],
  "unresolved": []
}
```

Paths inside the mapping are relative to `root`. This makes proposals movable
with their reference directory and prevents hidden dependence on one machine's
absolute paths.

## Metadata and Naming Rules

- Prefer DOI resolution over title search.
- Normalize DOI punctuation captured from PDF text.
- Treat title-search results as ambiguous unless similarity passes a documented
  threshold.
- Never use the current year as a fallback publication year.
- Represent missing year or author metadata as unresolved rather than inventing
  filename components.
- Preserve author order.
- Use family names from structured metadata rather than taking the final token
  of a display name when structured names are available.
- Transliterate Unicode to ASCII for portable filenames.
- Permit ASCII letters, digits, hyphens, and underscores.
- Collapse repeated separators and trim trailing separators.
- Limit each generated filename to a documented maximum length while preserving
  its extension and type suffix.

## Safety and Failure Handling

- Proposal generation never renames source material.
- Application requires a valid, reviewed mapping.
- Operations stay within the mapping root.
- Existing unrelated destinations cause failure.
- A source cannot appear in more than one operation.
- Directory moves cannot overlap or move a parent into its descendant.
- Apply operations are ordered to avoid parent-child path invalidation.
- On failure, stop immediately and write which operations completed.
- The result file provides enough information to construct a reverse mapping.
- Network and PDF extraction failures produce diagnostics and unresolved items,
  not fabricated metadata.

Full transactional filesystem rollback is out of scope for the first version.
The safer contract is preflight validation, deterministic destinations,
fail-fast execution, and a machine-readable operation log.

## Dependencies

Runtime requirements:

- Python 3.10 or newer.
- `pypdf` for PDF text and metadata extraction.

Development requirements:

- `pytest`
- `ruff`

The installer itself uses only the Python standard library. The skill documents
dependency installation without requiring Conda.

## Testing Strategy

Unit tests cover:

- Author and title normalization.
- DOI cleanup and extraction.
- Naming rules and length limits.
- Mapping schema validation.
- Traversal and root-containment rejection.
- Collision and duplicate-operation rejection.
- Deterministic operation ordering.
- Installer target selection and destination deduplication.

Filesystem integration tests use temporary directories to cover:

- Read-only proposal generation.
- Successful file and directory application.
- Failure when an unrelated destination exists.
- Partial-operation result logging.
- Copy and symbolic-link installation.
- Reinstallation without affecting unrelated installed skills.

Network calls use injected metadata providers and local fixtures. The default
test suite does not require internet access.

Skill validation checks:

- Agent Skills frontmatter and directory naming.
- Absence of machine-specific absolute paths.
- Referenced bundled files exist.
- CLI examples work from an arbitrary current directory.

## Documentation

The repository `README.md` explains:

- Supported clients.
- Installation for all clients or a selected client.
- Copy versus symbolic-link development installs.
- Skill inventory.
- Dependency setup.
- How contributors add and validate a skill.

Skill-specific operational instructions remain in `SKILL.md` and its
references rather than being duplicated in the repository README.

## Deferred Scope

The first release does not include:

- A Claude, Codex, Copilot, or Antigravity marketplace.
- Client-specific plugin manifests beyond optional skill metadata.
- Automatic rewriting of paths inside replication code.
- Metadata providers other than local PDF inspection and OpenAlex.
- Guaranteed atomic rollback across arbitrary filesystems.
- Windows junction support for `--link`.

These can be added after the canonical skill and installer are proven across
the five clients.

## Acceptance Criteria

The design is implemented when:

1. One canonical skill folder validates under the Agent Skills convention.
2. No skill instruction or script contains a user-specific absolute path.
3. The installer can dry-run and install the skill for all five target names.
4. Shared destinations are deduplicated.
5. Proposal generation does not rename source files.
6. Invalid, ambiguous, colliding, or escaping mappings cannot be applied.
7. Successful application produces deterministic names and a result log.
8. Automated tests run without network access and pass.
9. Installation and execution are documented from a fresh clone.
