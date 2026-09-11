# PDF Annotation Manifest

The manifest is a JSON array with 1 to 50 entries. Every entry creates one
Zotero-native annotation in an existing PDF attachment.

```json
[
  {
    "attachment_key": "ABCD2345",
    "page": 12,
    "text": "The exact passage as extracted from this PDF page.",
    "type": "highlight",
    "color": "#ffd400",
    "comment": "Optional research note",
    "tags": ["result", "identification"]
  },
  {
    "attachment_key": "EFGH6789",
    "page": 4,
    "text": "A second uniquely occurring passage.",
    "type": "underline",
    "color": "#2ea8e5"
  }
]
```

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `attachment_key` | yes | Exact eight-character key of an existing Zotero PDF attachment |
| `page` | yes | One-based PDF page number, independent of printed pagination |
| `text` | yes | Nonblank, exact, uniquely occurring passage on that page |
| `type` | yes | `highlight` or `underline` |
| `color` | yes | Six-digit hexadecimal RGB color including `#` |
| `comment` | no | Text stored as the annotation comment; defaults to an empty string |
| `tags` | no | Array of nonblank tag names; defaults to an empty array |

No additional fields are accepted. Duplicate entries with the same attachment,
page, passage, and type are rejected before any Local API request.

The helper reads the PDF's page-label metadata separately. For example, manifest
`page: 3` can become Zotero display label `257` while its position remains bound
to the third page in the file.

## Passage selection

Copy enough text to identify one occurrence on the chosen PDF page. Matching is
exact at the extracted-word level, so differences in hyphenation, ligatures, or
OCR output can prevent a match. A repeated short phrase is ambiguous; extend it
with neighboring words and make a new plan.

The plan records the located rectangles, attachment version, file size, and PDF
SHA-256 digest. Applying the batch recalculates them and stops if they changed.
