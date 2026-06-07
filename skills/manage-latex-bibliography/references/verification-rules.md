# Bibliographic Verification Rules

## Source Priority

1. Official publisher or journal page.
2. Crossref DOI metadata.
3. Recognized journal or bibliographic index.
4. Google Scholar.

Google Scholar is a discovery and cross-check source, not an automated API.

## Required Checks

Confirm the publication identity and check every applicable field:

- Authors and publication order.
- Year and title.
- Journal, book title, or series.
- Volume, issue, pages, or article number.
- Publisher, institution, school, or edition.
- DOI, ISBN, and canonical publication URL.

The helper's entry-type validation is the minimum acceptance threshold, not the
completeness target.

## Independent Verification

The verifier must repeat the lookup and record its identity. It must not accept
the first researcher's candidate without checking the cited sources.

When the client has no subagent capability, start a separate second pass:

1. Set aside the first-pass conclusion.
2. Search independently from the citation key, prose, DOI, or title.
3. Compare the newly collected evidence with the candidate.
4. Record the second-pass verifier identity and sources.

## Conflicts

Record conflicting values and their URLs. Prefer a higher-priority source only
when it clearly describes the same publication. A lower-priority source never
silently overrides a higher-priority source.

Leave unresolved identity or required fields unwritten. Never infer missing
metadata from the current date, a citation key, or a nearby publication.

## Approval

Verified entries for explicit citation keys may be added. Prose-inferred
references and corrections to existing entries require explicit user approval.
Show field-level before and after values for corrections.
