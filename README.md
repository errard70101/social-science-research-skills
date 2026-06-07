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

### `manage-latex-bibliography`

Scans LaTeX projects for missing citations, creates reviewable bibliography
proposals, and applies independently verified BibTeX entries with Chicago-style
headline capitalization.

The skill can configure a traditional BibTeX project for the AEA bibliography
style. It does not redistribute `aea.bst`; after explicit user confirmation,
the helper downloads the current LaTeX template directly from the official AEA
website and extracts the style into the user's project. Online metadata
verification also requires network access.

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

### 1. `summarize-academic-paper`
Extracts structured methodology and key findings from academic papers.
- **Input**: URL to a paper or PDF.
- **Output**:
  1. One-sentence summary
  2. Setup (experimental/empirical design)
  3. Empirical strategy
  4. Key result
  5. Limitations
  6. Follow-ups

### 2. `generate-bib-references`
Generates bibliography files complying with specific academic standards.
- **Goal**: Create a `.bib` file incorporating the `aea.bst` format.
- **Rules**: All entries must follow headline capitalization style.
- **Verification**: Uses a dedicated subagent to cross-check and verify reference correctness by searching the web.
