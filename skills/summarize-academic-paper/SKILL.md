---
name: summarize-academic-paper
description: Use when preparing for or hosting an academic seminar and you need a 2-page LaTeX summary of an economics paper (PDF, URL, or DOI) written for an econ PhD outside the subfield.
---

# Summarize Academic Paper

## Workflow

1. Confirm the input (PDF path, URL, or DOI) and the output directory.
   Default the output directory to the source PDF's directory when the input
   is local and to the current working directory otherwise.

2. Locate this skill directory, assign its absolute path to `SKILL_DIR`, and
   invoke the bundled script through that variable.

3. Fetch the paper:

   ```bash
   python "$SKILL_DIR/scripts/summarize_paper.py" fetch \
     --input <pdf|url|doi> \
     --output-dir <work-dir>
   ```

   Inspect `summarize-paper-fetch.json`. When `unresolved` is non-null,
   surface the message to the user and stop.

4. Extract text, metadata, and table or figure caption candidates:

   ```bash
   python "$SKILL_DIR/scripts/summarize_paper.py" extract \
     --fetch <work-dir>/summarize-paper-fetch.json \
     --output <work-dir>/summarize-paper-extract.json
   ```

   When `warnings` includes `no-extractable-text`, surface the message to the
   user and stop. Other warnings (for example `author-guess-empty`) are
   recorded but do not stop the workflow.

5. Synthesize the content JSON. Read `references/section-rubric.md` for the
   length bands and writing rules; consult `references/input-sources.md`
   when the input source (URL or DOI) needs verification or troubleshooting.
   Draft each section from the extracted text; never rely on training
   knowledge for facts about the paper. Pick at most one headline visual
   from `table_candidates`, preferring the table or figure the paper itself
   flags as central. Generate predecessor citation keys following the
   `authorYearFirstWord` rule used by `manage-latex-bibliography`. Write the
   content JSON to `<work-dir>/summarize-paper-content.json`.

6. Render the LaTeX summary:

   ```bash
   python "$SKILL_DIR/scripts/summarize_paper.py" render \
     --extract <work-dir>/summarize-paper-extract.json \
     --content <work-dir>/summarize-paper-content.json \
     --output-tex <work-dir>/<Authors>_<Year>_<Title>_Summary.tex \
     [--include-table "Table 3" | --include-figure "Figure 1"] \
     [--reproduce-tables]
   ```

   Read the generated `.tex` and confirm each section is non-empty. If any
   required slot is empty or far outside its rubric band, fix the content
   JSON and re-render rather than hand-editing the `.tex`.

7. Hand off to `manage-latex-bibliography` to populate `references.bib`.
   That skill scans the new `.tex`, identifies the paper-of-record key and
   each predecessor key as missing, verifies them online, and writes
   `references.bib`. The hand-off does not require user confirmation each
   time. User confirmation is required only when the bibliography skill
   installs or copies `aea.bst`, or when it proposes nontrivial modifications
   to existing files.

8. Run the final validation checklist (below) and inform the user of the
   output path and any remaining warnings.

## Naming Convention

- Summary: `<Authors>_<Year>_<Title>_Summary.tex`
- Supporting assets:
  `<Authors>_<Year>_<Title>_Summary/figures/<label-slug>.png`

One to three family names join with underscores in publication order. Four or
more authors use the first family name followed by `_et_al`. Identical to
`rename-and-organize-references` so the summary sorts next to the paper.

## Stop or Warn-and-Continue

Stop and ask the user when:

- The input cannot be resolved to a PDF (`fetch` reports `unresolved`).
- The PDF has no extractable text (`extract` reports `no-extractable-text`).
- The requested headline visual cannot be produced (label missing,
  `pymupdf` not installed for image mode, or `--reproduce-tables` set without
  `headline_visual.latex_table`).
- Validation of the content JSON fails for a structural reason.

Warn in the output JSON and continue when:

- The paper's venue cannot be determined; record
  `paper.venue = "working paper"` and let `manage-latex-bibliography` verify.
- No predecessor citations can be identified; leave `predecessor_citations`
  empty and write a prose-only placement-in-literature paragraph.
- Author count, ordering, or affiliations are ambiguous from the first page;
  record the best inference and a warning.
- A section is outside its rubric band. The renderer emits a warning when a
  slot is more than 25 percent outside the band; the agent decides whether to
  revise. Rubric excursions never stop the workflow.

## Safety Rules

- Never fabricate coefficients, standard errors, sample sizes, point
  estimates, or claims of statistical significance.
- Never invent a venue or year. When uncertain, use
  `paper.venue = "working paper"`.
- Image mode produces a page-level snapshot of the page where the table or
  figure caption appears, not a tight crop. Use reconstructed table mode when
  a clean visual is needed and you can supply the LaTeX from the paper text
  without paraphrasing.
- Predecessor citations come only from the paper's own related-work or
  introduction sections.
- Never bypass `unresolved` or `no-extractable-text` reports.
- Never hand-edit the rendered `.tex` to fill a missing section. Edit the
  content JSON and re-render.
- Never write to `references.bib` from this skill.

## Final Validation Checklist

1. Compile the `.tex` with XeLaTeX followed by BibTeX and two more XeLaTeX
   passes. When the user's `compile-latex` skill is available, invoke it;
   otherwise report the required commands.
2. The `.tex` contains no empty `\cite{}` commands.
3. Every required section slot is non-empty.
4. When the content JSON requests an image headline visual, the referenced
   PNG path exists under
   `<Authors>_<Year>_<Title>_Summary/figures/`.
5. After the bibliography hand-off, `references.bib` contains the
   paper-of-record citation key.
6. When compilation succeeded in checklist item 1, the compiled PDF is
   approximately two pages. A spill to three or more pages produces a
   warning that names the longest section. When compilation did not run,
   this check is skipped.

## Dependencies

Python 3.10+ with `pypdf>=5.0` and `httpx>=0.27`. For page-snapshot headline
visuals install the optional `render` extra:

```bash
python -m pip install '.[render]'
```

XeLaTeX, BibTeX, and `aea.bst` are required to compile the output;
`manage-latex-bibliography` handles `aea.bst` installation.

The optional `UNPAYWALL_EMAIL` environment variable enables the Unpaywall
fallback for paywalled DOIs.
