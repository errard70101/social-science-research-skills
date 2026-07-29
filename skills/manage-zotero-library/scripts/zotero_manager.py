#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # pragma: no cover - exercised in environments without extra
    keyring = None

    class KeyringError(Exception):
        """Fallback type when the optional keyring dependency is absent."""

    class PasswordDeleteError(KeyringError):
        """Fallback type when the optional keyring dependency is absent."""


LOCAL_API_BASE = "http://localhost:23119/api/"
LOCAL_API_PORT = 23119
WEB_API_BASE = "https://api.zotero.org/"
API_HEADERS = {"Zotero-API-Version": "3"}
APP_NAME = "Social Science Research Skills"
LOCAL_KEYRING_SERVICE = "social-science-research-skills.zotero-local-api"
WEB_KEYRING_SERVICE = "social-science-research-skills.zotero-web-api"
PLAN_SCHEMA_VERSION = 1
MAX_BATCH_ITEMS = 50
PAGE_SIZE = 100
KEY_PATTERN = re.compile(
    r"^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$",
    flags=re.IGNORECASE,
)
SECURE_KEYRING_MODULES = {
    "keyring.backends.libsecret",
    "keyring.backends.macos",
    "keyring.backends.secretservice",
    "keyring.backends.windows",
    "keyring.backends.kwallet",
}
AUTO_CREDENTIAL_STORE = object()


class ZoteroManagementError(RuntimeError):
    """Base error for safe Zotero management failures."""


class PlanDriftError(ZoteroManagementError):
    """The Zotero state changed after a plan was prepared."""


class AuthorizationError(ZoteroManagementError):
    """A Zotero write authorization cannot be used safely."""


class PlanIntegrityError(ZoteroManagementError):
    """A plan is malformed or changed after it was signed."""


class CredentialStoreUnavailable(AuthorizationError):
    """No supported operating-system credential store is available."""


class CredentialStore(Protocol):
    def get(self, credential_id: str) -> str | None:
        """Return a remembered key without exposing it to output."""

    def set(self, credential_id: str, key: str) -> None:
        """Save a key under a non-secret server or profile identifier."""

    def delete(self, credential_id: str) -> bool:
        """Delete a remembered key and report whether one existed."""


