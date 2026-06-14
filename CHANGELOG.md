# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
