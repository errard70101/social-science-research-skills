# Zotero Local Write Safety

Use this reference when an authorization, concurrency, deletion, or recovery
question arises. The bundled helper implements the constraints below; do not
replace it with ad hoc API calls.

## Official API behavior

- Local API overview and authorization:
  <https://www.zotero.org/support/dev/web_api/v3/local_api>
- Write requests, object versions, batch writes, and update semantics:
  <https://www.zotero.org/support/dev/web_api/v3/write_requests>
- Collection and tag behavior:
  <https://www.zotero.org/support/collections_and_tags>

Reads from the loopback Local API need no API key. A write first retrieves
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

## Concurrency and arrays

Plans record the Zotero server identity, object versions, and complete
before/after arrays. Apply re-reads current state before authorization and
aborts on any mismatch. Item updates are checked again after the authorization
dialog before the one-time key is consumed.

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
4. a valid one-time or user-approved remembered Zotero authorization;
5. a second hierarchy and membership check after the authorization dialog and
   immediately before DELETE.

After deletion, the helper checks that every planned collection is absent and
that affected items still exist with the expected remaining memberships. The
receipt stores the collection tree and affected memberships needed for manual
reconstruction. It does not claim that deletion can be automatically undone.

## Failure handling

- Before authorization: stop, prepare a new plan if needed, and make no write.
- Authorization denied or secure credential storage unavailable: stop without
  retrying.
- Stored key rejected with `401`: remove it and stop; a later apply can request
  fresh authorization.
- HTTP conflict or changed version: stop and create a new plan.
- Write response or verification failure: preserve the evidence, inspect state
  with GET requests, and ask the user before any corrective write.
- Existing plan or receipt path: choose a new path; never overwrite the old
  record.
