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

Optional page-snapshot headline visuals require the `render` extra:

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

### `query-zotero-library`

Searches a researcher's own Zotero library through the official read-only Local
API, locates local PDF attachments across macOS, Windows, and Linux, and
extracts relevant pages for source-grounded answers. It can also read child
notes and PDF annotations without modifying them. It requires Zotero Desktop to
be running with local application access enabled. A project can optionally name
a preferred Zotero collection in its agent instructions; otherwise the skill
searches the whole personal library.
It does not use Zotero Web API keys, third-party Zotero MCP servers, Zotero
writes, direct SQLite access, or vector indexing.

Runtime dependencies:

```bash
python -m pip install "httpx>=0.27" "pypdf>=5.0"
```

Optional PyMuPDF fallback for PDFs with difficult font encodings:

```bash
python -m pip install "pymupdf>=1.24"
```

This fallback improves text extraction but does not provide OCR.

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
