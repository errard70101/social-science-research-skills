---
name: manage-zotero-library
description: "Safely organize a user's personal Zotero library with reviewable plans and approved tag, collection-membership, and collection changes. Uses the Local API by default, with an opt-in official Zotero Web API backend whose key stays in a recognized OS credential store. On GET-only Local API versions, require manual Zotero Desktop application. Also use for Desktop-first PDF import guidance. Supports exact approval, version checks, delete confirmation, verification, and receipts. Never deletes Zotero items or attachments."
metadata:
  requires: [zotero-read]
---

# Manage Zotero Library

Organize the researcher's Zotero library through a strict
plan-review-approve-apply-verify workflow. Use the read-capability skill to find
items and collections; use this skill only for approved organization changes.
The helper uses the Local API by default and detects local write support at
runtime. The official Web API is an explicit alternative for a personal
library; it is never selected automatically.

Before running the bundled script, locate this skill directory and
assign its absolute path to `SKILL_DIR`.

## Scope

Supported:

- Add or remove tags on top-level bibliographic items.
- Add or remove those items from collections.
- Plan different tag and collection changes per item from a reviewed manifest.
- Create a collection.
- Rename or move a collection.
- Delete a collection after reviewing its full cascade impact.
- Delete multiple root collections atomically through one approved Web API plan.

Not supported:

- The bundled helper does not upload local PDFs, create attachments, or retrieve
  bibliographic metadata for new PDF files.
- Never delete Zotero items or attachments.
- Never use Zotero's “Delete Collection and Items” operation.
- Never empty Trash, merge duplicates, or edit title, author, year, DOI, or
  other core bibliographic metadata.
- Before recommending a manual DOI correction, resolve both values through
  DOI.org or Crossref and check for a DOI alias. A publisher landing page alone
  is not enough evidence that the library value is wrong.
- Never use a third-party MCP server or direct SQLite writes.
- Do not manage group libraries through the Web API backend.

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

