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
conda run -n benchmark python "$SKILL_DIR/scripts/search_repec.py" "your search query" --limit 10
```

**Option B: Fetch latest articles from a specific journal**
Provide the RePEc journal/series handle using `--journal-handle` without a query:

```bash
conda run -n benchmark python "$SKILL_DIR/scripts/search_repec.py" --journal-handle "RePEc:ucp:jpolec" --limit 5
```

The search script outputs a JSON array containing paper titles and links to the IDEAS page.

### 2. Fetching Citation Counts (Impact Evaluation)

Once you have identified a specific paper, you can extract its RePEc Handle from the IDEAS URL (e.g., `https://ideas.repec.org/p/nbr/nberwo/35310.html` -> Handle: `RePEc:nbr:nberwo:35310`).
Use the CitEc API to get its citation count to evaluate its impact:

```bash
conda run -n benchmark python "$SKILL_DIR/scripts/get_citations.py" "RePEc:nbr:nberwo:35310"
```

The script will return a JSON object with `cited_by_count` (how many papers cite this one) and `cites_count` (how many references this paper has).
*Note: The CitEc API has a strict 500 requests IP limit. Use this script sparingly for top-candidate papers only.*

## Dependencies

Use Python 3.10 or newer. Install the required libraries in your environment:

```bash
conda run -n benchmark python -m pip install "httpx>=0.27" "beautifulsoup4>=4.12"
```

## Use Cases
- Finding the most recent working papers (e.g., NBER, CEPR, IZA).
- Searching for papers by specific economic keywords, authors, or titles.
- Generating a list of academic references for an economics topic.
