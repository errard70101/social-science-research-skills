# Design Spec: Enhanced Workflow & Audit for manage-latex-bibliography

## Objective
To eliminate workflow blind spots where existing `.bib` entries are never verified against local PDFs or online databases. The new design introduces a front-end "Mode Selection" prompt for the Agent, and new backend script capabilities to audit and strictly initialize reference libraries.

## 1. Agent Workflow Updates (`SKILL.md`)
The `SKILL.md` file will be rewritten. Step 1 will mandate the Agent to halt and explicitly ask the user which of the 4 modes to run:

1. **Initialize (First-time Deep Check)**
   - **Purpose:** Deep verification for newly imported projects or massive cleanups.
   - **Action:** Forces every single `.bib` entry into the Waterfall Verification pipeline to check for the latest publication metadata and missing PDFs.

2. **Scan (LaTeX Sync)**
   - **Purpose:** Fast, daily usage during paper writing.
   - **Action:** Runs `manage_bibliography.py scan` to strictly find `\cite{}` keys in `.tex` that are missing from `.bib`.

3. **Audit (PDF Sync)**
   - **Purpose:** Routine local library maintenance.
   - **Action:** Checks `.bib` against the `references/` directory. Flags missing PDFs or metadata/filename mismatches.

4. **Update (Manual Fix)**
   - **Purpose:** Surgical metadata override.
   - **Action:** Forces an update on a specific key using `manage_bibliography.py update-entry`.

*After mode selection, the Agent follows the corresponding script execution and routes the output through the existing Waterfall Verification (Step 5).*

## 2. Script Architecture Updates (`manage_bibliography.py`)
Add a new `audit` subcommand:

```bash
python scripts/manage_bibliography.py audit \
  --bib /path/to/references.bib \
  --pdf-dir /path/to/references \
  --output /path/to/bibliography-proposal.json \
  [--all]
```

### Logic Rules for `audit` subcommand:
- **Default Behavior (`--pdf-dir`)**:
  - Parses `.bib` entries.
  - Checks if a corresponding PDF exists in `--pdf-dir`.
  - Determines a match based on standard naming convention (e.g. `[Authors]_[Year]*.pdf` or citation key). *Note: The exact PDF fuzzy matching logic will be implemented to account for both `citation_key.pdf` and `Author_Year_Title.pdf` formats.*
  - If a PDF is missing, or the year in the PDF name mismatches the `.bib` year, the citation key is appended to the `unresolved` list in the JSON proposal.
- **Initialize Behavior (`--all`)**:
  - Ignores local checks and blindly appends **all** citation keys found in the `.bib` file to the `unresolved` list.

## 3. Data Structure & State Management
- No changes to the `bibliography-proposal.json` schema.
- The `audit` command generates standard `unresolved` items. The existing `approve`, `validate`, and `apply` commands will handle these seamlessly.

## 4. Error Handling & Graceful Degradation
- If `--pdf-dir` is not provided or invalid, `audit` gracefully exits or warns the user unless `--all` is set.
