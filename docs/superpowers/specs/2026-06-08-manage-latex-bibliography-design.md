# Manage LaTeX Bibliography Skill Design

## Objective

Add a portable `manage-latex-bibliography` skill for maintaining BibTeX
bibliographies while writing or revising LaTeX documents. The skill must:

- Find citation keys used by `.tex` files but missing from the active `.bib`
  file.
- Detect likely prose references to works that have not yet been cited, then
  require user confirmation before adding them.
- Research and independently verify complete bibliographic metadata online.
- Add verified entries and propose corrections to existing entries.
- Apply Chicago-style headline capitalization while preserving required
  BibTeX case protection.
- Configure traditional BibTeX projects to use the AEA bibliography style when
  no bibliography configuration exists.
- Obtain `aea.bst` from the official AEA template only after user confirmation,
  without redistributing it in this repository.

The skill is intended both for explicit maintenance of an existing LaTeX
project and for invocation during document drafting when a new citation is
needed.

## Skill Structure

```text
skills/manage-latex-bibliography/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   └── manage_bibliography.py
└── references/
    ├── title-case-rules.md
    └── verification-rules.md
```

The skill does not contain `aea.bst`, an AEA template archive, or a copy of any
other AEA-owned file. The repository's MIT license applies only to files
created for this project.

## Responsibility Boundaries

The Python helper performs deterministic operations:

- Discover and parse LaTeX and BibTeX files.
- Inventory citation keys and bibliography declarations.
- Validate proposal structure and entry status.
- Normalize and validate citation keys and titles.
- Detect duplicate keys and identifiers.
- Apply approved changes using atomic file replacement.
- Download the official AEA template archive, safely extract `aea.bst`, and
  record provenance after explicit user confirmation.

The agent performs judgment-dependent work:

- Interpret prose as a possible reference to a publication.
- Search publishers, Crossref, journal indexes, and Google Scholar.
- Reconcile metadata among sources.
- Determine necessary case protection for proper nouns, abbreviations, LaTeX
  commands, and mathematics.
- Ask the user to resolve ambiguity or approve protected changes.

This split keeps filesystem changes reproducible without pretending that
publisher search and bibliographic disambiguation are deterministic.

## Command Interface

The helper exposes four subcommands:

```bash
python "$SKILL_DIR/scripts/manage_bibliography.py" scan \
  --project /path/to/latex-project \
  --output /path/to/latex-project/bibliography-proposal.json

python "$SKILL_DIR/scripts/manage_bibliography.py" validate \
  --proposal /path/to/latex-project/bibliography-proposal.json

python "$SKILL_DIR/scripts/manage_bibliography.py" apply \
  --proposal /path/to/latex-project/bibliography-proposal.json

python "$SKILL_DIR/scripts/manage_bibliography.py" install-aea-style \
  --project /path/to/latex-project \
  --confirm-download
```

`scan` and `validate` do not modify `.tex` or `.bib` files. `apply` accepts
only a valid proposal. `install-aea-style` refuses to access the network
without `--confirm-download`.

## Project Discovery

The scan begins from a user-selected project directory or main `.tex` file. It
follows local `\input{...}` and `\include{...}` references that remain inside
the project root, ignores commented commands, and inventories common citation
commands, including plural and author/year variants.

The helper identifies bibliography configuration as follows:

1. Detect `\addbibresource{...}` and `biblatex` or `biber` usage.
2. Otherwise detect `\bibliography{...}` and `\bibliographystyle{...}`.
3. Resolve declared bibliography paths relative to the declaring `.tex` file.
4. If exactly one active `.bib` target is found, use it.
5. If no `.bib` target exists in a traditional BibTeX project, propose
   `references.bib`.
6. If multiple active targets remain possible, stop before applying additions
   and ask the user to select one.

The parser must preserve source locations for every discovered citation and
bibliography declaration so reports can identify the relevant file and line.
It need not implement a complete TeX macro-expansion engine. Dynamic paths or
custom citation macros that cannot be resolved are reported as unsupported
rather than guessed.

## Proposal Format

The versioned JSON proposal contains:

