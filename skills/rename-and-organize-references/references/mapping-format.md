# Rename Mapping Format

## Top-Level Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Must be `1`. |
| `root` | string | Absolute reference-directory path. |
| `generated_at` | string | UTC ISO 8601 generation time. |
| `items` | array | Reviewed rename operations. |
| `unresolved` | array | Files that cannot yet be applied. |

## Item Fields

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Existing path relative to `root`. |
| `destination` | string | Planned path relative to `root`. |
| `kind` | string | `main-paper`, `appendix`, `slides`, or `replication`. |
| `confidence` | string | Must be `high` before application. |
| `metadata` | object | Title, year, ordered authors, DOI, and source. |

## Review Checklist

- Confirm the DOI belongs to the source paper.
- Confirm author order and family names.
- Confirm publication year and title.
- Confirm appendix, slides, and replication materials belong to the main paper.
- Resolve or remove every `unresolved` entry.
- Change every accepted item's confidence to `high`.
- Confirm no destination overwrites unrelated material.

All item paths must remain relative to `root`. The validator rejects traversal,
duplicate sources or destinations, unresolved items, low-confidence items, and
unrelated destination collisions.
