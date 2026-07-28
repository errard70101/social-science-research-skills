from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import os
import re
import unicodedata
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlsplit

import httpx
from pypdf import PdfReader
from pypdf.errors import PyPdfError

pymupdf = None
_PYMUPDF_IMPORT_ATTEMPTED = False

LOCAL_API_BASE = "http://localhost:23119/api/"
LOCAL_API_PORT = 23119
API_HEADERS = {"Zotero-API-Version": "3"}
MAX_SEARCH_RESULTS = 50
API_PAGE_SIZE = 100
MIN_MEANINGFUL_PAGE_CHARACTERS = 5
COLLECTION_KEY_PATTERN = re.compile(
    r"^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$",
    flags=re.IGNORECASE,
)
ITEM_KEY_PATTERN = COLLECTION_KEY_PATTERN


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
    """Resolve an exact key, nested path, or unambiguous bare name."""
    requested = requested.strip()
    matching_keys = [
        str(collection["key"])
        for collection in collections
        if collection.get("key")
        and str(collection["key"]).casefold() == requested.casefold()
    ]
    if len(matching_keys) == 1:
        return matching_keys[0]

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

    if COLLECTION_KEY_PATTERN.fullmatch(requested):
        raise ValueError(f"Zotero collection key was not found: {requested}")
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


def _tags(data: dict[str, object]) -> list[str]:
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [
        str(tag["tag"])
        for tag in tags
        if isinstance(tag, dict) and tag.get("tag")
    ]


