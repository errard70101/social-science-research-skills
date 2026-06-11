---
name: literature-search-repec
description: Search the RePEc (Research Papers in Economics) database via IDEAS. Use when searching for economics working papers (NBER, CEPR, SSRN economics), academic journal articles, or specific economic authors/topics.
---

# Literature Search: RePEc (IDEAS)

## Workflow

## Usage Instructions

This skill provides two primary capabilities: Searching for papers and Fetching Citation Counts.

### 1. Searching for Papers

**Option A: Keyword Search**
To search for papers by topic or author:

```bash
python "$SKILL_DIR/scripts/search_repec.py" "your search query" --limit 10
```

**Option B: Fetch latest articles from a specific journal**
Provide the RePEc journal/series handle using `--journal-handle` without a query:

```bash
python "$SKILL_DIR/scripts/search_repec.py" --journal-handle "RePEc:ucp:jpolec" --limit 5
```

The search script outputs a JSON array containing paper titles and links to the IDEAS page.

### 2. Fetching Citation Counts (Impact Evaluation)

Once you have identified a specific paper, you can extract its RePEc Handle from the IDEAS URL (e.g., `https://ideas.repec.org/p/nbr/nberwo/35310.html` -> Handle: `RePEc:nbr:nberwo:35310`).
Use the CitEc API to get its citation count to evaluate its impact:

```bash
python "$SKILL_DIR/scripts/get_citations.py" "RePEc:nbr:nberwo:35310"
```

The script will return a JSON object with `cited_by_count` (how many papers cite this one) and `cites_count` (how many references this paper has).
*Note: The CitEc API has a strict 500 requests IP limit. Use this script sparingly for top-candidate papers only.*

## Dependencies

Use Python 3.10 or newer. It requires `httpx` and `beautifulsoup4`.

```bash
python -m pip install httpx beautifulsoup4
```

## Synergy with other skills (AI Operating Guidelines)

- **When renaming PDFs (`rename-and-organize-references`)**: If you need to accurately identify a poorly named economics paper, use this skill to fetch the correct Author, Year, and Title first.
- **When updating LaTeX (`manage-latex-bibliography`)**: If you need to find the correct citation or BibTeX metadata for an economics paper, use this skill to find the IDEAS page, from which authoritative metadata can be extracted.
- **When Snowballing**: If you need to perform massive citation network traversal, use this skill to precisely locate the target paper first, then pass its title/ID to an available citation-network skill such as `literature-search-openalex` when that skill is installed.

## Use Cases
- Finding the most recent working papers (e.g., NBER, CEPR, IZA).
- Searching for papers by specific economic keywords, authors, or titles.
- Generating a list of academic references for an economics topic.
