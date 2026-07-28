---
name: manage-zotero-library
description: "Safely organize a user's personal Zotero library through the official Local API by preparing reviewable plans and, only after exact approval, adding or removing tags and collection memberships or creating, renaming, moving, and deleting collections. Also use when a researcher asks how to import a PDF, a folder of PDFs, or a large PDF collection: provide the Desktop-first stored-file workflow documented here, then offer to audit and organize the imported items. Supports user-selected one-time or securely remembered authorization, concurrency checks, delete-specific confirmation, post-write verification, and durable receipts. Never deletes Zotero items or attachments."
metadata:
  requires: [zotero-read]
---

# Manage Zotero Library

Organize the researcher's Zotero library through a strict
plan-review-approve-apply-verify workflow. Use the read-capability skill to find
items and collections; use this skill only for approved organization changes.

Before running the bundled script, locate this skill directory and
assign its absolute path to `SKILL_DIR`.

## Scope

Supported:

- Add or remove tags on top-level bibliographic items.
- Add or remove those items from collections.
- Create a collection.
- Rename or move a collection.
- Delete a collection after reviewing its full cascade impact.

Not supported:

- The bundled helper does not upload local PDFs, create attachments, or retrieve
  bibliographic metadata for new PDF files.
- Never delete Zotero items or attachments.
- Never use Zotero's “Delete Collection and Items” operation.
- Never empty Trash, merge duplicates, or edit title, author, year, DOI, or
  other core bibliographic metadata.
- Never use the Web API, a third-party MCP server, or direct SQLite writes.

## Bulk PDF import guidance

When a user asks how to import one PDF, a folder, or hundreds of PDFs, recommend
Zotero Desktop rather than implying that this skill's Local API helper performs
the import:

1. Create a temporary collection such as `0 Inbox / <date> PDF Import`.
2. Open the source folder, select the PDF files, and drag them normally into
   that collection. Normal dragging creates stored-file copies. Do not hold
   **Command+Option** on macOS or **Ctrl+Shift** on Windows/Linux because those
   modifiers create linked files instead.
3. For a large folder, suggest operational batches of **50–100 PDFs** so the
   user can observe recognition and isolate failures. State that this is a
   practical recommendation, not a Zotero limit.
4. Explain that Zotero normally attempts to retrieve metadata, create parent
   bibliographic items, and rename imported PDFs. Files it cannot identify
   remain standalone PDF attachments for later review.
5. Keep the source files unchanged until the user has verified item counts,
   opened sample PDFs, and completed their configured file sync. Never infer
   permission to delete the originals.
6. If the source has nested folders, ask whether their hierarchy matters.
   Import each folder into a mapped collection when it does; otherwise gather
   the PDFs into the temporary collection without promising that Zotero will
   reproduce the filesystem hierarchy.
7. After import, use the `zotero-read` provider to audit recognized and
   standalone items. Use this skill's normal plan-review-approve workflow for
   requested tags and collection memberships.

