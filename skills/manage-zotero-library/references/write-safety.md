# Zotero Write Safety

Use this reference when an authorization, concurrency, deletion, or recovery
question arises. The bundled helper implements the constraints below; do not
replace it with ad hoc API calls.

## Official Local API behavior

- Local API overview and authorization:
  <https://www.zotero.org/support/dev/web_api/v3/local_api>
- Write requests, object versions, batch writes, and update semantics:
  <https://www.zotero.org/support/dev/web_api/v3/write_requests>
- Collection and tag behavior:
  <https://www.zotero.org/support/collections_and_tags>

Current official documentation describes Local API writes, but older installed
Zotero versions can still expose the earlier GET-only implementation. Every
response from a write-capable implementation includes `Zotero-Server-ID`, and
the server ID is required on write requests. The helper therefore uses that
header as a runtime capability gate rather than assuming documentation and the
installed application update simultaneously.

When the header is absent, planning remains GET-only and the plan records
`local_api_write_supported: false` plus
`application_mode: manual_zotero_desktop`. Applying that plan is blocked before
authorization or any further HTTP request. The user performs the approved
change in Zotero Desktop, followed by read-only verification of the exact
planned keys through the `zotero-read` provider. A manual change has no helper
receipt or write-authorization mode.

When the header is present, reads need no API key. A write first retrieves the
`Zotero-Server-ID`, then calls `/api/local/authorize`. The returned key is
partitioned by that server ID and is never included in plans, receipts, logs,
or command output.

Zotero's **Allow** choice grants the current request. **Always Allow** creates a
remembered key without fine-grained permissions. The skill accepts the latter
only after the user selects it in Zotero and only when Python `keyring` exposes
a recognized operating-system credential store:

- macOS Keychain;
- Windows Credential Locker;
- Linux Secret Service/libsecret;
- Linux KWallet.

Null, failure, chained, plaintext, and unknown third-party keyring backends are
rejected. A one-time key remains only in process memory. A remembered key is
saved under a service-specific name and the Zotero server ID, never in the
repository or an environment variable.

On later approved plans, the helper reuses the stored key without opening the
Zotero dialog. If Zotero returns `401`, the helper removes the stale local
credential and stops without automatically retrying the write.

`auth-forget` removes the helper's local credential only. Full revocation
requires **Clear Write Authorizations** in Zotero Settings → Advanced, which
revokes all remembered local write keys. Restarting Zotero does not revoke
them.

## Opt-in official Web API behavior

The Web API backend is never automatic. The user must explicitly choose
`--backend web` and a non-secret `--web-profile` on both planning and apply
commands. The helper accepts only `https://api.zotero.org/`; redirects and
alternate hosts, ports, paths, user information, queries, and fragments are
rejected.

Relevant official documentation:

- Web API resources and personal-library URL prefixes:
  <https://www.zotero.org/support/dev/web_api/v3/basics>
- `/keys/current` access validation and version headers:
  <https://www.zotero.org/support/dev/web_api/v3/syncing>
- Write permissions, versioned requests, batch limits, and array semantics:
  <https://www.zotero.org/support/dev/web_api/v3/write_requests>

The key is entered only through the hidden prompt of `web-auth-store`. The
helper treats Python's `GetPassWarning` as fatal: if terminal echo cannot be
disabled, it stops before fallback input, credential-store access, or any
Zotero request. The helper does not accept the key as a command-line option or
environment variable. Before storage, it calls `/keys/current` with the
candidate key and requires a positive `userID` plus personal-library
`library: true` and `write: true` access. Group permissions do not substitute
for personal-library write access.

Web API keys are always persistent credentials. They may be stored only in the
same recognized OS credential-store families accepted for remembered Local API
authorization, under a backend-specific service and the selected profile name.
The key never appears in a plan, receipt, status response, log, or error. If a
recognized secure store is unavailable, the helper refuses Web API use rather
than falling back to plaintext, an environment variable, or a repository file.

Every Web plan records `api_backend: web`, `application_mode: web_api`, the
personal-library user ID, and `web_profile`. Apply requires an explicit Web
backend selection, revalidates `/keys/current`, and rejects a different profile
or user ID before reading or writing planned objects. Web writes use the bound
`/users/<userID>/...` prefix, never Local API `/users/0/...`, and never call
`/local/authorize`.

Item batch updates include each object's reviewed `version`. Collection
creation uses `If-Unmodified-Since-Version` with the planned library version;
collection updates include the reviewed object version. A Web delete plan
requires the collection and affected-item snapshots to report the same library
version, then uses the multi-object collection DELETE with `collectionKey` and
`If-Unmodified-Since-Version` set to that library version. This prevents a
new descendant or changed membership from entering the cascade after review.
The helper omits `Zotero-Write-Token` because Zotero documents it as redundant
for versioned writes.

`web-auth-forget` removes only the selected local credential profile. The key
continues to exist until the user revokes it on Zotero's API Keys settings
page. Never infer permission to store, retain, forget, or revoke a Web API key.

## Concurrency and arrays

Plans record the applicable Local server identity or Web user/profile binding,
object versions, and complete before/after arrays. Apply re-reads current state
before authorization and aborts on any mismatch. Local item updates are
checked again after the authorization dialog before the one-time key is
consumed. Web API apply has no interactive authorization pause and relies on
the immediate state check plus versioned writes.

For item updates, `tags` and `collections` are complete arrays, not incremental
patch operations. Omitting an existing value removes it. The helper therefore
merges requested additions/removals into the complete current arrays during
planning and writes only the reviewed result.

Zotero accepts at most 50 objects in a batch write. The helper applies the same
limit to an item plan.

## Collection deletion

Deleting a collection also deletes its subcollections, but not the library
items filed in them. Items with no remaining memberships become Unfiled. A
delete plan therefore enumerates every descendant and paginates through all
top-level items before it reports impact.

Applying deletion requires:

1. exact approval of the signed plan ID;
2. a separate confirmation equal to the target collection key;
3. unchanged collection hierarchy and memberships;
4. a valid Local authorization or a revalidated, securely stored Web API key;
5. for Local API writes, a second hierarchy and membership check after the
   authorization dialog and immediately before DELETE;
6. for Web API writes, one consistent library-version snapshot plus an atomic
   library-version guard on the multi-object collection DELETE.

After deletion, the helper checks that every planned collection is absent and
that affected items still exist with the expected remaining memberships. The
receipt stores the collection tree and affected memberships needed for manual
reconstruction. It does not claim that deletion can be automatically undone.

## Failure handling

- Missing `Zotero-Server-ID`: preserve the manual plan, do not request
  authorization, and route application through Zotero Desktop.
- Before authorization: stop, prepare a new plan if needed, and make no write.
- Authorization denied or secure credential storage unavailable: stop without
  retrying.
- Stored key rejected with `401`: remove it and stop; a later apply can request
  fresh authorization.
- Web key invalid or without personal-library write scope: stop before library
  access; never fall back to group scope or a different profile.
- Web key rejected during a write: preserve the selected stored profile and
  stop without retrying. Direct the user to `web-auth-status`; remove it only
  through the explicit `web-auth-forget` flow.
- HTTP conflict or changed version: stop and create a new plan.
- Write response or verification failure: preserve the evidence, inspect state
  with GET requests, and ask the user before any corrective write.
- Existing plan or receipt path: choose a new path; never overwrite the old
  record.
