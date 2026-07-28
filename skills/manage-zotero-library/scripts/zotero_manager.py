#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
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
API_HEADERS = {"Zotero-API-Version": "3"}
APP_NAME = "Social Science Research Skills"
KEYRING_SERVICE = "social-science-research-skills.zotero-local-api"
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
    """A one-time or remembered local write authorization cannot be used."""


class PlanIntegrityError(ZoteroManagementError):
    """A plan is malformed or changed after it was signed."""


class CredentialStoreUnavailable(AuthorizationError):
    """No supported operating-system credential store is available."""


class CredentialStore(Protocol):
    def get(self, server_id: str) -> str | None:
        """Return a remembered key without exposing it to output."""

    def set(self, server_id: str, key: str) -> None:
        """Save a remembered key for one Zotero database."""

    def delete(self, server_id: str) -> bool:
        """Delete a remembered key and report whether one existed."""


class SystemCredentialStore:
    """Store Zotero keys only in recognized operating-system secret stores."""

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
            value = backend.get_password(KEYRING_SERVICE, server_id)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "Could not read the operating-system credential store"
            ) from exc
        return str(value) if value else None

    def set(self, server_id: str, key: str) -> None:
        backend = self._backend()
        try:
            backend.set_password(KEYRING_SERVICE, server_id, key)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "Could not save the remembered Zotero authorization"
            ) from exc

    def delete(self, server_id: str) -> bool:
        backend = self._backend()
        try:
            existing = backend.get_password(KEYRING_SERVICE, server_id)
            if not existing:
                return False
            backend.delete_password(KEYRING_SERVICE, server_id)
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
        raise ValueError(
            f"Zotero Local API base URL must use port {LOCAL_API_PORT}"
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            "Zotero Local API base URL must not contain a query or fragment"
        )
    if parsed.path.rstrip("/") != "/api":
        raise ValueError("Zotero Local API base URL must end with /api/")
    return base_url.rstrip("/") + "/"


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
            raise ZoteroManagementError(
                "Zotero collection hierarchy contains a cycle"
            )
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
    key_matches = [
        key for key in by_key if key.casefold() == requested.casefold()
    ]
    if len(key_matches) == 1:
        return key_matches[0]

    normalized = _normalize_collection_path(requested)
    if not normalized:
        raise ValueError("Collection name cannot be empty")
    paths = build_collection_paths(collections)
    path_matches = [
        key
        for key, path in paths.items()
        if path.casefold() == normalized.casefold()
    ]
    if len(path_matches) == 1:
        return path_matches[0]
    if "/" not in requested:
        name_matches = [
            key
            for key, path in paths.items()
            if path.rsplit(" / ", maxsplit=1)[-1].casefold()
            == normalized.casefold()
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
            f"Zotero Local API returned invalid JSON for {context}"
        ) from exc


def _response_version(response: httpx.Response) -> int:
    value = response.headers.get("Last-Modified-Version", "")
    if not value.isdecimal():
        raise ZoteroManagementError(
            "Zotero Local API did not report Last-Modified-Version"
        )
    return int(value)


