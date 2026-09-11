---
name: annotate-zotero-pdf
description: "Create Zotero-native PDF highlights and underlines from exact passages through the official Local API. Use when the user wants to mark text in PDFs already attached to their personal Zotero library, optionally adding a comment, color, and tags. Plans up to 50 annotations as one reviewable batch, requires one exact batch approval rather than per-annotation confirmation, rechecks PDF geometry and library state, and verifies every created annotation."
metadata:
  requires: [manage-zotero-library, zotero-read]
---

# Annotate Zotero PDF

Create native Zotero highlights and underlines in PDFs that are already stored
in the user's personal library. Treat one reviewed manifest of at most 50 marks
as one operation: present one batch plan ID and never request approval for each
annotation separately.

Before running the bundled script, locate this skill directory and assign its absolute path to `SKILL_DIR`.

## Scope

Supported in the first version:

- yellow or custom-color highlights;
- underlines;
- an optional annotation comment;
- zero or more annotation tags;
- multiple marks across multiple existing PDF attachments in one batch.

Not supported:

- importing PDFs or creating attachments;
- free-text, image, ink, or area annotations;
- editing or deleting existing annotations;
- group libraries or the Zotero Web API;
- OCR or approximate/fuzzy passage matching.

Use the installed `zotero-read` provider to find the exact bibliographic item
and PDF attachment keys. Use `manage-zotero-library` for tags and collections
on bibliographic items; do not stretch this annotation helper into general
library management.

## Workflow

### 1. Build the manifest

Prepare a private JSON array following `references/manifest-format.md`. Each
entry must name an exact PDF attachment key, a one-based PDF page, the exact
passage, `highlight` or `underline`, and a six-digit hex color. A comment and
tags are optional.

Page means the one-based page in the PDF file, not the printed journal page or
Zotero page label. The exact passage must occur once on that page. If the text
is missing or repeated, refine the passage instead of guessing a location.

### 2. Create a GET-only batch plan

Choose new project-local paths. The helper creates parent directories and
refuses to overwrite existing files.

```bash
python "$SKILL_DIR/scripts/annotate_zotero_pdf.py" plan \
  ".zotero-management/annotation-manifest.json" \
  --output ".zotero-management/annotation-plan-<timestamp>.json"
```

Planning uses only GET requests. It validates the attachment, PDF hash, page
geometry, unique text location, current annotations, Zotero database identity,
and current library and attachment versions. It rejects rotated or unsupported
page geometry and an annotation that already exists.

Do not perform a live write merely to test the helper. Development tests must
use mocked Local API requests and disposable PDFs.

### 3. Review once for the batch

Show the user:

- the exact plan ID;
- the number of annotations and attachments;
- for every entry, attachment key, PDF page, type, passage, color, comment, and
  tags.

Ask for approval of the exact batch plan ID once. Do not ask for separate
confirmation for each annotation. The original request and the manifest alone
are not approval of the generated plan. A batch may contain at most 50 marks;
prepare another plan for the remainder.

### 4. Apply and verify the unchanged batch

```bash
python "$SKILL_DIR/scripts/annotate_zotero_pdf.py" apply \
  ".zotero-management/annotation-plan-<timestamp>.json" \
  --approve EXACT_PLAN_ID \
  --receipt ".zotero-management/annotation-receipt-<timestamp>.json"
```

When no valid remembered authorization exists, Zotero displays one Local API
authorization dialog for the batch:

- **Allow** grants the next successful write.
- **Always Allow** lets the shared Zotero management helper securely reuse the
  authorization from the operating-system credential store.

The user chooses whether to remember authorization. Never choose **Always
Allow** for them. A remembered authorization avoids repeated Zotero dialogs;
it does not replace the exact plan-ID approval for each batch.

Immediately before and after authorization, the helper rechecks database
identity, versions, attachment file hashes, passage geometry, and duplicates.
It then submits the unchanged batch with one versioned POST, never blindly
retries it, reads every created annotation back, and reports success only when
the receipt has `"verified": true`.

If a write times out, returns a server error, is incomplete, or fails readback
verification, report the state as uncertain and inspect with GET requests. Do
not repeat the write automatically.

## Safety Rules

- Use only the official loopback Local API at
  `http://localhost:23119/api/`; never use a third-party MCP server or direct
  SQLite writes.
- Treat the live `Zotero-Server-ID` response header as the write-capability
  gate. Without it, do not authorize or apply.
- Never put a Local API key in arguments, environment variables, manifests,
  plans, receipts, logs, chat, or repository files. Authentication is delegated
  to the installed `manage-zotero-library` helper.
- Never alter the plan after approval. Prepare and review a new plan after any
  content or state change.
- Never add an annotation when the passage match or page geometry is ambiguous.
- Never exceed one versioned POST for an approved batch and never reuse one
  approval for another plan.
- Keep `.zotero-management/` ignored because manifests, plans, and receipts can
  contain private article text and local file paths.

## Dependencies

Use Python 3.10 or newer with `httpx`, `keyring`, and PyMuPDF 1.24 or newer.
Zotero Desktop must be running with local application access enabled. The
repository installer automatically installs `manage-zotero-library` and the
`zotero-read` provider with this skill.