When giving this guidance, link to Zotero's official
[Adding Files](https://www.zotero.org/support/attaching_files) and
[Retrieve PDF Metadata](https://www.zotero.org/support/retrieve_pdf_metadata)
documentation. Clearly say that the current bundled helper does not upload
local PDFs; do not describe a future API importer as an available feature.

## Workflow

### 1. Resolve exact targets

Use the installed skill that provides `zotero-read` to search, list
collections, and identify exact item or collection keys. Do not search the
filesystem for PDFs or infer a target from a duplicate collection name.
Summarize the requested operation and exact targets before planning.

### 2. Prepare a read-only plan

Choose a new, project-local JSON path for every plan. The helper creates parent
directories but refuses to overwrite an existing file.

Tags and memberships:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-items \
  ABCD2345 BCDE3456 \
  --add-tag "reviewed" \
  --remove-tag "to-read" \
  --add-collection "0 Working Projects / ITS" \
  --remove-collection CDEF4567 \
  --output ".zotero-management/item-plan-<timestamp>.json"
```

Collection creation:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-collection-create \
  "New Project" \
  --parent "0 Working Projects" \
  --output ".zotero-management/create-plan-<timestamp>.json"
```

Collection rename or move:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-collection-update \
  DM2F65CA \
  --name "Interrupted Time Series" \
  --parent "0 Working Projects" \
  --output ".zotero-management/update-plan-<timestamp>.json"
```

Use `--root` instead of `--parent` to move a collection to the library root.

Collection deletion:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-collection-delete \
  QRST9876 \
  --output ".zotero-management/delete-plan-<timestamp>.json"
```

Planning performs only GET requests. If it reports a no-op, ambiguous
collection, child attachment/note, or more than 50 item updates, stop and
revise the request rather than bypassing the check.

### 3. Review with the user

Show the exact plan ID and a readable summary of every before/after change.
The initial request to manage Zotero is not approval of the generated plan.
Wait for the user to approve that exact plan ID after seeing it.

For deletion, also show:

- target key and full path;
- every descendant collection that will also be deleted;
- affected item count and titles;
- which items will become Unfiled;
- confirmation that `items_deleted` is zero.

Deletion needs two explicit values: the approved plan ID and a separate
delete confirmation equal to the target collection key. A general “yes” is
insufficient.

### 4. Apply the unchanged plan

Before applying, tell the user that Zotero will display an authorization
dialog when no valid remembered authorization exists. Explain both choices:

- **Allow** grants only the next successful write.
- **Always Allow** supports repeated operations without another dialog. The
  helper accepts it only when the key can be saved in a recognized system
  credential store: macOS Keychain, Windows Credential Locker, Linux Secret
  Service/libsecret, or KWallet.

Never choose `Always Allow` on the user's behalf. The user must make that
choice in Zotero after learning that the remembered key is unscoped and can
write to any library they can edit. A remembered key removes repeated Zotero
dialogs, but it never removes the plan ID approval required for each operation.

For non-delete operations:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" apply \
  ".zotero-management/item-plan-<timestamp>.json" \
  --approve EXACT_PLAN_ID \
  --receipt ".zotero-management/item-receipt-<timestamp>.json"
```

For a collection deletion:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" apply \
  ".zotero-management/delete-plan-<timestamp>.json" \
  --approve EXACT_PLAN_ID \
  --confirm-delete QRST9876 \
  --receipt ".zotero-management/delete-receipt-<timestamp>.json"
```

The helper checks the Zotero database identity and current versions before
requesting authorization. It rechecks item state after the authorization
dialog; for deletion, it rechecks the full cascade immediately before DELETE.
If state drift is detected, do not retry or patch the plan. Prepare a fresh
plan and request approval again.

### 5. Inspect or disable remembered authorization

Check only whether the current Zotero database has a securely stored key:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" auth-status
```

After the user explicitly asks to stop remembered access, remove this skill's
local credential:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" auth-forget
```

`auth-forget` prevents this skill from reusing the key but does not revoke
Zotero's copy. For full revocation, instruct the user to click
**Clear Write Authorizations** in Zotero Settings → Advanced. That Zotero
action revokes all remembered local write authorizations, not only this skill's
key. Unchecking local application access disables the entire Local API,
including reads.

### 6. Verify and report

The helper re-reads every changed object. Treat the operation as complete only
when the receipt says `"verified": true`. Report the receipt path, plan ID,
changed keys, `authorization_mode`, and verification result. A delete receipt
includes a reconstruction snapshot because deleting a collection is not
automatically reversible.

If the write succeeded but verification or receipt creation failed, report the
uncertain state immediately and perform read-only inspection. Never repeat the
write automatically.

## Safety Rules

- Keep every request on `http://localhost:23119/api/`; the helper rejects other
  hosts, ports, schemes, and paths.
- Never print, commit, or place a local API key in a plan, receipt, environment
  file, or repository. One-time keys remain only in process memory; remembered
  keys may be stored only in a recognized system credential store.
- Do not treat a plan file as authorization. Require the exact plan ID supplied
  by the user after review.
- Do not infer permission to enable, retain, or forget remembered authorization.
- Preserve complete `tags` and `collections` arrays; Zotero interprets those
  arrays as full replacement values.
- Stop on version conflicts, unexpected HTTP responses, malformed results, or
  failed post-write verification.
- Never apply more than one plan under a single approval.
- Do not perform a live write merely to test this skill. Use mocked requests in
  development.

Read `references/write-safety.md` before troubleshooting authorization,
versions, collection deletion, or recovery.

## Dependencies

Use Python 3.10 or newer with `httpx` and `keyring`. Zotero Desktop must be
running with “Allow other applications on this computer to communicate with
Zotero” enabled. The `zotero-read` capability is required for target discovery
and is installed automatically with this skill by the repository installer.
