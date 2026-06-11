# Social Science Research Skills

Portable Agent Skills for repeatable social science research workflows.

## Supported Clients

- Google Antigravity
- Claude Code
- OpenAI Codex
- OpenCode
- GitHub Copilot CLI

## Install

```bash
git clone https://github.com/linshih-yang/social-science-research-skills.git
cd social-science-research-skills
python scripts/install.py --all
```

Install for one client:

```bash
python scripts/install.py \
  --skill rename-and-organize-references \
  --target claude
```

Preview without changing files:

```bash
python scripts/install.py --all --dry-run
```

Use symbolic links while developing:

```bash
python scripts/install.py --all --link
```

The installer copies skills by default. Codex, OpenCode, and Copilot CLI share
`~/.agents/skills`; Antigravity and Claude Code use their own skill directories.

## Skills

### `rename-and-organize-references`

Creates a reviewable mapping for academic paper PDFs and related materials,
validates it, and applies deterministic author-year-title names.

Runtime dependency:

```bash
python -m pip install "pypdf>=5.0"
```

### `summarize-academic-paper`

Produces a two-page LaTeX summary of an economics paper from a PDF, URL,
or DOI. The summary is written for an economics PhD outside the paper's
subfield and emits citation keys that can be used to populate
`references.bib` after rendering.

Runtime dependencies:

```bash
python -m pip install "pypdf>=5.0" "httpx>=0.27"
```

Optional cropped headline visuals require the `render` extra:

```bash
python -m pip install '.[render]'
```

Optional environment variable `UNPAYWALL_EMAIL` enables Unpaywall fallback
for paywalled DOIs.

### `manage-latex-bibliography`

Scans LaTeX projects for missing citations, creates reviewable bibliography
proposals, and applies independently verified BibTeX entries with Chicago-style
headline capitalization.

The skill can configure a traditional BibTeX project for the AEA bibliography
style. It does not redistribute `aea.bst`; after explicit user confirmation,
the helper downloads the current LaTeX template directly from the official AEA
website and extracts the style into the user's project. Online metadata
verification also requires network access.

### `literature-search-repec`

Searches the IDEAS/RePEc database for economics working papers and journal articles. It can perform keyword searches, fetch the latest articles from specific journal handles (e.g., JPE, NBER), and extract citation counts via the CitEc API to evaluate paper impact.

Runtime dependencies:

```bash
python -m pip install httpx beautifulsoup4
```

### `implement-review-fix-workflow`

An Agentic CI/CD engine that runs a non-interactive implementation and review loop. It coordinates a maker (implementer) and a checker (reviewer) to autonomously develop, refine, and verify repository skills or tasks until they pass review.

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
```

Add each canonical skill under `skills/<skill-name>/`. The directory name must
match the `name` in `SKILL.md`. Keep bundled paths relative and avoid
client-specific or machine-specific assumptions.

## Roadmap

The following skills are planned for future development:

### 1. `generate-bib-references`
Generates bibliography files complying with specific academic standards.
- **Goal**: Create a `.bib` file incorporating the `aea.bst` format.
- **Rules**: All entries must follow headline capitalization style.
- **Verification**: Uses a dedicated subagent to cross-check and verify reference correctness by searching the web.
