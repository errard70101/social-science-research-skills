---
name: query-zotero-library
description: Retrieve and synthesize evidence from the user's own Zotero library through Zotero's official read-only Local API. Use when asked to find, compare, summarize, or answer research questions from papers and PDFs the user has collected in Zotero, especially while working inside a research repository. Supports optional collection hints and relevant-page extraction without Web API keys, third-party MCP servers, library writes, or vector indexing.
---

# Query Zotero Library

Use Zotero as the source of truth, retrieve a small evidence set, read the local
PDFs, and answer the research question with traceable support.

Before running a bundled script, locate this skill directory and assign its absolute path to `SKILL_DIR`.

## Workflow

1. Treat the user's question as the primary retrieval query. Use the current
   repository only to clarify terminology or generate additional compact search
   phrases.
2. Look for an optional preferred Zotero collection in project instructions
   such as `AGENTS.md`. Do not require a mapping, invent a repository convention,
   or modify project instructions.
3. Check the local connection:

   ```bash
   python "$SKILL_DIR/scripts/zotero_library.py" check
   ```

4. Search with two to four short phrases when the first query is broad. Zotero
   quick search treats each `q` value as a phrase; the helper requests
   `qmode=everything` so Zotero can use its local full-text index.

   Search the whole personal library by default:

   ```bash
   python "$SKILL_DIR/scripts/zotero_library.py" search \
     "bandwidth selection" --limit 10
   ```

   Narrow to a collection only when the user specifies one or project
   instructions provide an optional hint:

   ```bash
   python "$SKILL_DIR/scripts/zotero_library.py" search \
     "bandwidth selection" \
     --collection "0 Working Projects / ITS" \
     --limit 10
   ```

5. Review metadata and attachment availability before reading. Prefer three to
   five high-relevance papers; expand only when the evidence is inadequate.
   Check `total_results` and `truncated` in each response. A truncated result is
   still a whole-library or collection-wide search; refine the phrase or raise
   `--limit` before concluding that no better candidates exist.
6. Extract bounded, query-ranked page text from each available PDF:

   ```bash
   python "$SKILL_DIR/scripts/zotero_library.py" extract \
     "/local/path/to/paper.pdf" \
     --query "bandwidth selection" \
     --max-pages 8
   ```

7. Answer from the retrieved page text, not from titles or search matches alone.

## Search Scope

Apply this priority:

1. A collection explicitly named by the user.
2. An optional preferred collection found in project instructions.
3. The entire personal Zotero library.

If a user-specified collection is missing or ambiguous, report the problem
instead of silently broadening the scope. If an optional project hint is stale,
disclose that fact and retry the whole library. When broad searches remain
noisy, suggest that the user specify a collection or record a preferred
collection in project instructions; never make that configuration mandatory.

## Evidence Rules

- Treat a metadata match as a candidate, not evidence for a substantive claim.
- For each supported claim, identify author, year, title, Zotero item key, and
  the extracted PDF page when available.
- Label extracted page numbers as PDF pages because they may differ from printed
  journal pagination.
- Separate direct paper findings from cross-paper synthesis and from open
  questions.
- When no local PDF is available, report metadata only and say that the full
  text was not verified.
- When extraction reports missing text, explain that OCR may be required.
- If the extracted evidence is insufficient, say so and stop; do not fill gaps
  with metadata, general knowledge, or an unverified abstract.
- Never fabricate quotations, page numbers, bibliographic fields, or findings.

## Boundaries

- Use only Zotero's official loopback Local API and the bundled GET-only helper.
- Keep all traffic on localhost. Never expose or forward the Local API port.
- Do not request, store, or use a Zotero Web API key.
- Do not add, edit, move, tag, merge, or delete Zotero items or attachments.
- Do not read or write `zotero.sqlite` directly.
- Do not use a third-party Zotero MCP server.
- Do not create embeddings, a vector database, or a persistent full-text index.
- Do not construct OS-specific Zotero paths. Use only attachment paths returned
  by the Local API helper.
- Treat `Total-Results` as the match count and `count` as the bounded number
  returned by the helper.

Read `references/local-api-boundaries.md` when troubleshooting API behavior,
collection resolution, missing attachments, or cross-platform paths.

## Dependencies

Use Python 3.10 or newer with `httpx` and `pypdf`. Zotero Desktop must be
running, Local API access must be enabled, and a PDF must be available on the
current computer before its full text can be verified.
