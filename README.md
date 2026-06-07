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

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
```

Add each canonical skill under `skills/<skill-name>/`. The directory name must
match the `name` in `SKILL.md`. Keep bundled paths relative and avoid
client-specific or machine-specific assumptions.
