---
name: literature-search-repec
description: Search the RePEc (Research Papers in Economics) database via IDEAS. Use when searching for economics working papers (NBER, CEPR, SSRN economics), academic journal articles, or specific economic authors/topics.
---

# Literature Search: RePEc (IDEAS)

## Workflow

1. Identify the search terms, author names, or paper titles to query.
2. Locate this skill directory, assign its absolute path to `SKILL_DIR`, and invoke the bundled script through that variable.
3. Run the search script to query the IDEAS RePEc database:

   ```bash
   conda run -n benchmark python "$SKILL_DIR/scripts/search_repec.py" "your search query" --limit 10
   ```

4. The script outputs a JSON array of search results, including paper titles, authors, and links to the IDEAS page.
5. Review the results to extract the relevant papers. If needed, you can use the `read_url_content` tool on the resulting links to fetch the full paper metadata (abstract, JEL codes, download links) from the IDEAS website.

## Dependencies

Use Python 3.10 or newer. Install the required libraries in your environment:

```bash
conda run -n benchmark python -m pip install "httpx>=0.27" "beautifulsoup4>=4.12"
```

## Use Cases
- Finding the most recent working papers (e.g., NBER, CEPR, IZA).
- Searching for papers by specific economic keywords, authors, or titles.
- Generating a list of academic references for an economics topic.