class SystemCredentialStore:
    """Store Zotero keys only in recognized operating-system secret stores."""

    def __init__(self, service: str = LOCAL_KEYRING_SERVICE) -> None:
        self.service = service

    @staticmethod
    def _backend() -> object:
        if keyring is None:
            raise CredentialStoreUnavailable(
                "The keyring package is required for secure remembered "
                "authorization storage"
            )
        try:
            backend = keyring.get_keyring()
            module = backend.__class__.__module__.casefold()
            priority = float(getattr(backend, "priority", 0))
        except (KeyringError, TypeError, ValueError) as exc:
            raise CredentialStoreUnavailable(
                "The operating-system credential store is unavailable"
            ) from exc
        if module not in SECURE_KEYRING_MODULES or priority <= 0:
            raise CredentialStoreUnavailable(
                "The selected keyring backend is not a recognized secure "
                "operating-system credential store"
            )
        return backend

    def get(self, server_id: str) -> str | None:
        backend = self._backend()
        try:
            value = backend.get_password(self.service, server_id)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "Could not read the operating-system credential store"
            ) from exc
        return str(value) if value else None

    def set(self, server_id: str, key: str) -> None:
        backend = self._backend()
        try:
            backend.set_password(self.service, server_id, key)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "Could not save the remembered Zotero authorization"
            ) from exc

    def delete(self, server_id: str) -> bool:
        backend = self._backend()
        try:
            existing = backend.get_password(self.service, server_id)
            if not existing:
                return False
            backend.delete_password(self.service, server_id)
        except PasswordDeleteError:
            return False
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "Could not delete the remembered Zotero authorization"
            ) from exc
        return True


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print_json({"error": message})
        raise SystemExit(1)


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def prompt_web_api_key() -> str:
    """Read a Web API key only when terminal echo can be disabled."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Zotero Web API key: ")
    except getpass.GetPassWarning as exc:
        raise AuthorizationError(
            "Cannot accept a Zotero Web API key without echo-free terminal "
            "input. Run web-auth-store from an interactive terminal."
        ) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        raise ValueError(f"Zotero Local API base URL must use port {LOCAL_API_PORT}")
    if parsed.query or parsed.fragment:
        raise ValueError(
            "Zotero Local API base URL must not contain a query or fragment"
        )
    if parsed.path.rstrip("/") != "/api":
        raise ValueError("Zotero Local API base URL must end with /api/")
    return base_url.rstrip("/") + "/"


def validate_web_api_base(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or parsed.hostname != "api.zotero.org":
        raise ValueError("Zotero Web API base URL must be https://api.zotero.org/")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Zotero Web API base URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Zotero Web API base URL has an invalid port") from exc
    if port not in {None, 443}:
        raise ValueError("Zotero Web API base URL must use the HTTPS default port")
    if parsed.query or parsed.fragment or parsed.path.rstrip("/"):
        raise ValueError("Zotero Web API base URL must be https://api.zotero.org/")
    return WEB_API_BASE


def normalize_key(value: str, *, kind: str) -> str:
    key = value.strip().upper()
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Zotero {kind} key must be eight valid characters")
    return key


def _item_data(item: dict[str, object]) -> dict[str, object]:
    data = item.get("data")
    if not isinstance(data, dict):
        raise ZoteroManagementError("Zotero item has malformed data")
    return data


def _collection_data(collection: dict[str, object]) -> dict[str, object]:
    data = collection.get("data")
    if not isinstance(data, dict):
        raise ZoteroManagementError("Zotero collection has malformed data")
    return data


def _collection_name(collection: dict[str, object]) -> str:
    data = _collection_data(collection)
    return str(data.get("name") or "").strip()


def build_collection_paths(
    collections: list[dict[str, object]],
) -> dict[str, str]:
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
            raise ZoteroManagementError("Zotero collection hierarchy contains a cycle")
        collection = records[key]
        name = _collection_name(collection)
        if not name:
            raise ZoteroManagementError(f"Collection {key} has no name")
        data = _collection_data(collection)
        parent = data.get("parentCollection")
        if parent and str(parent) in records:
            path = f"{build(str(parent), (*ancestors, key))} / {name}"
        else:
            path = name
        paths[key] = path
        return path

    for key in records:
        build(key)
    return paths


def _normalize_collection_path(value: str) -> str:
    return " / ".join(part.strip() for part in value.split("/") if part.strip())


def resolve_collection_key(
    collections: list[dict[str, object]],
    requested: str,
) -> str:
    requested = requested.strip()
    by_key = {
        str(collection["key"]): collection
        for collection in collections
        if collection.get("key")
    }
    key_matches = [key for key in by_key if key.casefold() == requested.casefold()]
    if len(key_matches) == 1:
        return key_matches[0]

    normalized = _normalize_collection_path(requested)
    if not normalized:
        raise ValueError("Collection name cannot be empty")
    paths = build_collection_paths(collections)
    path_matches = [
        key for key, path in paths.items() if path.casefold() == normalized.casefold()
    ]
    if len(path_matches) == 1:
        return path_matches[0]
    if "/" not in requested:
        name_matches = [
            key
            for key, path in paths.items()
            if path.rsplit(" / ", maxsplit=1)[-1].casefold() == normalized.casefold()
        ]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            choices = ", ".join(sorted(paths[key] for key in name_matches))
            raise ValueError(
                f"Collection name is ambiguous: {requested}. Use one of: {choices}"
            )
    if KEY_PATTERN.fullmatch(requested):
        raise ValueError(f"Zotero collection key was not found: {requested}")
    raise ValueError(f"Zotero collection was not found: {requested}")


def _plan_digest(plan: dict[str, object]) -> str:
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def sign_plan(plan: dict[str, object]) -> dict[str, object]:
    signed = json.loads(json.dumps(plan, ensure_ascii=False))
    signed["plan_id"] = _plan_digest(signed)
    return signed


def validate_plan(plan: dict[str, object]) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanIntegrityError("Unsupported Zotero management plan schema")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or plan_id != _plan_digest(plan):
        raise PlanIntegrityError("Zotero management plan ID does not match content")
    if plan.get("action") not in {
        "update_items",
        "create_collection",
        "update_collection",
        "delete_collection",
        "delete_collections",
    }:
        raise PlanIntegrityError("Unsupported Zotero management plan action")


def write_json_exclusive(path: str | Path, value: object) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def ensure_output_available(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def _response_json(response: httpx.Response, context: str) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise ZoteroManagementError(
            f"Zotero API returned invalid JSON for {context}"
        ) from exc


def _response_version(response: httpx.Response) -> int:
    value = response.headers.get("Last-Modified-Version", "")
    if not value.isdecimal():
        raise ZoteroManagementError("Zotero API did not report Last-Modified-Version")
    return int(value)


class ManageZotero:
    """Plan and apply narrowly scoped Zotero API writes."""

    def __init__(
        self,
        *,
        backend: str = "local",
        base_url: str | None = None,
        web_profile: str = "default",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        credential_store: CredentialStore | None | object = AUTO_CREDENTIAL_STORE,
    ) -> None:
        if backend not in {"local", "web"}:
            raise ValueError("Zotero API backend must be 'local' or 'web'")
        self.backend = backend
        if backend == "local":
            self.base_url = validate_local_api_base(base_url or LOCAL_API_BASE)
        else:
            self.base_url = validate_web_api_base(base_url or WEB_API_BASE)
        self.web_profile = web_profile.strip()
        if backend == "web" and not self.web_profile:
            raise ValueError("Zotero Web API credential profile cannot be blank")
        if credential_store is AUTO_CREDENTIAL_STORE:
            self._credential_store: CredentialStore | None = (
                SystemCredentialStore(
                    WEB_KEYRING_SERVICE if backend == "web" else LOCAL_KEYRING_SERVICE
                )
                if transport is None
                else None
            )
        else:
            self._credential_store = credential_store  # type: ignore[assignment]
        self.authorization_mode = "none"
        self._authorization_server_id: str | None = None
        self._web_api_key: str | None = None
        self._web_identity: dict[str, object] | None = None
        self._client = httpx.Client(
            headers=API_HEADERS,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self) -> ManageZotero:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        self._web_api_key = None

    def _url(self, path: str) -> str:
        return self.base_url + path.lstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        if self.backend == "web" and "Zotero-API-Key" not in request_headers:
            request_headers["Zotero-API-Key"] = self._stored_web_key()
        response = self._client.request(
            method,
            self._url(path),
            params=params,
            json=json_body,
            headers=request_headers,
        )
        if self.backend == "local" and response.status_code == 403 and method == "GET":
            raise ZoteroManagementError(
                "Zotero Local API is disabled. Enable local application access "
                "in Zotero Settings → Advanced."
            )
        response.raise_for_status()
        return response

    def _get_json(self, path: str) -> object:
        response = self._request("GET", path)
        return _response_json(response, path)

    def planning_context(self) -> dict[str, object]:
        """Describe whether the running Zotero can apply a generated plan."""
        if self.backend == "web":
            identity = self._ensure_web_identity()
            return {
                "api_backend": "web",
                "application_mode": "web_api",
                "library": {"type": "user", "id": identity["user_id"]},
                "web_profile": self.web_profile,
            }
        response = self._request("GET", "")
        server_id = response.headers.get("Zotero-Server-ID", "").strip()
        write_supported = bool(server_id)
        return {
            "api_backend": "local",
            "server_id": server_id or None,
            "local_api_write_supported": write_supported,
            "application_mode": (
                "local_api" if write_supported else "manual_zotero_desktop"
            ),
        }

    def server_id(self) -> str:
        if self.backend != "local":
            raise ZoteroManagementError(
                "Zotero-Server-ID applies only to the Local API backend"
            )
        context = self.planning_context()
        server_id = context["server_id"]
        if not isinstance(server_id, str):
            raise ZoteroManagementError(
                "This Zotero version exposes a GET-only Local API and does not "
                "support write authorization"
            )
        return server_id

    def _stored_web_key(self) -> str:
        if self.backend != "web":
            raise AuthorizationError(
                "Web API credentials are unavailable on the Local API backend"
            )
        if self._web_api_key:
            return self._web_api_key
        if self._credential_store is None:
            raise CredentialStoreUnavailable(
                "A recognized operating-system credential store is required "
                "for Zotero Web API keys"
            )
        try:
            api_key = self._credential_store.get(self.web_profile)
        except CredentialStoreUnavailable:
            raise
        if not api_key:
            raise AuthorizationError(
                "No Zotero Web API key is stored for credential profile "
                f"{self.web_profile!r}. Run web-auth-store first."
            )
        self._web_api_key = api_key
        return api_key

    def _validate_web_key(self, api_key: str) -> dict[str, object]:
        try:
            response = self._request(
                "GET",
                "keys/current",
                headers={"Zotero-API-Key": api_key},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise AuthorizationError(
                    "The Zotero Web API key is invalid or lacks personal-library "
                    "write access"
                ) from exc
            raise
        payload = _response_json(response, "Web API key validation")
        if not isinstance(payload, dict):
            raise AuthorizationError("Zotero returned malformed API key metadata")
        user_id = payload.get("userID")
        access = payload.get("access")
        user_access = access.get("user") if isinstance(access, dict) else None
        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id <= 0
            or not isinstance(user_access, dict)
            or user_access.get("library") is not True
            or user_access.get("write") is not True
        ):
            raise AuthorizationError(
                "The Zotero Web API key does not have personal-library write access"
            )
        return {
            "user_id": user_id,
            "username": str(payload.get("username") or ""),
        }

    def _ensure_web_identity(self) -> dict[str, object]:
        if self._web_identity is None:
            self._web_identity = self._validate_web_key(self._stored_web_key())
        return self._web_identity

    def _library_path(self, path: str) -> str:
        if self.backend == "web":
            user_id = self._ensure_web_identity()["user_id"]
            return f"users/{user_id}/{path.lstrip('/')}"
        return f"users/0/{path.lstrip('/')}"

    def _get_item(self, key: str) -> dict[str, object]:
        payload = self._get_json(self._library_path(f"items/{key}"))
        if not isinstance(payload, dict):
            raise ZoteroManagementError(f"Zotero item {key} is malformed")
        return payload

    def _get_collections(
        self,
    ) -> tuple[list[dict[str, object]], httpx.Response]:
        return self._get_all(self._library_path("collections"), context="collections")

    def _get_top_items(
        self,
    ) -> tuple[list[dict[str, object]], httpx.Response]:
        return self._get_all(
            self._library_path("items/top"),
            context="top-level items",
        )

    def _get_all(
        self,
        path: str,
        *,
        context: str,
    ) -> tuple[list[dict[str, object]], httpx.Response]:
        records: list[dict[str, object]] = []
        first_response: httpx.Response | None = None
        first_version: int | None = None
        start = 0
        while True:
            response = self._request(
                "GET",
                path,
                params={"limit": PAGE_SIZE, "start": start},
            )
            if first_response is None:
                first_response = response
                if self.backend == "web":
                    first_version = _response_version(response)
            elif self.backend == "web" and _response_version(response) != first_version:
                raise PlanDriftError(
                    f"The Zotero library changed while reading the {context} snapshot"
                )
            payload = _response_json(response, context)
            if not isinstance(payload, list) or any(
                not isinstance(entry, dict) for entry in payload
            ):
                raise ZoteroManagementError(f"Zotero API returned malformed {context}")
            page = payload
            records.extend(page)

            total_header = response.headers.get("Total-Results", "")
            total = int(total_header) if total_header.isdecimal() else None
            if total is not None and len(records) >= total:
                break
            if not page or (total is None and len(page) < PAGE_SIZE):
                break
            start += len(page)
        if first_response is None:  # pragma: no cover - loop always runs once
            raise ZoteroManagementError(f"Could not retrieve Zotero {context}")
        return records, first_response

    def plan_items(
        self,
        item_keys: list[str],
        *,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        add_collections: list[str] | None = None,
        remove_collections: list[str] | None = None,
    ) -> dict[str, object]:
        keys = list(dict.fromkeys(normalize_key(key, kind="item") for key in item_keys))
        manifest = [
            {
                "key": key,
                "add_tags": add_tags or [],
                "remove_tags": remove_tags or [],
                "add_collections": add_collections or [],
                "remove_collections": remove_collections or [],
            }
            for key in keys
        ]
        return self.plan_items_manifest(manifest)

    def plan_items_manifest(
        self,
        manifest: list[dict[str, object]],
    ) -> dict[str, object]:
        if not isinstance(manifest, list):
            raise ValueError("The item manifest must be a JSON array")
        if not manifest:
            raise ValueError("At least one Zotero item key is required")
        if len(manifest) > MAX_BATCH_ITEMS:
            raise ValueError(
                f"A management plan can include at most {MAX_BATCH_ITEMS} items"
            )
        allowed_fields = {
            "key",
            "add_tags",
            "remove_tags",
            "add_collections",
            "remove_collections",
        }
        normalized_manifest: list[dict[str, object]] = []
        seen_keys: set[str] = set()
        needs_collections = False
        for index, entry in enumerate(manifest):
            if not isinstance(entry, dict):
                raise ValueError(f"Item manifest entry {index + 1} must be an object")
            unexpected = set(entry) - allowed_fields
            if unexpected:
                names = ", ".join(sorted(unexpected))
                raise ValueError(
                    f"Item manifest entry {index + 1} has unsupported fields: {names}"
                )
            key = normalize_key(str(entry.get("key") or ""), kind="item")
            if key in seen_keys:
                raise ValueError(f"Item manifest contains duplicate key: {key}")
            seen_keys.add(key)
            normalized = {
                "key": key,
                "add_tags": self._manifest_string_list(entry, "add_tags"),
                "remove_tags": self._manifest_string_list(entry, "remove_tags"),
                "add_collections": self._manifest_string_list(
                    entry,
                    "add_collections",
                ),
                "remove_collections": self._manifest_string_list(
                    entry,
                    "remove_collections",
                ),
            }
            needs_collections = needs_collections or bool(
                normalized["add_collections"] or normalized["remove_collections"]
            )
            normalized_manifest.append(normalized)

        planning_context = self.planning_context()
        collections: list[dict[str, object]] = []
        if needs_collections:
            collections, _ = self._get_collections()

        changes: list[dict[str, object]] = []
        for entry in normalized_manifest:
            key = str(entry["key"])
            added_tags = self._normalize_tags(list(entry["add_tags"]))
            removed_tags = self._normalize_tags(list(entry["remove_tags"]))
            if set(added_tags) & set(removed_tags):
                raise ValueError(
                    f"The same tag cannot be added and removed for item {key}"
                )
            added_collection_keys = [
                resolve_collection_key(collections, value)
                for value in entry["add_collections"]
            ]
            removed_collection_keys = [
                resolve_collection_key(collections, value)
                for value in entry["remove_collections"]
            ]
            if set(added_collection_keys) & set(removed_collection_keys):
                raise ValueError(
                    f"The same collection cannot be added and removed for item {key}"
                )
            record = self._get_item(key)
            data = _item_data(record)
            if data.get("parentItem"):
                raise ValueError(
                    f"Zotero item {key} is not a top-level bibliographic item"
                )
            before_tags = self._copy_tags(data.get("tags"))
            before_collections = self._copy_collection_keys(data.get("collections"))
            after_tags = [
                tag for tag in before_tags if str(tag["tag"]) not in set(removed_tags)
            ]
            existing_tag_names = {str(tag["tag"]) for tag in after_tags}
            for tag in added_tags:
                if tag not in existing_tag_names:
                    after_tags.append({"tag": tag})
                    existing_tag_names.add(tag)

            after_collections = [
                collection_key
                for collection_key in before_collections
                if collection_key not in set(removed_collection_keys)
            ]
            for collection_key in added_collection_keys:
                if collection_key not in after_collections:
                    after_collections.append(collection_key)

            if before_tags == after_tags and before_collections == after_collections:
                continue
            version = data.get("version", record.get("version"))
            if not isinstance(version, int):
                raise ZoteroManagementError(f"Zotero item {key} has no version")
            changes.append(
                {
                    "key": key,
                    "title": data.get("title") or "",
                    "version": version,
                    "before": {
                        "tags": before_tags,
                        "collections": before_collections,
                    },
                    "after": {
                        "tags": after_tags,
                        "collections": after_collections,
                    },
                }
            )

        if not changes:
            raise ValueError("No item changes would be made")
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "update_items",
                **planning_context,
                "summary": {
                    "changed_item_count": len(changes),
                    "requested_item_count": len(normalized_manifest),
                },
                "changes": changes,
            }
        )

    @staticmethod
    def _manifest_string_list(
        entry: dict[str, object],
        field: str,
    ) -> list[str]:
        value = entry.get(field, [])
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(f"Item manifest field {field} must be an array of strings")
        return list(value)

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        normalized = []
        for tag in tags:
            value = tag.strip()
            if not value:
                raise ValueError("Tag names cannot be blank")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _copy_tags(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [dict(tag) for tag in value if isinstance(tag, dict) and tag.get("tag")]

    @classmethod
    def _same_tags(cls, left: object, right: object) -> bool:
        def normalized(value: object) -> list[tuple[str, int]]:
            result = []
            for tag in cls._copy_tags(value):
                tag_type = tag.get("type", 0)
                result.append(
                    (
                        str(tag["tag"]),
                        tag_type if isinstance(tag_type, int) else 0,
                    )
                )
            return sorted(result)

        return normalized(left) == normalized(right)

    @staticmethod
    def _copy_collection_keys(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(key) for key in value if key]

    @classmethod
    def _same_collection_memberships(cls, left: object, right: object) -> bool:
        return sorted(cls._copy_collection_keys(left)) == sorted(
            cls._copy_collection_keys(right)
        )

    def plan_collection_create(
        self,
        name: str,
        *,
        parent: str | None = None,
    ) -> dict[str, object]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Collection name cannot be blank")
        planning_context = self.planning_context()
        collections, response = self._get_collections()
        parent_key = resolve_collection_key(collections, parent) if parent else False
        for entry in collections:
            data = _collection_data(entry)
            if (
                str(data.get("name") or "").casefold() == normalized_name.casefold()
                and (data.get("parentCollection") or False) == parent_key
            ):
                raise ValueError("A collection with that name already exists")
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "create_collection",
                **planning_context,
                "expected_library_version": _response_version(response),
                "after": {
                    "name": normalized_name,
                    "parentCollection": parent_key,
                },
            }
        )

    def plan_collection_update(
        self,
        collection_key: str,
        *,
        name: str | None = None,
        parent: str | None = None,
        move_to_root: bool = False,
    ) -> dict[str, object]:
        if parent is not None and move_to_root:
            raise ValueError("Choose a parent collection or move to root, not both")
        key = normalize_key(collection_key, kind="collection")
        planning_context = self.planning_context()
        collections, _ = self._get_collections()
        records = {
            str(entry["key"]): entry for entry in collections if entry.get("key")
        }
        if key not in records:
            raise ValueError(f"Zotero collection key was not found: {key}")
        paths = build_collection_paths(collections)
        data = _collection_data(records[key])
        version = data.get("version", records[key].get("version"))
        if not isinstance(version, int):
            raise ZoteroManagementError(f"Collection {key} has no version")
        before = {
            "key": key,
            "version": version,
            "name": data.get("name") or "",
            "parentCollection": data.get("parentCollection") or False,
            "path": paths[key],
        }
        new_name = name.strip() if name is not None else str(before["name"])
        if not new_name:
            raise ValueError("Collection name cannot be blank")
        if move_to_root:
            new_parent: str | bool = False
        elif parent is not None:
            new_parent = resolve_collection_key(collections, parent)
        else:
            new_parent = before["parentCollection"]
        if new_parent == key:
            raise ValueError("A collection cannot be its own parent")
        descendants = self._descendant_keys(collections, key)
        if new_parent in descendants:
            raise ValueError("A collection cannot be moved below its descendant")
        after = {
            "key": key,
            "version": version,
            "name": new_name,
            "parentCollection": new_parent,
        }
        comparable_before = {
            field: before[field]
            for field in ("key", "version", "name", "parentCollection")
        }
        if comparable_before == after:
            raise ValueError("No collection changes would be made")
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "update_collection",
                **planning_context,
                "before": before,
                "after": after,
            }
        )

    @staticmethod
    def _descendant_keys(
        collections: list[dict[str, object]],
        parent_key: str,
    ) -> set[str]:
        descendants: set[str] = set()
        changed = True
        while changed:
            changed = False
            for entry in collections:
                key = str(entry.get("key") or "")
                data = _collection_data(entry)
                parent = str(data.get("parentCollection") or "")
                if (
                    key
                    and key not in descendants
                    and (parent == parent_key or parent in descendants)
                ):
                    descendants.add(key)
                    changed = True
        return descendants

    def _delete_state_many(
        self,
        collection_keys: list[str],
        collections: list[dict[str, object]],
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        records = {
            str(entry["key"]): entry for entry in collections if entry.get("key")
        }
        for collection_key in collection_keys:
            if collection_key not in records:
                raise ValueError(
                    f"Zotero collection key was not found: {collection_key}"
                )
        for collection_key in collection_keys:
            descendants = self._descendant_keys(collections, collection_key)
            redundant = descendants & set(collection_keys)
            if redundant:
                names = ", ".join(sorted(redundant))
                raise ValueError(
                    "A multi-collection delete cannot include both an ancestor "
                    f"and its descendant: {collection_key}, {names}"
                )
        paths = build_collection_paths(collections)
        deleted_keys: set[str] = set()
        for collection_key in collection_keys:
            deleted_keys.add(collection_key)
            deleted_keys.update(self._descendant_keys(collections, collection_key))
        collection_snapshot = []
        for key in sorted(deleted_keys, key=lambda value: paths[value].casefold()):
            record = records[key]
            data = _collection_data(record)
            version = data.get("version", record.get("version"))
            if not isinstance(version, int):
                raise ZoteroManagementError(f"Collection {key} has no version")
            collection_snapshot.append(
                {
                    "key": key,
                    "version": version,
                    "name": data.get("name") or "",
                    "parentCollection": data.get("parentCollection") or False,
                    "path": paths[key],
                }
            )

        affected_items = []
        for record in items:
            data = _item_data(record)
            memberships = self._copy_collection_keys(data.get("collections"))
            if not set(memberships) & deleted_keys:
                continue
            remaining = [key for key in memberships if key not in deleted_keys]
            key = str(record.get("key") or data.get("key") or "")
            version = data.get("version", record.get("version"))
            if not key or not isinstance(version, int):
                raise ZoteroManagementError(
                    "An affected Zotero item has no key or version"
                )
            affected_items.append(
                {
                    "key": key,
                    "version": version,
                    "title": data.get("title") or "",
                    "collections_before": memberships,
                    "remaining_collections": remaining,
                    "becomes_unfiled": not remaining,
                }
            )
        affected_items.sort(key=lambda entry: str(entry["key"]))
        snapshot_by_key = {
            str(entry["key"]): entry for entry in collection_snapshot
        }
        targets = [
            {
                "key": key,
                "path": snapshot_by_key[key]["path"],
                "version": snapshot_by_key[key]["version"],
            }
            for key in collection_keys
        ]
        return {
            "targets": targets,
            "collection_snapshot": collection_snapshot,
            "affected_items": affected_items,
            "impact": {
                "deleted_collection_count": len(collection_snapshot),
                "affected_item_count": len(affected_items),
                "becomes_unfiled_count": sum(
                    bool(entry["becomes_unfiled"]) for entry in affected_items
                ),
                "items_deleted": 0,
            },
        }

    def _delete_state(
        self,
        collection_key: str,
        collections: list[dict[str, object]],
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        state = self._delete_state_many([collection_key], collections, items)
        target = state.pop("targets")[0]
        return {"target": target, **state}

    def _delete_snapshot_items(
        self,
        collection_keys: list[str],
        collections: list[dict[str, object]],
        *,
        expected_library_version: int | None,
    ) -> list[dict[str, object]]:
        if self.backend != "web":
            items, _ = self._get_top_items()
            return items

        deleted_keys: set[str] = set()
        for collection_key in collection_keys:
            deleted_keys.add(collection_key)
            deleted_keys.update(self._descendant_keys(collections, collection_key))
        items_by_key: dict[str, dict[str, object]] = {}
        for collection_key in sorted(deleted_keys):
            items, response = self._get_all(
                self._library_path(f"collections/{collection_key}/items/top"),
                context=f"items in collection {collection_key}",
            )
            if (
                expected_library_version is not None
                and _response_version(response) != expected_library_version
            ):
                raise PlanDriftError(
                    "The Zotero library changed while reading the delete impact "
                    "snapshot"
                )
            for item in items:
                data = _item_data(item)
                key = str(item.get("key") or data.get("key") or "")
                if not key:
                    raise ZoteroManagementError(
                        "An affected Zotero item has no key"
                    )
                items_by_key[key] = item
        return list(items_by_key.values())

    def plan_collection_delete(
        self,
        collection_key: str,
    ) -> dict[str, object]:
        key = normalize_key(collection_key, kind="collection")
        planning_context = self.planning_context()
        collections, collections_response = self._get_collections()
        expected_version = (
            _response_version(collections_response)
            if self.backend == "web"
            else None
        )
        items = self._delete_snapshot_items(
            [key],
            collections,
            expected_library_version=expected_version,
        )
        state = self._delete_state(key, collections, items)
        if self.backend == "web":
            state["expected_library_version"] = expected_version
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "delete_collection",
                **planning_context,
                **state,
                "requires_delete_confirmation": key,
            }
        )

    def plan_collections_delete(
        self,
        collection_keys: list[str],
    ) -> dict[str, object]:
        if self.backend != "web":
            raise ValueError(
                "Multi-collection delete plans require the Zotero Web API backend"
            )
        keys = [normalize_key(key, kind="collection") for key in collection_keys]
        if len(keys) < 2:
            raise ValueError(
                "A multi-collection delete plan requires at least two keys"
            )
        if len(keys) > MAX_BATCH_ITEMS:
            raise ValueError(
                f"A delete plan can include at most {MAX_BATCH_ITEMS} collections"
            )
        if len(set(keys)) != len(keys):
            raise ValueError("A multi-collection delete plan contains duplicate keys")
        planning_context = self.planning_context()
        collections, collections_response = self._get_collections()
        expected_version = _response_version(collections_response)
        items = self._delete_snapshot_items(
            keys,
            collections,
            expected_library_version=expected_version,
        )
        state = self._delete_state_many(keys, collections, items)
        confirmation = ",".join(keys)
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "delete_collections",
                **planning_context,
                **state,
                "expected_library_version": expected_version,
                "requires_delete_confirmation": confirmation,
            }
        )

    def authorize_write(self, server_id: str) -> str:
        self.authorization_mode = "none"
        self._authorization_server_id = server_id
        if self._credential_store is not None:
            try:
                stored_key = self._credential_store.get(server_id)
            except CredentialStoreUnavailable:
                stored_key = None
            if stored_key:
                self.authorization_mode = "remembered_reused"
                return stored_key

        response = self._client.post(
            self._url("local/authorize"),
            headers={
                **API_HEADERS,
                "Zotero-Server-ID": server_id,
            },
            json={"appName": APP_NAME},
        )
        if response.status_code == 403:
            raise AuthorizationError("The Zotero write authorization was denied")
        response.raise_for_status()
        payload = _response_json(response, "local/authorize")
        if not isinstance(payload, dict) or not payload.get("key"):
            raise AuthorizationError(
                "Zotero did not return a local write authorization key"
            )
        api_key = str(payload["key"])
        if payload.get("remember") is True:
            if self._credential_store is None:
                raise AuthorizationError(
                    "Always Allow was selected, but no secure system credential "
                    "store is available. Clear Write Authorizations in Zotero "
                    "Settings → Advanced before continuing."
                )
            try:
                self._credential_store.set(server_id, api_key)
            except CredentialStoreUnavailable as exc:
                raise AuthorizationError(
                    "Always Allow was selected, but the key could not be saved "
                    "in a secure system credential store. Clear Write "
                    "Authorizations in Zotero Settings → Advanced."
                ) from exc
            self.authorization_mode = "remembered_new"
        else:
            self.authorization_mode = "one_time"
        return api_key

    def remembered_authorization_status(
        self,
        server_id: str,
    ) -> dict[str, object]:
        if self._credential_store is None:
            return {
                "server_id": server_id,
                "secure_store_available": False,
                "remembered_authorization": False,
            }
        try:
            stored = bool(self._credential_store.get(server_id))
        except CredentialStoreUnavailable:
            return {
                "server_id": server_id,
                "secure_store_available": False,
                "remembered_authorization": False,
            }
        return {
            "server_id": server_id,
            "secure_store_available": True,
            "remembered_authorization": stored,
        }

    def forget_remembered_authorization(self, server_id: str) -> bool:
        if self._credential_store is None:
            return False
        try:
            return self._credential_store.delete(server_id)
        except CredentialStoreUnavailable as exc:
            raise AuthorizationError(str(exc)) from exc

    def store_web_authorization(self, api_key: str) -> dict[str, object]:
        if self.backend != "web":
            raise AuthorizationError(
                "Web API authorization requires the Web API backend"
            )
        if self._credential_store is None:
            raise CredentialStoreUnavailable(
                "A recognized operating-system credential store is required "
                "for Zotero Web API keys"
            )
        candidate = api_key.strip()
        if not candidate:
            raise ValueError("Zotero Web API key cannot be blank")
        identity = self._validate_web_key(candidate)
        try:
            self._credential_store.set(self.web_profile, candidate)
        except CredentialStoreUnavailable as exc:
            raise AuthorizationError(
                "The Zotero Web API key could not be saved in a recognized "
                "operating-system credential store"
            ) from exc
        self._web_api_key = candidate
        self._web_identity = identity
        return {
            "web_profile": self.web_profile,
            "user_id": identity["user_id"],
            "username": identity["username"],
            "personal_library_write_access": True,
            "stored": True,
        }

    def web_authorization_status(self) -> dict[str, object]:
        if self.backend != "web":
            raise AuthorizationError(
                "Web API authorization requires the Web API backend"
            )
        if self._credential_store is None:
            return {
                "web_profile": self.web_profile,
                "secure_store_available": False,
                "stored_authorization": False,
            }
        try:
            stored = bool(self._credential_store.get(self.web_profile))
        except CredentialStoreUnavailable:
            return {
                "web_profile": self.web_profile,
                "secure_store_available": False,
                "stored_authorization": False,
            }
        return {
            "web_profile": self.web_profile,
            "secure_store_available": True,
            "stored_authorization": stored,
        }

    def forget_web_authorization(self) -> bool:
        if self.backend != "web":
            raise AuthorizationError(
                "Web API authorization requires the Web API backend"
            )
        if self._credential_store is None:
            return False
        try:
            removed = self._credential_store.delete(self.web_profile)
        except CredentialStoreUnavailable as exc:
            raise AuthorizationError(str(exc)) from exc
        if removed:
            self._web_api_key = None
            self._web_identity = None
        return removed

    def apply_plan(
        self,
        plan: dict[str, object],
        *,
        approval: str,
        confirm_delete: str | None = None,
    ) -> dict[str, object]:
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or approval != plan_id:
            raise ValueError("The approval must exactly match the plan ID")
        if plan.get("action") in {"delete_collection", "delete_collections"} and (
            confirm_delete != plan.get("requires_delete_confirmation")
        ):
            raise ValueError(
                "The delete confirmation must exactly match the collection key"
            )
        validate_plan(plan)
        plan_backend = str(plan.get("api_backend") or "local")
        if plan_backend not in {"local", "web"}:
            raise PlanIntegrityError("Zotero plan has an unsupported API backend")
        if plan_backend != self.backend:
            raise PlanDriftError("The plan belongs to a different Zotero API backend")
        if plan_backend == "web":
            if plan.get("application_mode") != "web_api":
                raise PlanIntegrityError(
                    "Zotero Web API plan has an invalid application mode"
                )
            if plan.get("web_profile") != self.web_profile:
                raise PlanDriftError(
                    "The plan belongs to a different Web API credential profile"
                )
            identity = self._ensure_web_identity()
            expected_library = {
                "type": "user",
                "id": identity["user_id"],
            }
            if plan.get("library") != expected_library:
                raise PlanDriftError(
                    "The plan belongs to a different Zotero personal library"
                )
            current_server_id: str | None = None
            self.authorization_mode = "web_api_key"
        else:
            current_server_id = self._validate_local_apply_context(plan)
        action = str(plan["action"])
        if action == "update_items":
            result = self._apply_items(plan, current_server_id)
        elif action == "create_collection":
            result = self._apply_collection_create(plan, current_server_id)
        elif action == "update_collection":
            result = self._apply_collection_update(plan, current_server_id)
        elif action in {"delete_collection", "delete_collections"}:
            result = self._apply_collection_delete(plan, current_server_id)
        else:  # pragma: no cover - validate_plan rejects unsupported actions
            raise PlanIntegrityError("Unsupported Zotero management plan action")
        receipt = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "action": action,
            "applied_at": _now(),
            "authorization_mode": self.authorization_mode,
            **result,
        }
        if plan_backend == "web":
            receipt.update(
                {
                    "api_backend": "web",
                    "application_mode": "web_api",
                    "library": plan["library"],
                    "web_profile": self.web_profile,
                }
            )
        return receipt

    def inspect_plan_state(self, plan: dict[str, object]) -> dict[str, object]:
        """Inspect a failed item or delete plan without issuing a write request."""
        validate_plan(plan)
        action = str(plan.get("action") or "")
        if action not in {
            "update_items",
            "delete_collection",
            "delete_collections",
        }:
            raise ValueError(
                "Read-only outcome inspection supports item and delete plans"
            )
        plan_backend = str(plan.get("api_backend") or "local")
        if plan_backend != self.backend:
            raise PlanDriftError("The plan belongs to a different Zotero API backend")
        if self.backend == "web":
            if plan.get("web_profile") != self.web_profile:
                raise PlanDriftError(
                    "The plan belongs to a different Web API credential profile"
                )
            identity = self._ensure_web_identity()
            if plan.get("library") != {"type": "user", "id": identity["user_id"]}:
                raise PlanDriftError(
                    "The plan belongs to a different Zotero personal library"
                )
        else:
            current_context = self.planning_context()
            planned_server_id = plan.get("server_id")
            if planned_server_id is not None and (
                current_context.get("server_id") != planned_server_id
            ):
                raise PlanDriftError(
                    "The plan belongs to a different Zotero database instance"
                )

        base = {
            "plan_id": plan["plan_id"],
            "action": action,
        }
        if action == "update_items":
            changes = plan.get("changes")
            if not isinstance(changes, list) or not changes:
                raise PlanIntegrityError("Item plan contains no changes")
            states = []
            for change in changes:
                if not isinstance(change, dict):
                    raise PlanIntegrityError("Item plan contains a malformed change")
                key = normalize_key(str(change.get("key") or ""), kind="item")
                current = self._get_item(key)
                data = _item_data(current)
                after = change.get("after")
                if not isinstance(after, dict):
                    raise PlanIntegrityError("Item plan has malformed after state")
                if self._same_tags(data.get("tags"), after.get("tags")) and (
                    self._same_collection_memberships(
                        data.get("collections"),
                        after.get("collections"),
                    )
                ):
                    states.append("applied")
                elif self._before_matches(current, change):
                    states.append("not_applied")
                else:
                    states.append("indeterminate")
            if set(states) == {"applied"}:
                return {
                    **base,
                    "outcome": "applied",
                    "safe_to_retry": False,
                    "verified": True,
                }
            if set(states) == {"not_applied"}:
                return {
                    **base,
                    "outcome": "not_applied",
                    "safe_to_retry": True,
                    "verified": True,
                }
            return {
                **base,
                "outcome": "indeterminate",
                "safe_to_retry": False,
                "verified": False,
            }

        keys = self._delete_plan_keys(plan)
        snapshot = plan.get("collection_snapshot")
        if not isinstance(snapshot, list) or not snapshot:
            raise PlanIntegrityError("Collection delete plan has no snapshot")
        collections, collections_response = self._get_collections()
        current_keys = {
            str(entry.get("key") or "") for entry in collections if entry.get("key")
        }
        deleted_keys = {
            str(entry.get("key") or "")
            for entry in snapshot
            if isinstance(entry, dict) and entry.get("key")
        }
        present = current_keys & deleted_keys
        if not present:
            preserved = True
            for affected in plan.get("affected_items", []):
                if not isinstance(affected, dict):
                    preserved = False
                    break
                try:
                    current = self._get_item(str(affected.get("key") or ""))
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        preserved = False
                        break
                    raise
                data = _item_data(current)
                memberships = self._copy_collection_keys(data.get("collections"))
                if not self._same_collection_memberships(
                    memberships,
                    affected.get("remaining_collections"),
                ) or set(memberships) & deleted_keys:
                    preserved = False
                    break
            if preserved:
                return {
                    **base,
                    "outcome": "applied",
                    "safe_to_retry": False,
                    "verified": True,
                }
            return {
                **base,
                "outcome": "indeterminate",
                "safe_to_retry": False,
                "verified": False,
            }

        if present != deleted_keys:
            return {
                **base,
                "outcome": "indeterminate",
                "safe_to_retry": False,
                "verified": False,
            }

        current_version = (
            _response_version(collections_response)
            if self.backend == "web"
            else None
        )
        items = self._delete_snapshot_items(
            keys,
            collections,
            expected_library_version=current_version,
        )
        current_state = (
            self._delete_state_many(keys, collections, items)
            if action == "delete_collections"
            else self._delete_state(keys[0], collections, items)
        )
        fields = ["collection_snapshot", "affected_items", "impact"]
        fields.append("targets" if action == "delete_collections" else "target")
        unchanged = all(current_state[field] == plan.get(field) for field in fields)
        if unchanged:
            expected_version = plan.get("expected_library_version")
            safe_to_retry = self.backend != "web" or (
                isinstance(expected_version, int)
                and not isinstance(expected_version, bool)
                and current_version == expected_version
            )
            return {
                **base,
                "outcome": "not_applied",
                "safe_to_retry": safe_to_retry,
                "verified": True,
            }
        return {
            **base,
            "outcome": "indeterminate",
            "safe_to_retry": False,
            "verified": False,
        }

    def _validate_local_apply_context(self, plan: dict[str, object]) -> str:
        if (
            plan.get("application_mode") == "manual_zotero_desktop"
            or plan.get("local_api_write_supported") is False
            or not isinstance(plan.get("server_id"), str)
        ):
            raise ZoteroManagementError(
                "This plan was created by a Zotero version with a GET-only "
                "Local API. Apply it manually in Zotero Desktop; this helper "
                "will not request authorization or send a write."
            )
        current_server_id = self.server_id()
        if current_server_id != plan.get("server_id"):
            raise PlanDriftError(
                "The plan belongs to a different Zotero database instance"
            )
        return current_server_id

    @staticmethod
    def _before_matches(
        record: dict[str, object],
        change: dict[str, object],
    ) -> bool:
        data = _item_data(record)
        before = change.get("before")
        if not isinstance(before, dict):
            raise PlanIntegrityError("Item plan has malformed before state")
        return (
            data.get("version", record.get("version")) == change.get("version")
            and ManageZotero._same_tags(data.get("tags"), before.get("tags"))
            and ManageZotero._same_collection_memberships(
                data.get("collections"),
                before.get("collections"),
            )
        )

    def _write_headers(
        self,
        server_id: str | None,
        api_key: str,
        *,
        version: int | None = None,
    ) -> dict[str, str]:
        headers = {**API_HEADERS, "Zotero-API-Key": api_key}
        if server_id is not None:
            headers["Zotero-Server-ID"] = server_id
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        return headers

    def _write_request(
        self,
        method: str,
        path: str,
        *,
        server_id: str | None,
        params: dict[str, object] | None = None,
        json_body: object | None = None,
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            return self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
            )
        except httpx.HTTPStatusError as exc:
            if self.backend == "web" and exc.response.status_code in {401, 403}:
                self.authorization_mode = "web_api_key_rejected"
                raise AuthorizationError(
                    "The stored Zotero Web API key was rejected. The credential "
                    "was preserved and the write was not retried. Run "
                    "web-auth-status to inspect the selected profile or use the "
                    "explicit web-auth-forget flow to remove it."
                ) from exc
            if exc.response.status_code == 412:
                raise PlanDriftError(
                    "The Zotero library changed after the plan was prepared; "
                    "the versioned write was rejected"
                ) from exc
            if exc.response.status_code == 401 and self.authorization_mode.startswith(
                "remembered_"
            ):
                try:
                    self.forget_remembered_authorization(server_id)
                except AuthorizationError as delete_exc:
                    raise AuthorizationError(
                        "The stored Zotero authorization was rejected, and its "
                        "local credential could not be removed. Clear it from "
                        "the operating-system credential store manually."
                    ) from delete_exc
                self.authorization_mode = "remembered_rejected"
                raise AuthorizationError(
                    "The stored Zotero authorization was rejected and removed. "
                    "Run apply again to request a new authorization; the write "
                    "was not retried automatically."
                ) from exc
            raise

    def _api_key_for_write(self, server_id: str | None) -> str:
        if self.backend == "web":
            self._ensure_web_identity()
            self.authorization_mode = "web_api_key"
            return self._stored_web_key()
        if server_id is None:
            raise PlanIntegrityError("Local API write has no Zotero server ID")
        return self.authorize_write(server_id)

    def _apply_items(
        self,
        plan: dict[str, object],
        server_id: str | None,
    ) -> dict[str, object]:
        changes = plan.get("changes")
        if not isinstance(changes, list) or not changes:
            raise PlanIntegrityError("Item plan contains no changes")
        if self.backend == "local":
            self._assert_items_unchanged(changes)
        api_key = self._api_key_for_write(server_id)
        self._assert_items_unchanged(changes)

        payload = []
        for change in changes:
            after = change.get("after")
            if not isinstance(after, dict):
                raise PlanIntegrityError("Item plan has malformed after state")
            payload.append(
                {
                    "key": change["key"],
                    "version": change["version"],
                    "tags": after.get("tags", []),
                    "collections": after.get("collections", []),
                }
            )
        response = self._write_request(
            "POST",
            self._library_path("items"),
            server_id=server_id,
            json_body=payload,
            headers=self._write_headers(server_id, api_key),
        )
        write_result = _response_json(response, "item batch update")
        if not isinstance(write_result, dict):
            raise ZoteroManagementError(
                "Zotero returned a malformed item update result"
            )
        failed = write_result.get("failed")
        failures = failed if isinstance(failed, dict) else {}
        verification = []
        verified = not failures
        for change in changes:
            key = str(change["key"])
            current = self._get_item(key)
            data = _item_data(current)
            after = change["after"]
            item_verified = (
                self._same_tags(data.get("tags"), after["tags"])
                and self._same_collection_memberships(
                    data.get("collections"),
                    after["collections"],
                )
            )
            verification.append({"key": key, "verified": item_verified})
            verified = verified and item_verified
        return {
            "verified": verified,
            "verification": verification,
            "write_failures": failures,
            "inverse": [
                {
                    "key": change["key"],
                    "restore": change["before"],
                }
                for change in changes
            ],
        }

    def _assert_items_unchanged(
        self,
        changes: list[object],
    ) -> None:
        for change in changes:
            if not isinstance(change, dict):
                raise PlanIntegrityError("Item plan contains a malformed change")
            key = normalize_key(str(change.get("key") or ""), kind="item")
            if not self._before_matches(self._get_item(key), change):
                raise PlanDriftError(
                    f"Zotero item {key} changed after the plan was prepared"
                )

    def _apply_collection_create(
        self,
        plan: dict[str, object],
        server_id: str | None,
    ) -> dict[str, object]:
        collections, response = self._get_collections()
        expected_version = plan.get("expected_library_version")
        if _response_version(response) != expected_version:
            raise PlanDriftError(
                "The Zotero library changed after the plan was prepared"
            )
        after = plan.get("after")
        if not isinstance(after, dict):
            raise PlanIntegrityError("Collection plan has malformed after state")
        parent = after.get("parentCollection")
        if parent and str(parent) not in {
            str(entry.get("key") or "") for entry in collections
        }:
            raise PlanDriftError("The planned parent collection no longer exists")
        api_key = self._api_key_for_write(server_id)
        write_response = self._write_request(
            "POST",
            self._library_path("collections"),
            server_id=server_id,
            json_body=[after],
            headers=self._write_headers(
                server_id,
                api_key,
                version=int(expected_version),
            ),
        )
        payload = _response_json(write_response, "collection creation")
        created_key = self._created_object_key(payload)
        created = self._get_collection(created_key)
        data = _collection_data(created)
        verified = data.get("name") == after.get("name") and (
            data.get("parentCollection") or False
        ) == (after.get("parentCollection") or False)
        return {
            "verified": verified,
            "created_collection_key": created_key,
        }

    @staticmethod
    def _created_object_key(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ZoteroManagementError("Malformed Zotero creation response")
        successful = payload.get("successful", payload.get("success"))
        if not isinstance(successful, dict) or not successful:
            raise ZoteroManagementError("Zotero did not create the collection")
        value = next(iter(successful.values()))
        if isinstance(value, str):
            return normalize_key(value, kind="collection")
        if isinstance(value, dict):
            data = value.get("data")
            key = value.get("key")
            if not key and isinstance(data, dict):
                key = data.get("key")
            return normalize_key(str(key or ""), kind="collection")
        raise ZoteroManagementError("Malformed Zotero collection creation result")

    def _get_collection(self, key: str) -> dict[str, object]:
        payload = self._get_json(self._library_path(f"collections/{key}"))
        if not isinstance(payload, dict):
            raise ZoteroManagementError(f"Zotero collection {key} is malformed")
        return payload

    def _apply_collection_update(
        self,
        plan: dict[str, object],
        server_id: str | None,
    ) -> dict[str, object]:
        before = plan.get("before")
        after = plan.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise PlanIntegrityError("Collection update plan is malformed")
        key = normalize_key(str(before.get("key") or ""), kind="collection")
        current = self._get_collection(key)
        data = _collection_data(current)
        current_state = {
            "key": key,
            "version": data.get("version", current.get("version")),
            "name": data.get("name") or "",
            "parentCollection": data.get("parentCollection") or False,
        }
        expected = {
            field: before[field]
            for field in ("key", "version", "name", "parentCollection")
        }
        if current_state != expected:
            raise PlanDriftError(
                f"Collection {key} changed after the plan was prepared"
            )
        api_key = self._api_key_for_write(server_id)
        self._write_request(
            "PUT",
            self._library_path(f"collections/{key}"),
            server_id=server_id,
            json_body=after,
            headers=self._write_headers(server_id, api_key),
        )
        updated = _collection_data(self._get_collection(key))
        verified = updated.get("name") == after.get("name") and (
            updated.get("parentCollection") or False
        ) == (after.get("parentCollection") or False)
        return {
            "verified": verified,
            "inverse": {
                "key": key,
                "name": before["name"],
                "parentCollection": before["parentCollection"],
            },
        }

    def _apply_collection_delete(
        self,
        plan: dict[str, object],
        server_id: str | None,
    ) -> dict[str, object]:
        keys = self._delete_plan_keys(plan)
        if self.backend == "local" and len(keys) != 1:
            raise PlanIntegrityError(
                "Local API collection deletion supports one target per plan"
            )
        self._assert_delete_state_unchanged(plan, keys)
        api_key = self._api_key_for_write(server_id)
        if self.backend == "local":
            # The authorization dialog can remain open while the user edits
            # Zotero. Recheck immediately before using the granted key.
            self._assert_delete_state_unchanged(plan, keys)
        if self.backend == "web":
            expected_version = plan.get("expected_library_version")
            if (
                not isinstance(expected_version, int)
                or isinstance(expected_version, bool)
                or expected_version < 0
            ):
                raise PlanIntegrityError(
                    "Web collection delete plan has no library version"
                )
            delete_path = self._library_path("collections")
            delete_params: dict[str, object] | None = {
                "collectionKey": ",".join(keys)
            }
            delete_version = expected_version
        else:
            target = plan.get("target")
            if not isinstance(target, dict):
                raise PlanIntegrityError("Collection delete plan has no target")
            key = keys[0]
            delete_path = self._library_path(f"collections/{key}")
            delete_params = None
            delete_version = int(target["version"])
        self._write_request(
            "DELETE",
            delete_path,
            server_id=server_id,
            params=delete_params,
            headers=self._write_headers(
                server_id,
                api_key,
                version=delete_version,
            ),
        )

        deleted_keys = {str(entry["key"]) for entry in plan["collection_snapshot"]}
        missing_collections = []
        for deleted_key in sorted(deleted_keys):
            response = self._client.get(
                self._url(self._library_path(f"collections/{deleted_key}")),
                headers=(
                    {"Zotero-API-Key": self._stored_web_key()}
                    if self.backend == "web"
                    else None
                ),
            )
            if response.status_code != 404:
                missing_collections.append(deleted_key)
        item_verification = []
        items_preserved = True
        for affected in plan["affected_items"]:
            item_key = str(affected["key"])
            current = self._get_item(item_key)
            data = _item_data(current)
            memberships = self._copy_collection_keys(data.get("collections"))
            memberships_match = (
                self._same_collection_memberships(
                    memberships,
                    affected["remaining_collections"],
                )
                and not set(memberships) & deleted_keys
            )
            item_verification.append(
                {
                    "key": item_key,
                    "exists": True,
                    "memberships_match": memberships_match,
                }
            )
            items_preserved = items_preserved and memberships_match
        verified = not missing_collections and items_preserved
        return {
            "verified": verified,
            "collections_still_present": missing_collections,
            "item_verification": item_verification,
            "items_deleted": 0,
            "reconstruction_snapshot": {
                "collections": plan["collection_snapshot"],
                "affected_items": plan["affected_items"],
            },
        }

    @staticmethod
    def _delete_plan_keys(plan: dict[str, object]) -> list[str]:
        if plan.get("action") == "delete_collections":
            targets = plan.get("targets")
            if not isinstance(targets, list) or len(targets) < 2:
                raise PlanIntegrityError(
                    "Multi-collection delete plan has malformed targets"
                )
            keys = []
            for target in targets:
                if not isinstance(target, dict):
                    raise PlanIntegrityError(
                        "Multi-collection delete plan has malformed targets"
                    )
                keys.append(
                    normalize_key(
                        str(target.get("key") or ""),
                        kind="collection",
                    )
                )
            return keys
        target = plan.get("target")
        if not isinstance(target, dict):
            raise PlanIntegrityError("Collection delete plan has no target")
        return [
            normalize_key(str(target.get("key") or ""), kind="collection")
        ]

    def _assert_delete_state_unchanged(
        self,
        plan: dict[str, object],
        keys: list[str],
    ) -> None:
        collections, collections_response = self._get_collections()
        expected_version = (
            plan.get("expected_library_version")
            if self.backend == "web"
            else None
        )
        if self.backend == "web":
            if not isinstance(expected_version, int) or isinstance(
                expected_version, bool
            ):
                raise PlanIntegrityError(
                    "Web collection delete plan has no library version"
                )
            if _response_version(collections_response) != expected_version:
                raise PlanDriftError(
                    "The Zotero library changed after the delete impact snapshot "
                    "was prepared"
                )
        items = self._delete_snapshot_items(
            keys,
            collections,
            expected_library_version=(
                expected_version if isinstance(expected_version, int) else None
            ),
        )
        current_state = (
            self._delete_state_many(keys, collections, items)
            if plan.get("action") == "delete_collections"
            else self._delete_state(keys[0], collections, items)
        )
        state_fields = ["collection_snapshot", "affected_items", "impact"]
        state_fields.append(
            "targets" if plan.get("action") == "delete_collections" else "target"
        )
        for field in state_fields:
            if current_state[field] != plan.get(field):
                raise PlanDriftError(
                    "The collection tree or membership changed after the plan "
                    "was prepared"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Plan and apply approved Zotero API organization changes"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_backend_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--backend",
            choices=("local", "web"),
            default="local",
            help="Use the Local API by default or opt in to the official Web API",
        )
        command_parser.add_argument(
            "--web-profile",
            default="default",
            help="OS credential-store profile for an opted-in Web API key",
        )

    items_parser = subparsers.add_parser(
        "plan-items",
        help="Create a no-write plan for tags and collection memberships",
    )
    items_parser.add_argument("item_keys", nargs="+")
    items_parser.add_argument("--add-tag", action="append", default=[])
    items_parser.add_argument("--remove-tag", action="append", default=[])
    items_parser.add_argument("--add-collection", action="append", default=[])
    items_parser.add_argument("--remove-collection", action="append", default=[])
    items_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(items_parser)

    manifest_parser = subparsers.add_parser(
        "plan-items-manifest",
        help="Create a no-write plan from per-item tag and collection changes",
    )
    manifest_parser.add_argument("manifest", type=Path)
    manifest_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(manifest_parser)

    create_parser = subparsers.add_parser(
        "plan-collection-create",
        help="Create a no-write plan for a new collection",
    )
    create_parser.add_argument("name")
    create_parser.add_argument("--parent")
    create_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(create_parser)

    update_parser = subparsers.add_parser(
        "plan-collection-update",
        help="Create a no-write plan to rename or move a collection",
    )
    update_parser.add_argument("collection_key")
    update_parser.add_argument("--name")
    parent_group = update_parser.add_mutually_exclusive_group()
    parent_group.add_argument("--parent")
    parent_group.add_argument("--root", action="store_true")
    update_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(update_parser)

    delete_parser = subparsers.add_parser(
        "plan-collection-delete",
        help="Create a no-write cascade-impact plan for collection deletion",
    )
    delete_parser.add_argument("collection_key")
    delete_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(delete_parser)

    multi_delete_parser = subparsers.add_parser(
        "plan-collections-delete",
        help="Create one Web API plan to delete multiple collections",
    )
    multi_delete_parser.add_argument("collection_keys", nargs="+")
    multi_delete_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(multi_delete_parser)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply an unchanged plan after explicit approval",
    )
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--approve", required=True)
    apply_parser.add_argument("--confirm-delete")
    apply_parser.add_argument("--receipt", type=Path, required=True)
    add_backend_options(apply_parser)

    inspect_parser = subparsers.add_parser(
        "inspect-plan-state",
        help="Read current state after an indeterminate item or delete write",
    )
    inspect_parser.add_argument("plan", type=Path)
    inspect_parser.add_argument("--output", type=Path, required=True)
    add_backend_options(inspect_parser)

    subparsers.add_parser(
        "auth-status",
        help="Report whether a remembered authorization is securely stored",
    )
    subparsers.add_parser(
        "auth-forget",
        help="Forget this tool's stored key for the current Zotero database",
    )
    web_store_parser = subparsers.add_parser(
        "web-auth-store",
        help="Validate and securely store a personal-library Web API key",
    )
    web_store_parser.add_argument("--web-profile", default="default")
    web_status_parser = subparsers.add_parser(
        "web-auth-status",
        help="Report whether a Web API key is stored for a credential profile",
    )
    web_status_parser.add_argument("--web-profile", default="default")
    web_forget_parser = subparsers.add_parser(
        "web-auth-forget",
        help="Remove a Web API key from one credential profile",
    )
    web_forget_parser.add_argument("--web-profile", default="default")
    return parser


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _load_json_array(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(
        not isinstance(entry, dict) for entry in payload
    ):
        raise ValueError(f"JSON file must contain an array of objects: {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = (
        "web"
        if args.command.startswith("web-auth-")
        else getattr(args, "backend", "local")
    )
    web_profile = getattr(args, "web_profile", "default")
    active_plan: dict[str, object] | None = None

    def recovery_step(plan: dict[str, object]) -> str:
        if plan.get("action") in {
            "update_items",
            "delete_collection",
            "delete_collections",
        }:
            return "Run inspect-plan-state before any retry"
        return "Perform read-only inspection before any retry"

    try:
        web_api_key = prompt_web_api_key() if args.command == "web-auth-store" else None
        if args.command == "apply":
            output: Path | None = args.receipt
        elif args.command == "inspect-plan-state" or args.command.startswith("plan-"):
            output = args.output
        else:
            output = None
        if output is not None:
            ensure_output_available(output)
        with ManageZotero(
            backend=backend,
            web_profile=web_profile,
        ) as client:
            if args.command == "plan-items":
                result = client.plan_items(
                    args.item_keys,
                    add_tags=args.add_tag,
                    remove_tags=args.remove_tag,
                    add_collections=args.add_collection,
                    remove_collections=args.remove_collection,
                )
            elif args.command == "plan-items-manifest":
                result = client.plan_items_manifest(_load_json_array(args.manifest))
            elif args.command == "plan-collection-create":
                result = client.plan_collection_create(
                    args.name,
                    parent=args.parent,
                )
            elif args.command == "plan-collection-update":
                result = client.plan_collection_update(
                    args.collection_key,
                    name=args.name,
                    parent=args.parent,
                    move_to_root=args.root,
                )
            elif args.command == "plan-collection-delete":
                result = client.plan_collection_delete(args.collection_key)
            elif args.command == "plan-collections-delete":
                result = client.plan_collections_delete(args.collection_keys)
            elif args.command == "apply":
                plan = _load_json_object(args.plan)
                active_plan = plan
                result = client.apply_plan(
                    plan,
                    approval=args.approve,
                    confirm_delete=args.confirm_delete,
                )
            elif args.command == "inspect-plan-state":
                plan = _load_json_object(args.plan)
                active_plan = plan
                result = client.inspect_plan_state(plan)
            elif args.command == "auth-status":
                server_id = client.server_id()
                result = client.remembered_authorization_status(server_id)
            elif args.command == "auth-forget":
                server_id = client.server_id()
                removed = client.forget_remembered_authorization(server_id)
                result = {
                    "server_id": server_id,
                    "local_credential_removed": removed,
                    "zotero_revocation_required": True,
                }
            elif args.command == "web-auth-store":
                if web_api_key is None:  # pragma: no cover - command fixes type
                    raise AuthorizationError("No Zotero Web API key was provided")
                result = client.store_web_authorization(web_api_key)
            elif args.command == "web-auth-status":
                result = client.web_authorization_status()
            else:
                result = {
                    "web_profile": client.web_profile,
                    "stored_credential_removed": (client.forget_web_authorization()),
                    "zotero_key_revocation_required": True,
                }
        if output is not None:
            write_json_exclusive(output, result)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print_json(
            {
                "error": (
                    "Cannot connect to the selected Zotero API backend. For "
                    "Local API access, start Zotero Desktop and enable local "
                    "application access."
                )
            }
        )
        return 1
    except httpx.TimeoutException:
        if args.command == "apply" and active_plan is not None:
            print_json(
                {
                    "error": "Zotero write outcome is indeterminate after timeout",
                    "outcome": "indeterminate",
                    "plan_id": active_plan.get("plan_id"),
                    "action": active_plan.get("action"),
                    "safe_to_retry": False,
                    "next_step": recovery_step(active_plan),
                }
            )
        else:
            print_json({"error": "Zotero API request timed out"})
        return 1
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if args.command == "apply" and active_plan is not None and status >= 500:
            print_json(
                {
                    "error": (
                        "Zotero write outcome is indeterminate after "
                        f"HTTP {status}"
                    ),
                    "outcome": "indeterminate",
                    "plan_id": active_plan.get("plan_id"),
                    "action": active_plan.get("action"),
                    "safe_to_retry": False,
                    "next_step": recovery_step(active_plan),
                }
            )
        else:
            print_json({"error": f"Zotero API request failed with HTTP {status}"})
        return 1
    except (
        FileExistsError,
        OSError,
        ValueError,
        ZoteroManagementError,
        json.JSONDecodeError,
    ) as exc:
        print_json({"error": str(exc)})
        return 1

    if output is None:
        print_json(result)
    else:
        print_json({"output": str(output), **result})
    return 0 if bool(result.get("verified", True)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