```json
{
  "schema_version": 1,
  "project_root": "/absolute/project/path",
  "bibliography_system": "bibtex",
  "target_bib": "references.bib",
  "citations": [],
  "new_entries": [],
  "existing_entry_corrections": [],
  "inferred_references": [],
  "tex_changes": [],
  "unresolved": [],
  "verification_report": []
}
```

Each proposed entry includes:

- Citation key and BibTeX entry type.
- Normalized fields.
- Stable identifiers such as DOI, ISBN, or publication URL when available.
- Source URLs and retrieval dates for each verified field.
- Conflicts found among sources.
- Verification status and verifier identity.
- Whether user approval is required and, when applicable, its recorded state.

Statuses are explicit: `candidate`, `verified`, `needs-user-confirmation`,
`approved`, `rejected`, or `unresolved`. Validation rejects unknown statuses.

## Citation Discovery

Two discovery paths are supported:

### Explicit Citation Keys

For each key already used by a recognized citation command but absent from the
active bibliography, the agent searches for the intended work. A key alone is
not considered proof of identity. Ambiguous matches remain unresolved.

### Prose-Inferred References

The agent may identify author-year mentions, paper titles, DOI strings, or
other clear references in prose. These candidates always have
`needs-user-confirmation` status before the skill inserts a citation command or
adds an entry. The skill must show the source passage and proposed work to the
user.

## Metadata Search and Verification

The source priority is:

1. Official publisher or journal page.
2. Crossref DOI metadata.
3. A recognized journal or bibliographic index.
4. Google Scholar.

All available fields are checked, including authors and their order, year,
title, journal or book title, volume, issue, pages or article number, publisher,
edition, DOI, and URL. Required fields vary by BibTeX entry type, but the
verification process attempts to complete every applicable field.

A second agent independently verifies each candidate against online sources.
The verifier receives the candidate identity and evidence but must conduct its
own lookup rather than accepting the first agent's conclusion. On clients
without subagent support, the main agent performs a separate second pass,
discarding first-pass assumptions and repeating the lookup.

Verification succeeds only when the publication identity and all required
fields are supported. Conflicts are recorded. A lower-priority source does not
override a higher-priority source without an explicit explanation. Unresolved
material is never fabricated or written to the bibliography.

## Entry and Title Rules

New citation keys use lowercase `authorYearFirstTitleWord`, for example
`acemoglu2001colonial`. Stop words are skipped when selecting the title word.
If a key collides with a different work, the next meaningful title word is
appended until the key is unique. Numeric suffixes are not generated.

Titles use Chicago-style headline capitalization. The formatter must preserve
or add braces around content whose case BibTeX must not alter, including:

- Initialisms and abbreviations such as `{AI}` and `{U.S.}`.
- Proper names whose capitalization cannot be safely inferred.
- Case-sensitive technical terms.
- LaTeX commands and their arguments.
- Inline mathematics.

Example:

```bibtex
title = {The Effects of {AI} on {U.S.} Labor Markets}
```

The helper may flag capitalization defects mechanically, but the verifier
remains responsible for semantic case protection.

## Modification Policy

- A new entry tied to an explicit citation key may be added after independent
  verification.
- A prose-inferred reference requires user confirmation before adding either
  the citation or its entry.
- A correction to an existing entry always requires user approval. The
  proposal shows field-level before and after values.
- Existing entry order and unrelated formatting are preserved where practical.
- Duplicate DOI, ISBN, or equivalent stable identifiers are rejected even when
  citation keys differ.
- Application creates a temporary file in the destination directory, flushes
  it, and atomically replaces the destination only after complete rendering.
- `apply` writes a result report containing applied, skipped, and unresolved
  items.

## LaTeX Configuration

For a traditional BibTeX project with no bibliography configuration, the
proposal adds:

```tex
\bibliographystyle{aea}
\bibliography{references}
```

The commands are placed before `\end{document}` in the selected main document.
If another `\bibliographystyle{...}` already exists, it is preserved and a
warning is reported. The skill does not replace it automatically.

For a `biblatex` or `biber` project, the skill may maintain `.bib` entries but
does not add `\bibliographystyle`, change the bibliography backend, or install
`aea.bst` as an active style. It reports that the AEA `.bst` file is for the
traditional BibTeX workflow.

## Official AEA Style Download

The user must explicitly approve the download. The helper then:

