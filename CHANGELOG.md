# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **`manage-zotero-library`** now gates Local API writes on the live
  `Zotero-Server-ID` capability signal. GET-only Zotero versions can still
  produce reviewable plans, but those plans are routed to manual Zotero Desktop
  application and are rejected before authorization or any write request.

## [0.3.0] - 2026-07-29

### Added
- **`query-zotero-library`**: new cross-platform skill for searching a
  researcher's personal Zotero library through the official read-only Local
  API, resolving local PDF attachments, and extracting bounded page evidence.
- Collection discovery with nested paths, item counts, and exact collection-key
  selection.
- Read-only retrieval of child notes and PDF annotations, including selected
  text, comments, page labels, tags, and attachment provenance.
- Optional PyMuPDF fallback for PDFs that `pypdf` cannot open or extracts as
  nearly empty or control-character-corrupted text.

### Changed
- PDF extraction can return leading pages without a query or rank bounded pages
  by query. Results identify the parser and any pages supplied by fallback.
- Zotero search responses expose `Total-Results` truncation and decoded native
  attachment paths without requiring Web API keys, SQLite access, third-party
  MCP servers, vector indexing, or filesystem searches.

### Fixed
- Percent-encoded spaces and Unicode characters in Local API attachment URLs
  are decoded before checking file availability.
- Collection filters accept exact Zotero keys and report ambiguous duplicate
  names instead of silently selecting one.

## [0.2.2] - 2026-07-27

Audit pass over the skill surface. Every finding was a skill instructing an
agent to do something the code could not do, or restating a rule that lived
somewhere else.

### Fixed
- **`literature-search-repec`**, **`implement-review-fix-workflow`**: `SKILL.md` used `$SKILL_DIR` without ever telling the agent to assign it, so every documented command ran against an empty path. All five skills now define it before first use.
- **`manage-latex-bibliography`**: `SKILL.md` documented an `update-entry` subcommand that argparse never registered; the call failed with `invalid choice`. Editing a proposal entry in place and re-running `validate` replaces it.
- **`scripts/install.py`**: skill installs copied `__pycache__` and stale bytecode into the client skill directories. `copytree` now excludes `__pycache__` and `*.py[cod]`.
- **`summarize-academic-paper`**: the citation-key convention was named `authorYearFirstWord` here and `authorYearFirstTitleWord` in `manage-latex-bibliography`, which owns the actual rules. Both documents now point at the canonical `Entry Rules` section.
- **README**: described the `render` extra as producing cropped headline visuals; image mode emits a page-level snapshot, as `SKILL.md` has said since c7187b5.

### Changed
- **`manage-latex-bibliography`**: replaced the unconditional five-mode "STOP AND ASK" menu with named operations the agent selects directly, asking only when the request is genuinely ambiguous. The menu text was also hardcoded Traditional Chinese while every other skill is English.
- **`literature-search-repec`**: removed an empty `## Workflow` heading and a "Synergy with other skills" section that restated the `requires:`/`capabilities:` frontmatter contract.
- All five skills now ship `agents/openai.yaml`; previously two of them did not.
- `CONTRIBUTING.md` records that `AGENTS.md` is canonical and `CLAUDE.md` / `GEMINI.md` must stay byte-identical.

### Added
- Structure tests discover skills from the `skills/` directory and derive each skill's bundled files from its `SKILL.md`, instead of a hardcoded whitelist a new skill could silently escape.
- New guard parses every `$SKILL_DIR/scripts/*.py <subcommand>` invocation out of each `SKILL.md` and asserts argparse accepts it — 12 subcommands across three skills.
- Regression tests for `SKILL_DIR` ordering, bytecode exclusion, client-instruction-file synchronization, and each documentation fix above. Suite grew from 345 to 370 tests.

## [0.2.1] - 2026-06-14

### Fixed
- **`summarize-academic-paper`**: Offloaded extracted pages into a separate `.pages.jsonl` file to bound the `extract.json` artifact size (schema bumped to v2).
- **`summarize-academic-paper`**: Used content-addressed filenames (SHA256) for PDF downloads to prevent duplicates.
- **`summarize-academic-paper`**: Added fallback checks for `%PDF-` magic bytes when validating PDF responses.
- **`summarize-academic-paper`**: Updated template to use safer default `plainnat` and clarified "page-snapshot" mode instructions.

## [0.2.0] - 2026-06-14

### Added
- **`manage-latex-bibliography`** gains an `audit` subcommand that cross-checks the `.bib` against a PDF directory, with a `--all` strict-initialization mode.
- **`manage-latex-bibliography`** gains a `verify-existing` subcommand: cross-checks every existing `.bib` entry's DOI, title, and year against Crossref and emits a Metadata Inconsistency Report. Gracefully degrades to `unverified` when the source is unreachable. (#3)
- **`rename-and-organize-references`** `propose` accepts `--template`, `--transform` (`none`/`lowercase`/`kebab-case`/`snake_case`), and `--separator` flags so projects can override the default `Authors_Year_Title` convention. (#3)
- **Inter-skill dependency contract**: `SKILL.md` frontmatter supports inline-array `requires:` and `capabilities:`; `scripts/install.py` resolves dependencies transitively and warns on missing capability providers rather than crashing. New doc `docs/architecture-dependencies.md`. (#4)

### Changed
- Parent skills (`manage-latex-bibliography`, `rename-and-organize-references`) now request the abstract `literature-search` capability instead of naming specific search skills, and instruct agents to tag `[UNVERIFIED]` rather than fabricate metadata when no provider is installed.

## [0.1.0] - 2026-06-14

### Added
- Initial alpha release of `social-science-research-skills` as a portable Agent Skills library.
- **`rename-and-organize-references`**: Creates a reviewable mapping for academic paper PDFs and applies deterministic author-year-title names.
- **`summarize-academic-paper`**: Produces a two-page LaTeX summary of an economics paper from a PDF, URL, or DOI.
- **`manage-latex-bibliography`**: Scans LaTeX projects for missing citations, verifies them, and applies Chicago-style headline capitalization.
- **`literature-search-repec`**: Searches the IDEAS/RePEc database for economics working papers and journal articles.
- **`implement-review-fix-workflow`**: An Agentic CI/CD engine that runs an autonomous, non-interactive implementation and review loop for skill development.