Keep the default Local API unless the user explicitly opts in to the official
Web API. Before the first Web API plan, have the user create a key at Zotero's
[API Keys](https://www.zotero.org/settings/keys) page with personal-library
write access, then store it under a non-secret profile name:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" web-auth-store \
  --web-profile research
```

The command prompts for the key without echoing it, calls `/keys/current`, and
stores it only after confirming the returned user ID and personal-library
`library: true` and `write: true` access. If terminal echo cannot be disabled,
the command stops before reading the key or initializing a Web API client.
Never place the key in a command-line argument, environment variable, plan,
receipt, chat, log, or repository file. If no recognized OS credential store
is available, Web API use is blocked.

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

For a heterogeneous batch, prepare a JSON array with one exact item key per
entry. Each optional operation field is an array of strings:

```json
[
  {
    "key": "ABCD2345",
    "add_collections": ["Macroeconomics"],
    "remove_collections": ["0 Inbox"]
  },
  {
    "key": "BCDE3456",
    "add_tags": ["reviewed"],
    "add_collections": ["Finance"]
  }
]
```

Create one signed plan without composing internal helper calls:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-items-manifest \
  ".zotero-management/item-manifest.json" \
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

For two or more independent root collections on the Web API backend, create
one atomic plan so the first deletion cannot invalidate a second approved
plan. Do not include both an ancestor and its descendant:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" plan-collections-delete \
  QRST9876 RSTU8765 \
  --backend web --web-profile research \
  --output ".zotero-management/delete-batch-plan-<timestamp>.json"
```

Planning performs only GET requests. If it reports a no-op, ambiguous
collection, child attachment/note, or more than 50 item updates, stop and
revise the request rather than bypassing the check.

For an explicitly selected Web API operation, add the same two options to any
planning command:

```bash
--backend web --web-profile research
```

Inspect these plan fields before presenting an apply path:

- `local_api_write_supported: true` and `application_mode: local_api` mean the
  running Zotero returned the `Zotero-Server-ID` required by the official local
  write protocol. Continue with the approval and Local API apply workflow.
- `local_api_write_supported: false` and
  `application_mode: manual_zotero_desktop` mean the running Zotero is still
  GET-only. The plan remains reviewable, but the helper cannot apply it.
- `api_backend: web`, `application_mode: web_api`, `library`, and
  `web_profile` bind an opted-in Web plan to the user ID returned by
  `/keys/current` and to the named OS credential profile.

Do not infer capability from a Zotero version number or from online
documentation alone. The current runtime response is authoritative.

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
delete confirmation equal to the target collection key. A multi-collection
plan uses the exact comma-separated key sequence recorded in
`requires_delete_confirmation`. A general “yes” is insufficient.

### 4. Apply the unchanged plan

For a `manual_zotero_desktop` plan, do **not** run `apply`. Tell the user that
their current Zotero Local API is GET-only, then have the user perform only the
approved change in Zotero Desktop. For collection membership removal, use
**Remove Item(s) from Collection…**, not **Move Item(s) to Trash…**. For
collection deletion, use **Delete Collection…**, never **Delete Collection and
Items…**. After the user acts, continue to read-only verification in step 6.

For a `local_api` plan, continue with the commands below.

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

For a reviewed multi-collection Web plan, pass its exact recorded confirmation
sequence, for example `--confirm-delete QRST9876,RSTU8765`.

For a `web_api` plan, use the same command with the backend and the exact
credential profile recorded in the plan:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" apply \
  ".zotero-management/item-plan-<timestamp>.json" \
  --backend web \
  --web-profile research \
  --approve EXACT_PLAN_ID \
  --receipt ".zotero-management/item-receipt-<timestamp>.json"
```

The helper revalidates `/keys/current` before applying, rejects a different
user ID or credential profile, and sends only versioned writes. It never calls
`/local/authorize` for Web API plans. Revoked or insufficient keys stop the
operation without an automatic write retry. A `401` or `403` write rejection
does not remove the stored profile; inspect it with `web-auth-status` and use
`web-auth-forget` only after the user explicitly requests removal.

The helper checks the Zotero database identity and current versions before
requesting authorization. It rechecks item state after the authorization
dialog; for deletion, it rechecks the full cascade immediately before DELETE.
Web delete plans bind the complete tree-and-membership impact snapshot to one
library version and use Zotero's library-versioned multi-object collection
DELETE, so intervening library-wide drift makes the write fail atomically.
If state drift is detected, do not retry or patch the plan. Prepare a fresh
plan and request approval again.

### 5. Inspect or disable remembered authorization

These commands apply only when the running Zotero supports Local API writes.
On a GET-only runtime, there can be no local write authorization for this
helper to inspect or forget.

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

For an opted-in Web API profile, inspect or remove only that profile's stored
credential:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" web-auth-status \
  --web-profile research
python "$SKILL_DIR/scripts/zotero_manager.py" web-auth-forget \
  --web-profile research
```

`web-auth-forget` removes the local credential but does not revoke the key on
zotero.org. The user revokes it from Zotero's API Keys settings. Do not infer
permission to store, retain, remove, or revoke a Web API key.

### 6. Verify and report

For a `manual_zotero_desktop` plan, wait until the user confirms that the
Desktop action is complete. Then use the `zotero-read` provider to re-read the
exact planned item or collection keys and compare the current state with the
plan. For deletion, confirm that every planned collection is absent and every
affected item still exists with its planned remaining memberships. Report the
plan ID, changed keys, `application_mode`, and comparison result. Do not claim
that the helper produced a receipt or an `authorization_mode` for a manual change.

For a `local_api` or `web_api` plan, the helper re-reads every changed object.
Treat the operation as complete only when the receipt says `"verified": true`.
Report the receipt path, plan ID, changed keys, backend, library binding,
`authorization_mode`, and verification result. A delete receipt includes a
reconstruction snapshot because deleting a collection is not automatically
reversible.

If the write succeeded but verification or receipt creation failed, report the
uncertain state immediately and perform read-only inspection. Never repeat the
write automatically.

If an item update or collection deletion returns HTTP 5xx or times out after
submission, the CLI reports an indeterminate outcome with the plan ID. Before
any retry, inspect the unchanged plan using GET requests only:

```bash
python "$SKILL_DIR/scripts/zotero_manager.py" inspect-plan-state \
  ".zotero-management/delete-plan-<timestamp>.json" \
  --backend web --web-profile research \
  --output ".zotero-management/delete-inspection-<timestamp>.json"
```

Retry only when the inspection reports `outcome: not_applied`,
`safe_to_retry: true`, and the user approves the retry. An `applied` result is
complete after verification; an `indeterminate` result requires manual review.

## Safety Rules

- Local requests stay on `http://localhost:23119/api/`. Opted-in Web requests
  stay on `https://api.zotero.org/`. The helper rejects every other host, port,
  scheme, and path.
- Treat the presence of `Zotero-Server-ID` on the live Local API response as
  the write-capability gate. A missing header keeps the helper in GET-only
  planning mode and must stop authorization and apply before any write request.
- Never print, commit, or place a local API key in a plan, receipt, environment
  file, or repository. One-time keys remain only in process memory; remembered
  keys may be stored only in a recognized system credential store.
- Never print, commit, or place a Web API key in arguments, plans, receipts,
  environment variables, logs, chat, or repository files. Store it only under
  the selected profile in a recognized system credential store, and validate
  personal-library write scope through `/keys/current` before planning or
  applying.
- Do not treat a plan file as authorization. Require the exact plan ID supplied
  by the user after review.
- Do not infer permission to enable, retain, or forget remembered authorization.
- Preserve complete `tags` and `collections` arrays; Zotero interprets those
  arrays as full replacement values.
- Compare tags and collection memberships order-insensitively during drift
  checks and verification. Zotero can return the same values in a different
  order.
- Stop on version conflicts, unexpected HTTP responses, malformed results, or
  failed post-write verification.
- Never apply more than one plan under a single approval.
- Do not perform a live write merely to test this skill. Use mocked requests in
  development.
- Keep `.zotero-management/` ignored by default because plans and receipts can
  contain private library titles and collection paths. Export them deliberately
  when an external audit record is required.

Read `references/write-safety.md` before troubleshooting authorization,
versions, collection deletion, or recovery.

## Dependencies

Use Python 3.10 or newer with `httpx` and `keyring`. Local API use requires
Zotero Desktop to be running with “Allow other applications on this computer
to communicate with Zotero” enabled. Web API use requires network access and a
recognized OS credential store. The `zotero-read` capability is required for
target discovery and is installed automatically with this skill by the
repository installer.
