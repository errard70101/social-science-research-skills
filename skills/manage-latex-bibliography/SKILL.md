---
name: manage-latex-bibliography
description: Use when a LaTeX project needs a new or updated BibTeX bibliography, missing citation entries, verified metadata, headline-style titles, or optional AEA bibliography-style setup.
---

# Manage LaTeX Bibliography

## Workflow

1. Confirm the project root or main `.tex` file.
2. Locate this skill directory and assign its absolute path to `SKILL_DIR`.
3. Scan without modifying the project:

   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" scan \
     --project /path/to/project \
     --output /path/to/project/bibliography-proposal.json
   ```

4. Review missing citation keys and inspect prose for likely uncited works.
   Never treat a citation key or prose mention as proof of publication identity.
5. Research each candidate according to
   `references/verification-rules.md`.
6. Give each candidate and its evidence to an independent subagent for a fresh
   online check. If subagents are unavailable, perform a separate second lookup
   without relying on first-pass conclusions.
7. Format titles according to `references/title-case-rules.md`.
8. Populate each proposal entry with its BibTeX type, fields, source URLs,
   conflicts, verifier identity, and status. Use `verified` only after the
   independent check succeeds.
9. Ask the user to approve every prose-inferred reference and every correction
   to an existing entry. Corrections must include the existing fields as
   `before_fields`, use `approved` status, and set both approval flags to true.
10. Validate the completed proposal:

    ```bash
    python "$SKILL_DIR/scripts/manage_bibliography.py" validate \
      --proposal /path/to/project/bibliography-proposal.json
    ```

11. Apply only after validation succeeds:

    ```bash
    python "$SKILL_DIR/scripts/manage_bibliography.py" apply \
      --proposal /path/to/project/bibliography-proposal.json
    ```

12. Review `bibliography-apply-result.json` and compile the project when a TeX
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
