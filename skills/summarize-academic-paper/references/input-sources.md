# Input Sources

The `fetch` subcommand accepts a local PDF path, an HTTP/HTTPS URL, or a DOI.
It rewrites known abstract-page URLs to their direct PDF locations, follows
HTTP redirects, and reads `<meta name="citation_pdf_url">` tags on HTML
landing pages.

## Recognized URL patterns

| Pattern                                     | Rewrite target                                  |
|---------------------------------------------|-------------------------------------------------|
| `https://arxiv.org/abs/<id>`                | `https://arxiv.org/pdf/<id>.pdf`                |
| `https://www.nber.org/papers/w<id>`         | `https://www.nber.org/papers/w<id>.pdf`         |
| `https://<journal>/<article>` (HTML landing) | Follow `<meta name="citation_pdf_url">` if present |

Any other URL is fetched directly and accepted if the response carries
`Content-Type: application/pdf`.

## DOI behavior

A DOI string (with or without the `doi:` prefix) is normalized to lowercase
and resolved through `https://doi.org/<doi>`. When the redirect target is not
a PDF and `UNPAYWALL_EMAIL` is set in the environment, the helper queries
`https://api.unpaywall.org/v2/<doi>?email=<email>` and prefers
`best_oa_location.url_for_pdf`.

When `UNPAYWALL_EMAIL` is not set and the DOI does not resolve directly to a
PDF, the `fetch` artifact records `unresolved` with a message that names
`UNPAYWALL_EMAIL` so the user can decide whether to set it.

> [!NOTE]
> Real Unpaywall DOI fallback requests require a valid `UNPAYWALL_EMAIL` environment variable. To manually validate the Unpaywall integration, set `UNPAYWALL_EMAIL` in your environment and run with a real open-access DOI (e.g. `10.1038/nature12345`). Do not run live network tests in the automated test suite.

## When fetch fails

- The skill never invents a URL. If neither the rewrite, the citation-meta
  tag, nor Unpaywall yields a PDF, the artifact records an explicit
  `unresolved` reason and the workflow stops.
- For SSRN abstract pages and other publishers that gate downloads behind a
  click-through or login, manually download the PDF and pass the local path
  to `fetch --input` instead.
- For working papers whose host blocks scripted requests, download the PDF
  in a browser and use the local file path.

## Privacy and rate limits

- The `httpx` client identifies itself with a static User-Agent.
- The helper makes at most one direct request per URL and at most one
  follow-up request when the page advertises a PDF location.
- Unpaywall requests respect the email-based identification policy.
