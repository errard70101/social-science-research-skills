---
name: rename-and-organize-references
description: Use when academic paper PDFs, appendices, slides, or replication materials need consistent author-year-title filenames and a reviewed, safe reorganization plan.
---

# Rename and Organize References

## Workflow

1. Identify the target reference directory and confirm its scope.
2. Locate this skill directory, assign its absolute path to `SKILL_DIR`, and
   invoke the bundled script through that variable.
3. Generate a proposal before changing files:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" propose \
     --directory /path/to/references \
     --output /path/to/references/proposed-renames.json
   ```

4. Review `unresolved`, every item with non-high confidence, metadata, and all
   source/destination pairs. Edit the JSON only when the correction is supported
   by the paper or a reliable metadata source.
5. Read `references/mapping-format.md` when editing or diagnosing a proposal.
6. Validate the reviewed mapping:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" validate \
     --mapping /path/to/references/proposed-renames.json
   ```

7. Apply only after validation succeeds and the user approves the exact mapping:

   ```bash
   python "$SKILL_DIR/scripts/rename_references.py" apply \
     --mapping /path/to/references/proposed-renames.json
   ```

8. Inspect the result JSON and verify every completed destination.

Use `--offline` with `propose` when network access is unavailable or not
permitted.

## Naming Convention

- Main paper: `[Authors]_[Year]_[Title].pdf`
- Appendix: `[Authors]_[Year]_[Title]_Appendix.pdf`
- Slides: `[Authors]_[Year]_[Title]_Slides.pdf`
- Replication directory: `[Authors]_[Year]_[Title]_Replication/`

For one to three authors, retain family names in publication order. For four or
more authors, use the first family name followed by `_et_al`.

## Safety Rules

- Never run `apply` on an unreviewed proposal.
- Never invent an author, publication year, or title.
- Treat unresolved metadata and title-search matches as review items.
- Do not bypass collision, containment, or duplicate-operation failures.
- Warn that renaming replication directories can break hard-coded paths inside
  research code; this skill does not rewrite those paths.
- Preserve the result JSON because it records completed operations and reverse
  paths after a failure.

## Dependencies

Use Python 3.10 or newer and install `pypdf`:

```bash
python -m pip install "pypdf>=5.0"
```
