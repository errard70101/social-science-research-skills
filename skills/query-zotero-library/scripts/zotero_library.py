from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlsplit

import httpx
from pypdf import PdfReader
from pypdf.errors import PyPdfError

LOCAL_API_BASE = "http://localhost:23119/api/"
LOCAL_API_PORT = 23119
API_HEADERS = {"Zotero-API-Version": "3"}
MAX_SEARCH_RESULTS = 50


class ZoteroError(RuntimeError):
    """A user-actionable Zotero Local API error."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print_json({"error": message})
        raise SystemExit(1)


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_local_api_base(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or not _is_loopback_host(parsed.hostname):
        raise ValueError("Zotero Local API base URL must use an HTTP loopback host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Zotero Local API base URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Zotero Local API base URL has an invalid port") from exc
    if port != LOCAL_API_PORT:
        raise ValueError(
            f"Zotero Local API base URL must use port {LOCAL_API_PORT}"
        )
    if parsed.query:
        raise ValueError("Zotero Local API base URL must not contain a query")
    if parsed.fragment:
        raise ValueError("Zotero Local API base URL must not contain a fragment")
    path = parsed.path.rstrip("/")
    if path != "/api":
        raise ValueError("Zotero Local API base URL must end with /api/")
    return base_url.rstrip("/") + "/"


def file_url_to_path(file_url: str, *, platform: str | None = None) -> str:
    """Convert a Zotero file URL to a native POSIX or Windows path."""
    parsed = urlsplit(file_url.strip())
    if parsed.scheme.casefold() != "file":
        raise ValueError("Attachment location is not a file URL")
    if parsed.query:
        raise ValueError("Attachment file URL must not contain a query")
    if parsed.fragment:
        raise ValueError("Attachment file URL must not contain a fragment")

    target_platform = platform or ("windows" if os.name == "nt" else "posix")
    if target_platform not in {"posix", "windows"}:
        raise ValueError("platform must be 'posix' or 'windows'")

    decoded_path = unquote(parsed.path)
    host = unquote(parsed.netloc)
    is_local_host = not host or host.casefold() == "localhost"

    if target_platform == "windows":
        if not is_local_host:
            path = PureWindowsPath(f"//{host}{decoded_path}")
            if not path.is_absolute():
                raise ValueError("Attachment file URL must contain an absolute path")
            return str(path)
        if re.match(r"^/[A-Za-z]:/", decoded_path):
            decoded_path = decoded_path[1:]
        path = PureWindowsPath(decoded_path)
        if not path.is_absolute():
            raise ValueError("Attachment file URL must contain an absolute path")
        return str(path)

    if not is_local_host:
        decoded_path = f"//{host}{decoded_path}"
    if not decoded_path.startswith("/"):
        raise ValueError("Attachment file URL must contain an absolute path")
    return decoded_path


def _collection_name(collection: dict[str, object]) -> str:
    data = collection.get("data")
    if not isinstance(data, dict):
        return ""
    name = data.get("name")
    return str(name).strip() if name is not None else ""


def build_collection_paths(
    collections: list[dict[str, object]],
) -> dict[str, str]:
    """Map Zotero collection keys to human-readable nested paths."""
    records = {
        str(collection["key"]): collection
        for collection in collections
        if collection.get("key")
    }
    paths: dict[str, str] = {}

    def build(key: str, ancestors: tuple[str, ...] = ()) -> str:
        if key in paths:
            return paths[key]
        if key in ancestors:
            raise ValueError("Zotero collection hierarchy contains a cycle")

        collection = records[key]
        data = collection.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"Collection {key} has malformed data")
        name = _collection_name(collection)
        if not name:
            raise ValueError(f"Collection {key} has no name")

        parent = data.get("parentCollection")
        if parent and str(parent) in records:
            parent_path = build(str(parent), (*ancestors, key))
            path = f"{parent_path} / {name}"
        else:
            path = name
        paths[key] = path
        return path

    for collection_key in records:
        build(collection_key)
    return paths


def _normalize_collection_path(value: str) -> str:
    return " / ".join(part.strip() for part in value.split("/") if part.strip())


def resolve_collection_key(
    collections: list[dict[str, object]],
    requested: str,
) -> str:
    """Resolve either an exact nested path or an unambiguous bare name."""
    normalized = _normalize_collection_path(requested)
    if not normalized:
        raise ValueError("Collection name cannot be empty")

    paths = build_collection_paths(collections)
    exact = [
        key
        for key, path in paths.items()
        if path.casefold() == normalized.casefold()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"Collection path is ambiguous: {requested}")

    if "/" not in requested:
        named = [
            key
            for key, path in paths.items()
            if path.rsplit(" / ", maxsplit=1)[-1].casefold()
            == normalized.casefold()
        ]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            choices = ", ".join(sorted(paths[key] for key in named))
            raise ValueError(
                f"Collection name is ambiguous: {requested}. Use one of: {choices}"
            )

    raise ValueError(f"Zotero collection was not found: {requested}")


def _creator_name(creator: dict[str, object]) -> str:
    if creator.get("name"):
        return str(creator["name"]).strip()
    parts = [creator.get("firstName"), creator.get("lastName")]
    return " ".join(str(part).strip() for part in parts if part).strip()


def _creators(data: dict[str, object]) -> list[dict[str, str]]:
    raw_creators = data.get("creators", [])
    if not isinstance(raw_creators, list):
        return []
    creators = [creator for creator in raw_creators if isinstance(creator, dict)]
    return [
        {
            "name": _creator_name(creator),
            "role": str(creator.get("creatorType") or ""),
        }
        for creator in creators
        if _creator_name(creator)
    ]


def _authors(data: dict[str, object]) -> list[str]:
    return [
        creator["name"]
        for creator in _creators(data)
        if creator["role"] == "author"
    ]


def _year(value: object) -> str | None:
    match = re.search(r"\b(?:18|19|20|21)\d{2}\b", str(value or ""))
    return match.group(0) if match else None


def _is_pdf_attachment(data: dict[str, object]) -> bool:
    if data.get("itemType") != "attachment":
        return False
    content_type = str(data.get("contentType", "")).casefold()
    filename = str(data.get("filename", "")).casefold()
    return content_type == "application/pdf" or filename.endswith(".pdf")


class LocalZotero:
    """Small GET-only client for Zotero's loopback Local API."""

    def __init__(
        self,
        *,
        base_url: str = LOCAL_API_BASE,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = validate_local_api_base(base_url)
        self._client = httpx.Client(
            headers=API_HEADERS,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self) -> LocalZotero:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        return self.base_url + path.lstrip("/")

    def _get(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        response = self._client.get(self._url(path), params=params)
        if response.status_code == 403:
            raise ZoteroError(
                "Zotero Local API is disabled. In Zotero Settings → Advanced, "
                "enable 'Allow other applications on this computer to "
                "communicate with Zotero'."
            )
        response.raise_for_status()
        return response

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> object:
        response = self._get(path, params=params)
        return self._decode_json(response, path)

    @staticmethod
    def _decode_json(response: httpx.Response, path: str) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise ZoteroError(
                f"Zotero Local API returned invalid JSON for {path}"
            ) from exc

    def check(self) -> dict[str, object]:
        response = self._get("")
        return {
            "ok": True,
            "api_version": response.headers.get("Zotero-API-Version"),
            "schema_version": response.headers.get("Zotero-Schema-Version"),
        }

    def collections(self) -> list[dict[str, object]]:
        payload = self._get_json("users/0/collections")
        if not isinstance(payload, list):
            raise ZoteroError("Zotero Local API returned malformed collections")
        return [item for item in payload if isinstance(item, dict)]

    def search(
        self,
        query: str,
        *,
        collection: str | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(
                f"Search limit must be between 1 and {MAX_SEARCH_RESULTS}"
            )

        if collection:
            collections = self.collections()
            collection_key = resolve_collection_key(collections, collection)
            collection_paths = build_collection_paths(collections)
            endpoint = f"users/0/collections/{collection_key}/items/top"
            scope: dict[str, object] = {
                "kind": "collection",
                "name": collection_paths[collection_key],
                "key": collection_key,
            }
        else:
            endpoint = "users/0/items/top"
            scope = {"kind": "library"}

        response = self._get(
            endpoint,
            params={
                "q": query,
                "qmode": "everything",
                "limit": limit,
            },
        )
        payload = self._decode_json(response, endpoint)
        if not isinstance(payload, list):
            raise ZoteroError("Zotero Local API returned malformed search results")

        items = [
            self._format_item(item)
            for item in payload
            if isinstance(item, dict)
        ]
        total_header = response.headers.get("Total-Results", "")
        total_results = (
            int(total_header) if total_header.isdecimal() else len(items)
        )
        return {
            "query": query,
            "scope": scope,
            "count": len(items),
            "total_results": total_results,
            "truncated": total_results > len(items),
            "items": items,
        }

    def _format_item(self, item: dict[str, object]) -> dict[str, object]:
        data = item.get("data")
        if not isinstance(data, dict):
            raise ZoteroError("Zotero item has malformed data")
        key = str(item.get("key") or data.get("key") or "")
        if not key:
            raise ZoteroError("Zotero item has no key")

        if _is_pdf_attachment(data):
            raw_attachments = [item]
        else:
            children = self._get_json(f"users/0/items/{key}/children")
            if not isinstance(children, list):
                raise ZoteroError(f"Zotero item {key} has malformed children")
            raw_attachments = [
                child
                for child in children
                if isinstance(child, dict)
                and isinstance(child.get("data"), dict)
                and _is_pdf_attachment(child["data"])
            ]

        tags = data.get("tags", [])
        tag_names = [
            str(tag["tag"])
            for tag in tags
            if isinstance(tag, dict) and tag.get("tag")
        ]
        return {
            "key": key,
            "item_type": data.get("itemType"),
            "title": data.get("title") or data.get("filename") or "",
            "authors": _authors(data),
            "creators": _creators(data),
            "date": data.get("date") or "",
            "year": _year(data.get("date")),
            "abstract": data.get("abstractNote") or "",
            "doi": data.get("DOI") or "",
            "url": data.get("url") or "",
            "tags": tag_names,
            "collections": data.get("collections") or [],
            "attachments": [
                self._resolve_attachment(attachment)
                for attachment in raw_attachments
            ],
        }

    def _resolve_attachment(
        self,
        attachment: dict[str, object],
    ) -> dict[str, object]:
        data = attachment.get("data")
        if not isinstance(data, dict):
            raise ZoteroError("Zotero attachment has malformed data")
        key = str(attachment.get("key") or data.get("key") or "")
        result: dict[str, object] = {
            "key": key,
            "title": data.get("title") or "",
            "filename": data.get("filename") or "",
            "content_type": data.get("contentType") or "",
            "available": False,
            "path": None,
        }

        try:
            response = self._get(f"users/0/items/{key}/file/view/url")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {404, 410}:
                result["error"] = "Local PDF is not available on this computer"
                return result
            raise

        file_url = response.text.strip()
        try:
            path = file_url_to_path(file_url)
        except ValueError as exc:
            result["error"] = str(exc)
            result["file_url"] = file_url
            return result

        result["file_url"] = file_url
        result["path"] = path
        result["available"] = Path(path).is_file()
        if not result["available"]:
            result["error"] = (
                "Zotero returned a local PDF path, but the file is not available "
                "on this computer"
            )
        return result


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    return [term for term in re.findall(r"\w+", query.casefold()) if len(term) > 1]


def extract_pdf(
    source: str | Path,
    *,
    query: str | None,
    max_pages: int = 8,
    max_chars_per_page: int = 12_000,
) -> dict[str, object]:
    """Extract and rank bounded PDF page text for evidence review."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {path}")
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if max_chars_per_page < 1:
        raise ValueError("max_chars_per_page must be at least 1")
    if not query or not query.strip():
        raise ValueError("A non-empty query is required for relevant-page extraction")

    reader = PdfReader(str(path))
    terms = _query_terms(query)
    phrase = query.casefold().strip()
    pages: list[dict[str, object]] = []
    empty_pages: list[int] = []

    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages.append(index)
        folded = text.casefold()
        score = sum(folded.count(term) for term in terms)
        if phrase:
            score += 5 * folded.count(phrase)
        pages.append(
            {
                "page": index,
                "score": score,
                "text": text[:max_chars_per_page],
                "truncated": len(text) > max_chars_per_page,
            }
        )

    matched_pages = [page for page in pages if int(page["score"]) > 0]
    matched_pages.sort(
        key=lambda page: (-int(page["score"]), int(page["page"]))
    )
    selected = matched_pages[:max_pages]
    warnings: list[str] = []
    if empty_pages:
        warnings.append(
            "Some pages have no extractable text; the PDF may require OCR."
        )
    if not any(page["text"] for page in pages):
        warnings.append("No extractable text was found in the PDF.")
    elif not matched_pages:
        warnings.append(
            "No pages matched the query; refine the query or inspect another PDF."
        )

    return {
        "source": str(path),
        "query": query,
        "total_pages": len(reader.pages),
        "matched_pages": len(matched_pages),
        "returned_pages": len(selected),
        "pages": selected,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Query local Zotero literature without modifying the library"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Check Zotero Local API availability")

    search_parser = subparsers.add_parser(
        "search",
        help="Search Zotero metadata and indexed full text",
    )
    search_parser.add_argument("query", help="A compact search phrase")
    search_parser.add_argument(
        "--collection",
        help="Optional collection name or nested path",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help=f"Maximum results, from 1 to {MAX_SEARCH_RESULTS}",
    )

    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract the most relevant pages from a local PDF",
    )
    extract_parser.add_argument("path", type=Path, help="Local PDF path")
    extract_parser.add_argument(
        "--query",
        required=True,
        help="Terms used to select and rank relevant pages",
    )
    extract_parser.add_argument(
        "--max-pages",
        type=int,
        default=8,
        help="Maximum pages to return",
    )
    extract_parser.add_argument(
        "--max-chars-per-page",
        type=int,
        default=12_000,
        help="Maximum extracted characters per page",
    )
    return parser


def _connection_error_message() -> str:
    return (
        "Cannot connect to Zotero Local API. Start Zotero Desktop, then enable "
        "'Allow other applications on this computer to communicate with Zotero' "
        "in Zotero Settings → Advanced."
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "extract":
            result = extract_pdf(
                args.path,
                query=args.query,
                max_pages=args.max_pages,
                max_chars_per_page=args.max_chars_per_page,
            )
        else:
            with LocalZotero() as client:
                if args.command == "check":
                    result = client.check()
                else:
                    result = client.search(
                        args.query,
                        collection=args.collection,
                        limit=args.limit,
                    )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print_json({"error": _connection_error_message()})
        return 1
    except httpx.TimeoutException:
        print_json({"error": "Zotero Local API request timed out"})
        return 1
    except httpx.HTTPStatusError as exc:
        print_json(
            {
                "error": (
                    "Zotero Local API request failed with HTTP "
                    f"{exc.response.status_code}"
                )
            }
        )
        return 1
    except PyPdfError as exc:
        print_json({"error": f"Cannot read PDF: {exc}"})
        return 1
    except (OSError, ValueError, ZoteroError) as exc:
        print_json({"error": str(exc)})
        return 1

    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