class ManageZotero:
    """Plan and apply narrowly scoped Zotero Local API writes."""

    def __init__(
        self,
        *,
        base_url: str = LOCAL_API_BASE,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        credential_store: CredentialStore | None | object = AUTO_CREDENTIAL_STORE,
    ) -> None:
        self.base_url = validate_local_api_base(base_url)
        if credential_store is AUTO_CREDENTIAL_STORE:
            self._credential_store: CredentialStore | None = (
                SystemCredentialStore() if transport is None else None
            )
        else:
            self._credential_store = credential_store  # type: ignore[assignment]
        self.authorization_mode = "none"
        self._authorization_server_id: str | None = None
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
        response = self._client.request(
            method,
            self._url(path),
            params=params,
            json=json_body,
            headers=headers,
        )
        if response.status_code == 403 and method == "GET":
            raise ZoteroManagementError(
                "Zotero Local API is disabled. Enable local application access "
                "in Zotero Settings → Advanced."
            )
        response.raise_for_status()
        return response

    def _get_json(self, path: str) -> object:
        response = self._request("GET", path)
        return _response_json(response, path)

    def server_id(self) -> str:
        response = self._request("GET", "")
        server_id = response.headers.get("Zotero-Server-ID", "").strip()
        if not server_id:
            raise ZoteroManagementError(
                "Zotero Local API did not report Zotero-Server-ID"
            )
        return server_id

    def _get_item(self, key: str) -> dict[str, object]:
        payload = self._get_json(f"users/0/items/{key}")
        if not isinstance(payload, dict):
            raise ZoteroManagementError(f"Zotero item {key} is malformed")
        return payload

    def _get_collections(
        self,
    ) -> tuple[list[dict[str, object]], httpx.Response]:
        return self._get_all("users/0/collections", context="collections")

    def _get_top_items(self) -> list[dict[str, object]]:
        items, _ = self._get_all(
            "users/0/items/top",
            context="top-level items",
        )
        return items

    def _get_all(
        self,
        path: str,
        *,
        context: str,
    ) -> tuple[list[dict[str, object]], httpx.Response]:
        records: list[dict[str, object]] = []
        first_response: httpx.Response | None = None
        start = 0
        while True:
            response = self._request(
                "GET",
                path,
                params={"limit": PAGE_SIZE, "start": start},
            )
            if first_response is None:
                first_response = response
            payload = _response_json(response, context)
            if not isinstance(payload, list) or any(
                not isinstance(entry, dict) for entry in payload
            ):
                raise ZoteroManagementError(
                    f"Zotero Local API returned malformed {context}"
                )
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
        keys = list(
            dict.fromkeys(normalize_key(key, kind="item") for key in item_keys)
        )
        if not keys:
            raise ValueError("At least one Zotero item key is required")
        if len(keys) > MAX_BATCH_ITEMS:
            raise ValueError(
                f"A management plan can include at most {MAX_BATCH_ITEMS} items"
            )
        added_tags = self._normalize_tags(add_tags or [])
        removed_tags = self._normalize_tags(remove_tags or [])
        if set(added_tags) & set(removed_tags):
            raise ValueError("The same tag cannot be added and removed")

        collection_additions = add_collections or []
        collection_removals = remove_collections or []
        collections: list[dict[str, object]] = []
        if collection_additions or collection_removals:
            collections, _ = self._get_collections()
        added_collection_keys = [
            resolve_collection_key(collections, value)
            for value in collection_additions
        ]
        removed_collection_keys = [
            resolve_collection_key(collections, value)
            for value in collection_removals
        ]
        if set(added_collection_keys) & set(removed_collection_keys):
            raise ValueError("The same collection cannot be added and removed")

        server_id = self.server_id()
        changes: list[dict[str, object]] = []
        for key in keys:
            record = self._get_item(key)
            data = _item_data(record)
            if data.get("parentItem"):
                raise ValueError(
                    f"Zotero item {key} is not a top-level bibliographic item"
                )
            before_tags = self._copy_tags(data.get("tags"))
            before_collections = self._copy_collection_keys(
                data.get("collections")
            )
            after_tags = [
                tag
                for tag in before_tags
                if str(tag["tag"]) not in set(removed_tags)
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

            if (
                before_tags == after_tags
                and before_collections == after_collections
            ):
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
                "server_id": server_id,
                "summary": {
                    "changed_item_count": len(changes),
                    "requested_item_count": len(keys),
                },
                "changes": changes,
            }
        )

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
        return [
            dict(tag)
            for tag in value
            if isinstance(tag, dict) and tag.get("tag")
        ]

    @staticmethod
    def _copy_collection_keys(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(key) for key in value if key]

    def plan_collection_create(
        self,
        name: str,
        *,
        parent: str | None = None,
    ) -> dict[str, object]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Collection name cannot be blank")
        server_id = self.server_id()
        collections, response = self._get_collections()
        parent_key = (
            resolve_collection_key(collections, parent) if parent else False
        )
        for entry in collections:
            data = _collection_data(entry)
            if (
                str(data.get("name") or "").casefold()
                == normalized_name.casefold()
                and (data.get("parentCollection") or False) == parent_key
            ):
                raise ValueError("A collection with that name already exists")
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "create_collection",
                "server_id": server_id,
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
        server_id = self.server_id()
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
                "server_id": server_id,
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

    def _delete_state(
        self,
        collection_key: str,
        collections: list[dict[str, object]],
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        records = {
            str(entry["key"]): entry for entry in collections if entry.get("key")
        }
        if collection_key not in records:
            raise ValueError(
                f"Zotero collection key was not found: {collection_key}"
            )
        paths = build_collection_paths(collections)
        deleted_keys = {
            collection_key,
            *self._descendant_keys(collections, collection_key),
        }
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
            remaining = [
                key for key in memberships if key not in deleted_keys
            ]
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
        target = next(
            entry
            for entry in collection_snapshot
            if entry["key"] == collection_key
        )
        return {
            "target": {
                "key": collection_key,
                "path": target["path"],
                "version": target["version"],
            },
            "collection_snapshot": collection_snapshot,
            "affected_items": affected_items,
            "impact": {
                "deleted_collection_count": len(collection_snapshot),
                "affected_item_count": len(affected_items),
                "becomes_unfiled_count": sum(
                    bool(entry["becomes_unfiled"])
                    for entry in affected_items
                ),
                "items_deleted": 0,
            },
        }

    def plan_collection_delete(
        self,
        collection_key: str,
    ) -> dict[str, object]:
        key = normalize_key(collection_key, kind="collection")
        server_id = self.server_id()
        collections, _ = self._get_collections()
        state = self._delete_state(key, collections, self._get_top_items())
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "delete_collection",
                "server_id": server_id,
                **state,
                "requires_delete_confirmation": key,
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
        if (
            plan.get("action") == "delete_collection"
            and confirm_delete != plan.get("requires_delete_confirmation")
        ):
            raise ValueError(
                "The delete confirmation must exactly match the collection key"
            )
        validate_plan(plan)
        current_server_id = self.server_id()
        if current_server_id != plan.get("server_id"):
            raise PlanDriftError(
                "The plan belongs to a different Zotero database instance"
            )
        action = str(plan["action"])
        if action == "update_items":
            result = self._apply_items(plan, current_server_id)
        elif action == "create_collection":
            result = self._apply_collection_create(plan, current_server_id)
        elif action == "update_collection":
            result = self._apply_collection_update(plan, current_server_id)
        else:
            result = self._apply_collection_delete(plan, current_server_id)
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "action": action,
            "applied_at": _now(),
            "authorization_mode": self.authorization_mode,
            **result,
        }

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
            and ManageZotero._copy_tags(data.get("tags"))
            == before.get("tags")
            and ManageZotero._copy_collection_keys(data.get("collections"))
            == before.get("collections")
        )

    def _write_headers(
        self,
        server_id: str,
        api_key: str,
        *,
        version: int | None = None,
    ) -> dict[str, str]:
        headers = {
            **API_HEADERS,
            "Zotero-Server-ID": server_id,
            "Zotero-API-Key": api_key,
        }
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        return headers

    def _write_request(
        self,
        method: str,
        path: str,
        *,
        server_id: str,
        json_body: object | None = None,
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            return self._request(
                method,
                path,
                json_body=json_body,
                headers=headers,
            )
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code == 401
                and self.authorization_mode.startswith("remembered_")
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

    def _apply_items(
        self,
        plan: dict[str, object],
        server_id: str,
    ) -> dict[str, object]:
        changes = plan.get("changes")
        if not isinstance(changes, list) or not changes:
            raise PlanIntegrityError("Item plan contains no changes")
        self._assert_items_unchanged(changes)
        api_key = self.authorize_write(server_id)
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
            "users/0/items",
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
                self._copy_tags(data.get("tags")) == after["tags"]
                and self._copy_collection_keys(data.get("collections"))
                == after["collections"]
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
        server_id: str,
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
        api_key = self.authorize_write(server_id)
        write_response = self._write_request(
            "POST",
            "users/0/collections",
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
        verified = (
            data.get("name") == after.get("name")
            and (data.get("parentCollection") or False)
            == (after.get("parentCollection") or False)
        )
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
        payload = self._get_json(f"users/0/collections/{key}")
        if not isinstance(payload, dict):
            raise ZoteroManagementError(f"Zotero collection {key} is malformed")
        return payload

    def _apply_collection_update(
        self,
        plan: dict[str, object],
        server_id: str,
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
        api_key = self.authorize_write(server_id)
        self._write_request(
            "PUT",
            f"users/0/collections/{key}",
            server_id=server_id,
            json_body=after,
            headers=self._write_headers(server_id, api_key),
        )
        updated = _collection_data(self._get_collection(key))
        verified = (
            updated.get("name") == after.get("name")
            and (updated.get("parentCollection") or False)
            == (after.get("parentCollection") or False)
        )
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
        server_id: str,
    ) -> dict[str, object]:
        target = plan.get("target")
        if not isinstance(target, dict):
            raise PlanIntegrityError("Collection delete plan has no target")
        key = normalize_key(str(target.get("key") or ""), kind="collection")
        self._assert_delete_state_unchanged(plan, key)
        api_key = self.authorize_write(server_id)
        # The authorization dialog can remain open while the user edits Zotero.
        # Recheck the full cascade immediately before using the granted key.
        self._assert_delete_state_unchanged(plan, key)
        self._write_request(
            "DELETE",
            f"users/0/collections/{key}",
            server_id=server_id,
            headers=self._write_headers(
                server_id,
                api_key,
                version=int(target["version"]),
            ),
        )

        deleted_keys = {
            str(entry["key"]) for entry in plan["collection_snapshot"]
        }
        missing_collections = []
        for deleted_key in sorted(deleted_keys):
            response = self._client.get(
                self._url(f"users/0/collections/{deleted_key}")
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
                memberships == affected["remaining_collections"]
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

    def _assert_delete_state_unchanged(
        self,
        plan: dict[str, object],
        key: str,
    ) -> None:
        collections, _ = self._get_collections()
        items = self._get_top_items()
        current_state = self._delete_state(key, collections, items)
        for field in (
            "target",
            "collection_snapshot",
            "affected_items",
            "impact",
        ):
            if current_state[field] != plan.get(field):
                raise PlanDriftError(
                    "The collection tree or membership changed after the plan "
                    "was prepared"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Plan and apply approved Zotero Local API organization changes"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    create_parser = subparsers.add_parser(
        "plan-collection-create",
        help="Create a no-write plan for a new collection",
    )
    create_parser.add_argument("name")
    create_parser.add_argument("--parent")
    create_parser.add_argument("--output", type=Path, required=True)

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

    delete_parser = subparsers.add_parser(
        "plan-collection-delete",
        help="Create a no-write cascade-impact plan for collection deletion",
    )
    delete_parser.add_argument("collection_key")
    delete_parser.add_argument("--output", type=Path, required=True)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply an unchanged plan after explicit approval",
    )
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--approve", required=True)
    apply_parser.add_argument("--confirm-delete")
    apply_parser.add_argument("--receipt", type=Path, required=True)

    subparsers.add_parser(
        "auth-status",
        help="Report whether a remembered authorization is securely stored",
    )
    subparsers.add_parser(
        "auth-forget",
        help="Forget this tool's stored key for the current Zotero database",
    )
    return parser


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "apply":
            output: Path | None = args.receipt
        elif args.command.startswith("plan-"):
            output = args.output
        else:
            output = None
        if output is not None:
            ensure_output_available(output)
        with ManageZotero() as client:
            if args.command == "plan-items":
                result = client.plan_items(
                    args.item_keys,
                    add_tags=args.add_tag,
                    remove_tags=args.remove_tag,
                    add_collections=args.add_collection,
                    remove_collections=args.remove_collection,
                )
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
            elif args.command == "apply":
                plan = _load_json_object(args.plan)
                result = client.apply_plan(
                    plan,
                    approval=args.approve,
                    confirm_delete=args.confirm_delete,
                )
            elif args.command == "auth-status":
                server_id = client.server_id()
                result = client.remembered_authorization_status(server_id)
            else:
                server_id = client.server_id()
                removed = client.forget_remembered_authorization(server_id)
                result = {
                    "server_id": server_id,
                    "local_credential_removed": removed,
                    "zotero_revocation_required": True,
                }
        if output is not None:
            write_json_exclusive(output, result)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print_json(
            {
                "error": (
                    "Cannot connect to Zotero Local API. Start Zotero Desktop "
                    "and enable local application access."
                )
            }
        )
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
