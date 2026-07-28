# Zotero Local API Boundaries

## Official behavior

- Local API documentation:
  <https://www.zotero.org/support/dev/web_api/v3/local_api>
- Read endpoint and search documentation:
  <https://www.zotero.org/support/dev/web_api/v3/basics>
- Zotero data directory and attachment overview:
  <https://www.zotero.org/support/zotero_data>

The Zotero desktop client exposes an implementation of API version 3 at
`http://localhost:23119/api/`. It requires Zotero to be running and the
Advanced preference allowing local applications to communicate with Zotero.
It does not require authentication, works offline, and must not be exposed
beyond the loopback interface.

The helper intentionally supports only the personal library through user ID
`0`. It never sends a non-GET request, authentication header, or API key. It
accepts only HTTP loopback base URLs on Zotero's standard port `23119`, without
credentials, query parameters, or fragments.

## Endpoints used

| Purpose | Endpoint |
| --- | --- |
| Connection check | `/api/` |
| Collection discovery | `/api/users/0/collections` |
| Whole-library search | `/api/users/0/items/top` |
| Collection search | `/api/users/0/collections/{key}/items/top` |
| Item metadata | `/api/users/0/items/{key}` |
| Child attachments and notes | `/api/users/0/items/{key}/children` |
| PDF annotations | `/api/users/0/items?itemType=annotation` |
| Local attachment URL | `/api/users/0/items/{key}/file/view/url` |

Search calls set `qmode=everything`. This lets Zotero use indexed full text, but
the `q` parameter is phrase-oriented. Prefer several short, meaningful queries
over one long natural-language question.

The helper caps returned candidates but reads Zotero's `Total-Results` response
header. If `truncated` is true, refine the query or deliberately raise the
limit before treating the candidate set as adequate.

## Notes and annotations

Zotero child notes are returned with the bibliographic item's other children.
PDF annotations are API items whose `parentItem` points to an attachment.
Zotero does not reliably return them from the attachment's `/children`
endpoint, so the helper retrieves annotation items in pages of 100 and filters
them locally to the target item's PDF attachment keys.

The `annotations` command omits raw note HTML and annotation position geometry.
It returns readable note text plus the annotation type, selected text, comment,
color, displayed page label, sort index, tags, and modification date. Note text
and annotation comments are researcher-authored context. An annotation's
selected text can help locate evidence, but it does not replace checking the
paper and its page.

## Collection resolution

Collections are resolved at runtime from their names and
`parentCollection` keys. A path such as `Projects / ITS` identifies a nested
collection. A bare collection name is accepted only when it is unique. An exact
eight-character Zotero collection key is also accepted.

Use the bundled `collections` command to discover paths, keys, and the item
counts reported by Zotero. Do not write a separate Local API client.

Project instructions may contain a preferred collection as an efficiency hint.
They are not configuration requirements and are not a second source of truth.
Zotero remains authoritative.

## Attachment handling

The Local API returns a `file://` URL for an attachment on disk. The helper
rejects relative or decorated file URLs, percent-decodes an absolute URL, and
returns only the decoded native `path`. It handles:

- POSIX paths used by macOS and Linux;
- Windows drive-letter paths;
- Windows UNC paths;
- spaces and Unicode file names.

Never derive an attachment path from a guessed Zotero data directory. Stored
attachments are generally the most portable. Linked attachments work only when
their target is valid on the current computer.

Never search the home directory, Zotero data directory, or local disks for an
alternative copy. Read only the exact decoded paths returned by the helper.

An item can match Zotero's full-text index even when its PDF is not currently
available. Treat such an item as metadata-only evidence until the file exists
locally and its text has been extracted.

## Diagnostics

- Connection refused: start Zotero Desktop.
- HTTP 403: enable local application access in Zotero Settings, under Advanced.
- Missing or ambiguous collection: correct the name or use its full nested path.
- Missing attachment: make the PDF available locally; do not rewrite its path.
- Empty extracted pages: install optional PyMuPDF to retry font-encoding
  failures; an image-only PDF may still require OCR.
