---
name: manage-latex-bibliography
description: Use when a LaTeX project needs a new or updated BibTeX bibliography, missing citation entries, verified metadata, headline-style titles, or optional AEA bibliography-style setup.
---

# Manage LaTeX Bibliography

## Workflow

1. **STOP AND ASK THE USER:** "請問您這次需要執行哪一種文獻管理模式？請選擇："
   - **0. Initialize (首次深度健檢)**: Forces every `.bib` entry to be verified online. (Command: `audit --all`)
   - **1. Scan (文獻補漏)**: Checks `.tex` vs `.bib` for missing keys. (Command: `scan`)
   - **2. Audit (日常 PDF 雙向稽核)**: Checks `.bib` vs `references/` for missing PDFs. (Command: `audit`)
   - **3. Update (單點強制更新)**: Forces update on a specific key. (Command: `update-entry`)
   - **4. Verify Existing (現有條目元資料對帳)**: Cross-checks every existing `.bib` entry against Crossref for DOI, title, and year drift. (Command: `verify-existing`)
2. Confirm the project root, the main `.tex` file, or the `references.bib` file.
3. Locate this skill directory and assign its absolute path to `SKILL_DIR`.
4. Based on the selected mode, generate the proposal without modifying the project:

   **Mode 1 (Scan):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" scan \
     --project /path/to/project \
     --output /path/to/project/bibliography-proposal.json
   ```

   **Mode 0 (Initialize):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" audit \
     --bib /path/to/project/references.bib \
     --pdf-dir /path/to/project/references \
     --output /path/to/project/bibliography-proposal.json \
     --all
   ```

   **Mode 2 (Audit):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" audit \
     --bib /path/to/project/references.bib \
     --pdf-dir /path/to/project/references \
     --output /path/to/project/bibliography-proposal.json
   ```

   **Mode 4 (Verify Existing):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" verify-existing \
     --bib /path/to/project/references.bib \
     --output /path/to/project/bibliography-verify-report.json
   ```

   The report lists each entry with `verified`, `inconsistent`, `unverified`,
   or `skipped` status. If Crossref is unreachable, entries gracefully degrade
   to `unverified` so the workflow does not crash.

   **Mode 3 (Update):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" update-entry \
     --proposal /path/to/project/bibliography-proposal.json \
     --key <citation_key> \
     --entry-type <type> \
     --fields <json_fields_string>
   ```

5. Review missing citation keys and inspect prose for likely uncited works.
   Never treat a citation key or prose mention as proof of publication identity.
6. Research each candidate according to `references/verification-rules.md`. You MUST use an available literature search skill (e.g., literature-search-repec or literature-search-openalex) to retrieve the ground truth metadata.
7. Give each candidate and its evidence to an independent subagent for a fresh
   online check. If subagents are unavailable, perform a separate second lookup
   without relying on first-pass conclusions.
8. Format titles according to `references/title-case-rules.md`.
9. Populate each proposal entry with its BibTeX type, fields, source URLs,
   conflicts, verifier identity, and status. Use `verified` only after the
   independent check succeeds.
10. Ask the user to approve every prose-inferred reference and every correction
    to an existing entry. Corrections must include the existing fields as
    `before_fields`, use `approved` status, and set both approval flags to true.
11. Validate the completed proposal:

    ```bash
    python "$SKILL_DIR/scripts/manage_bibliography.py" validate \
      --proposal /path/to/project/bibliography-proposal.json
    ```

12. Apply only after validation succeeds:

    ```bash
    python "$SKILL_DIR/scripts/manage_bibliography.py" apply \
      --proposal /path/to/project/bibliography-proposal.json
    ```

13. Review `bibliography-apply-result.json` and compile the project when a TeX
    toolchain is available.

Re-run `scan` whenever a tracked `.tex` or `.bib` file changes.

## Entry Rules

Use lowercase `authorYearFirstTitleWord` citation keys, for example
`acemoglu2001colonial`. Skip title stop words. If the key collides with another
work, append the next meaningful title word; do not add an arbitrary numeric
suffix.

Use lowercase BibTeX field names and string field values. Keep braces balanced
and protect case-sensitive title content before validation.

## Inferred References

The agent may identify author-year mentions, titles, DOI strings, or other
clear publication references in prose. Show the source passage and proposed
publication to the user. Do not add the citation or entry until the user
approves it.

## AEA Style

This skill does not distribute `aea.bst`. For a traditional BibTeX project,
ask the user before downloading the official AEA template. After confirmation:

```bash
python "$SKILL_DIR/scripts/manage_bibliography.py" install-aea-style \
  --project /path/to/project \
  --confirm-download
```

The helper accepts only an HTTPS download that ends on the official
`aeaweb.org` host and records its URL, retrieval time, and SHA-256 digest.
Never use an unofficial mirror.

Preserve an existing bibliography style. For `biblatex` or `biber`, maintain
entries but do not activate `aea.bst` or convert the project.

## Safety Rules

- Never invent bibliographic metadata.
- Never apply unresolved or unverified entries.
- Never apply inferred references or existing-entry corrections without user
  approval.
- Do not bypass duplicate identifier, stale digest, project containment,
  archive, or overwrite failures.
- Do not add `aea.bst` or downloaded AEA files to this skill or repository.