class _ReadableNoteParser(HTMLParser):
    """Convert Zotero note HTML into compact, readable plain text."""

    _BLOCK_TAGS = {"br", "div", "li", "p", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [
            " ".join(line.split())
            for line in "".join(self.parts).splitlines()
            if line.strip()
        ]
        return "\n".join(lines)


def _note_text(value: object) -> str:
    parser = _ReadableNoteParser()
    parser.feed(str(value or ""))
    parser.close()
    return parser.text()


def _meaningful_character_count(text: str) -> int:
    return sum(character.isalnum() for character in text)


def _has_suspicious_control_characters(text: str) -> bool:
    controls = sum(
        unicodedata.category(character) == "Cc"
        and character not in {"\n", "\r", "\t"}
        for character in text
    )
    return "\ufffd" in text or controls >= 2


def _pymupdf_backend():
    global _PYMUPDF_IMPORT_ATTEMPTED, pymupdf
    if pymupdf is not None:
        return pymupdf
    if not _PYMUPDF_IMPORT_ATTEMPTED:
        _PYMUPDF_IMPORT_ATTEMPTED = True
        with suppress(ImportError):
            pymupdf = importlib.import_module("pymupdf")
    return pymupdf


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

    def _get_all_json(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        start = 0
        total_results: int | None = None
        while total_results is None or start < total_results:
            page_params = dict(params or {})
            page_params.update({"limit": API_PAGE_SIZE, "start": start})
            response = self._get(path, params=page_params)
            payload = self._decode_json(response, path)
            if not isinstance(payload, list):
                raise ZoteroError(
                    f"Zotero Local API returned malformed results for {path}"
                )
            page = [item for item in payload if isinstance(item, dict)]
            results.extend(page)

            total_header = response.headers.get("Total-Results", "")
            if total_header.isdecimal():
                total_results = int(total_header)
            if not payload:
                break
            start += len(payload)
            if total_results is None and len(payload) < API_PAGE_SIZE:
                break
        return results

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

    def collection_catalog(self) -> dict[str, object]:
        collections = self.collections()
        paths = build_collection_paths(collections)
        summaries: list[dict[str, object]] = []
        for collection in collections:
            key = str(collection.get("key") or "")
            meta = collection.get("meta")
            item_count = meta.get("numItems") if isinstance(meta, dict) else None
            summaries.append(
                {
                    "name": _collection_name(collection),
                    "path": paths[key],
                    "key": key,
                    "item_count": item_count,
                }
            )
        summaries.sort(key=lambda item: str(item["path"]).casefold())
        return {"count": len(summaries), "collections": summaries}

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
            "tags": _tags(data),
            "collections": data.get("collections") or [],
            "attachments": [
                self._resolve_attachment(attachment)
                for attachment in raw_attachments
            ],
        }

    def notes_and_annotations(self, item_key: str) -> dict[str, object]:
        """Return child notes and PDF annotations for one Zotero item."""
        normalized_key = item_key.strip().upper()
        if not ITEM_KEY_PATTERN.fullmatch(normalized_key):
            raise ValueError("Zotero item key must be eight valid characters")

        item = self._get_json(f"users/0/items/{normalized_key}")
        if not isinstance(item, dict):
            raise ZoteroError(f"Zotero item {normalized_key} is malformed")
        data = item.get("data")
        if not isinstance(data, dict):
            raise ZoteroError(f"Zotero item {normalized_key} has malformed data")

        if _is_pdf_attachment(data):
            children: list[dict[str, object]] = []
            attachments = [item]
        else:
            raw_children = self._get_json(
                f"users/0/items/{normalized_key}/children"
            )
            if not isinstance(raw_children, list):
                raise ZoteroError(
                    f"Zotero item {normalized_key} has malformed children"
                )
            children = [
                child for child in raw_children if isinstance(child, dict)
            ]
            attachments = [
                child
                for child in children
                if isinstance(child.get("data"), dict)
                and _is_pdf_attachment(child["data"])
            ]

        notes = [
            self._format_note(child)
            for child in children
            if isinstance(child.get("data"), dict)
            and child["data"].get("itemType") == "note"
        ]
        attachment_keys = {
            str(attachment.get("key") or "")
            for attachment in attachments
            if attachment.get("key")
        }
        annotations = (
            self._get_all_json(
                "users/0/items",
                params={"itemType": "annotation"},
            )
            if attachment_keys
            else []
        )
        annotations_by_attachment: dict[str, list[dict[str, object]]] = {
            key: [] for key in attachment_keys
        }
        for annotation in annotations:
            annotation_data = annotation.get("data")
            if not isinstance(annotation_data, dict):
                continue
            parent_key = str(annotation_data.get("parentItem") or "")
            if parent_key in annotations_by_attachment:
                annotations_by_attachment[parent_key].append(
                    self._format_annotation(annotation)
                )

        formatted_attachments: list[dict[str, object]] = []
        for attachment in attachments:
            attachment_data = attachment.get("data")
            if not isinstance(attachment_data, dict):
                continue
            key = str(attachment.get("key") or "")
            attachment_annotations = annotations_by_attachment.get(key, [])
            attachment_annotations.sort(
                key=lambda value: (
                    str(value["sort_index"]),
                    str(value["key"]),
                )
            )
            formatted_attachments.append(
                {
                    "key": key,
                    "title": attachment_data.get("title") or "",
                    "filename": attachment_data.get("filename") or "",
                    "annotations": attachment_annotations,
                }
            )

        return {
            "item": {
                "key": normalized_key,
                "item_type": data.get("itemType"),
                "title": data.get("title") or data.get("filename") or "",
            },
            "note_count": len(notes),
            "annotation_count": sum(
                len(attachment["annotations"])
                for attachment in formatted_attachments
            ),
            "notes": notes,
            "attachments": formatted_attachments,
        }

    @staticmethod
    def _format_note(item: dict[str, object]) -> dict[str, object]:
        data = item.get("data")
        if not isinstance(data, dict):
            raise ZoteroError("Zotero note has malformed data")
        return {
            "key": str(item.get("key") or data.get("key") or ""),
            "text": _note_text(data.get("note")),
            "tags": _tags(data),
            "date_modified": data.get("dateModified") or "",
        }

    @staticmethod
    def _format_annotation(item: dict[str, object]) -> dict[str, object]:
        data = item.get("data")
        if not isinstance(data, dict):
            raise ZoteroError("Zotero annotation has malformed data")
        return {
            "key": str(item.get("key") or data.get("key") or ""),
            "type": data.get("annotationType") or "",
            "text": data.get("annotationText") or "",
            "comment": data.get("annotationComment") or "",
            "color": data.get("annotationColor") or "",
            "page_label": data.get("annotationPageLabel") or "",
            "sort_index": data.get("annotationSortIndex") or "",
            "tags": _tags(data),
            "date_modified": data.get("dateModified") or "",
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
            return result

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
    query: str | None = None,
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
    if query is not None and not query.strip():
        raise ValueError("When provided, query must not be blank")

    normalized_query = query.strip() if query is not None else None
    terms = _query_terms(normalized_query)
    phrase = normalized_query.casefold() if normalized_query else ""
    pages: list[dict[str, object]] = []
    empty_pages: list[int] = []
    fallback_pages: list[int] = []
    fallback_errors: list[str] = []
    fallback_document = None
    fallback_backend = None
    reader = None

    try:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
    except PyPdfError as primary_error:
        fallback_backend = _pymupdf_backend()
        if fallback_backend is None:
            raise
        try:
            fallback_document = fallback_backend.open(str(path))
        except Exception as fallback_error:
            raise primary_error from fallback_error
        total_pages = len(fallback_document)

    pages_to_extract = (
        total_pages
        if normalized_query is not None
        else min(total_pages, max_pages)
    )
    try:
        for page_index in range(pages_to_extract):
            page_number = page_index + 1
            primary_error: Exception | None = None
            if reader is None:
                text = ""
            else:
                try:
                    text = (reader.pages[page_index].extract_text() or "").strip()
                except Exception as exc:
                    text = ""
                    primary_error = exc

            needs_fallback = (
                reader is None
                or _meaningful_character_count(text)
                < MIN_MEANINGFUL_PAGE_CHARACTERS
                or _has_suspicious_control_characters(text)
            )
            if needs_fallback:
                fallback_backend = fallback_backend or _pymupdf_backend()
            if needs_fallback and fallback_backend is not None:
                try:
                    if fallback_document is None:
                        fallback_document = fallback_backend.open(str(path))
                    fallback_text = (
                        fallback_document.load_page(page_index).get_text("text")
                        or ""
                    ).strip()
                except Exception as exc:
                    fallback_errors.append(f"page {page_number}: {exc}")
                else:
                    fallback_is_cleaner = (
                        _has_suspicious_control_characters(text)
                        and not _has_suspicious_control_characters(fallback_text)
                        and _meaningful_character_count(fallback_text)
                        >= MIN_MEANINGFUL_PAGE_CHARACTERS
                    )
                    fallback_has_more_text = _meaningful_character_count(
                        fallback_text
                    ) > _meaningful_character_count(text)
                    if (
                        reader is None
                        or fallback_is_cleaner
                        or fallback_has_more_text
                    ):
                        text = fallback_text
                        fallback_pages.append(page_number)

            if primary_error is not None and page_number not in fallback_pages:
                raise PyPdfError(
                    f"Cannot extract text from PDF page {page_number}"
                ) from primary_error

            if not text:
                empty_pages.append(page_number)
            folded = text.casefold()
            score = sum(folded.count(term) for term in terms)
            if phrase:
                score += 5 * folded.count(phrase)
            pages.append(
                {
                    "page": page_number,
                    "score": score,
                    "text": text[:max_chars_per_page],
                    "truncated": len(text) > max_chars_per_page,
                }
            )
    finally:
        if fallback_document is not None:
            fallback_document.close()

    if normalized_query is not None:
        matched_pages = [page for page in pages if int(page["score"]) > 0]
        matched_pages.sort(
            key=lambda page: (-int(page["score"]), int(page["page"]))
        )
        selected = matched_pages[:max_pages]
        matched_count: int | None = len(matched_pages)
        selection_mode = "query-ranked"
    else:
        selected = pages[:max_pages]
        matched_count = None
        selection_mode = "leading-pages"

    warnings: list[str] = []
    if fallback_pages:
        page_list = ", ".join(str(page) for page in fallback_pages)
        warnings.append(
            f"PyMuPDF fallback supplied text for PDF pages: {page_list}."
        )
    if fallback_errors:
        warnings.append(
            "PyMuPDF fallback could not read some low-text pages; retained "
            "the pypdf output."
        )
    if empty_pages:
        warnings.append(
            "Some pages have no extractable text; the PDF may require OCR."
        )
    if not any(page["text"] for page in pages):
        warnings.append("No extractable text was found in the PDF.")
    elif normalized_query is not None and not selected:
        warnings.append(
            "No pages matched the query; refine the query or inspect another PDF."
        )

    return {
        "source": str(path),
        "query": normalized_query,
        "selection_mode": selection_mode,
        "total_pages": total_pages,
        "matched_pages": matched_count,
        "returned_pages": len(selected),
        "pages": selected,
        "parser": (
            "pypdf"
            if not fallback_pages
            else "pymupdf"
            if len(fallback_pages) == pages_to_extract
            else "mixed"
        ),
        "fallback_pages": fallback_pages,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Query local Zotero literature without modifying the library"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Check Zotero Local API availability")
    subparsers.add_parser(
        "collections",
        help="List personal-library collection paths, keys, and item counts",
    )
    annotations_parser = subparsers.add_parser(
        "annotations",
        help="Read child notes and PDF annotations for one Zotero item",
    )
    annotations_parser.add_argument(
        "item_key",
        help="Eight-character Zotero bibliographic item or PDF attachment key",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Search Zotero metadata and indexed full text",
    )
    search_parser.add_argument("query", help="A compact search phrase")
    search_parser.add_argument(
        "--collection",
        help="Optional collection key, nested path, or unambiguous name",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help=f"Maximum results, from 1 to {MAX_SEARCH_RESULTS}",
    )

    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract query-ranked or leading pages from a local PDF",
    )
    extract_parser.add_argument("path", type=Path, help="Local PDF path")
    extract_parser.add_argument(
        "--query",
        help="Optional terms used to select and rank relevant pages",
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
                elif args.command == "collections":
                    result = client.collection_catalog()
                elif args.command == "annotations":
                    result = client.notes_and_annotations(args.item_key)
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