1. Downloads the current LaTeX template archive directly from the official AEA
   template endpoint.
2. Requires HTTPS and an `aeaweb.org` host after redirects.
3. Enforces archive size, entry-count, and uncompressed-size limits.
4. Rejects absolute paths, traversal paths, links, duplicate members, and any
   archive without exactly one regular `aea.bst`.
5. Extracts only `aea.bst` to a temporary location.
6. Computes SHA-256 and records the final source URL, retrieval timestamp, and
   digest in the result report.
7. Refuses to overwrite a different local `aea.bst`; an identical digest is
   treated as already installed.

The repository must not cache, mirror, vendor, or commit the downloaded file.
If automated download fails, the skill provides the official AEA templates
page for manual download. It must not fall back to an unofficial mirror.

## Error Handling

- Missing or ambiguous main documents are reported before mutation.
- Missing bibliography targets are created only through an approved proposal.
- Unsupported dynamic TeX constructs are reported with source locations.
- Network failures leave candidates unresolved.
- Conflicting metadata is reported and not guessed.
- Invalid BibTeX, duplicate identifiers, key collisions, stale proposal input,
  or paths escaping the project root cause validation failure.
- Before applying, file digests are compared with the proposal's scan-time
  digests. Changed input files require a new scan.
- A failed apply does not leave partially rendered destination files.

## Testing Strategy

Unit tests cover:

- Comment-aware parsing of common citation and bibliography commands.
- Recursive local `\input` and `\include` discovery.
- BibTeX and `biblatex` project detection.
- Active `.bib` selection and ambiguity handling.
- Citation-key generation, stop words, and deterministic collision handling.
- Chicago headline capitalization and preservation of protected LaTeX content.
- Required fields by entry type.
- Duplicate key, DOI, and ISBN detection.
- Proposal status and approval validation.
- Stale input digest rejection.

Filesystem integration tests use temporary projects to cover:

- Creating a new `references.bib`.
- Appending verified entries without rewriting unrelated entries.
- Refusing unapproved inferred references and existing-entry corrections.
- Adding missing BibTeX commands before `\end{document}`.
- Preserving a non-AEA bibliography style.
- Warning without modifying a `biblatex` project.
- Atomic writes and result-report generation.

AEA download tests use local archive fixtures and an injected downloader. They
cover redirect host checks, malicious ZIP paths, archive limits, missing or
duplicate `aea.bst`, digest recording, identical local files, and overwrite
refusal. The default suite never accesses the network.

When BibTeX tooling is available, an optional integration test compiles a
minimal fixture using an externally supplied or test-fixture style file. It is
skipped when LaTeX is unavailable and never requires downloading AEA content.

## Documentation

The repository README lists `manage-latex-bibliography`, its intended
workflows, and its Python and network requirements. It explains that
`aea.bst` is not distributed with the skill and is downloaded from AEA only
with user approval.

`SKILL.md` contains the operational workflow and approval gates.
`verification-rules.md` defines source priority, required evidence, and
conflict handling. `title-case-rules.md` documents headline capitalization and
BibTeX case protection.

The temporary feature note currently at the end of the README is removed when
the implementation documentation replaces it.

## Acceptance Criteria

The feature is complete when:

1. The new canonical skill passes repository structure and portability checks.
2. A scan identifies missing explicit citation keys and separately reports
   prose-inferred references.
3. New entries cannot be applied without independent verification.
4. Inferred citations and corrections to existing entries cannot be applied
   without user approval.
5. Generated keys and titles follow the agreed deterministic rules.
6. The correct active `.bib` file is selected or ambiguity stops application.
7. Traditional BibTeX configuration is added only when absent; existing styles
   and `biblatex` configuration are preserved.
8. `aea.bst` is absent from the repository and can be downloaded only with
   explicit confirmation from the official AEA host.
9. All changes produce a verification and application report.
10. Offline tests cover parsing, validation, file application, and secure AEA
    archive extraction.

## Deferred Scope

- Converting a project between BibTeX and `biblatex`.
- Replacing an existing bibliography style automatically.
- Supporting arbitrary custom citation macros or full TeX macro expansion.
- Automatically resolving genuine metadata conflicts.
- Redistributing or mirroring AEA template files.
- Treating Google Scholar as an automated API.
