from __future__ import annotations

import json
import warnings
from pathlib import Path

import httpx
import pytest

from tests.conftest import load_script

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "manage-zotero-library" / "scripts" / "zotero_manager.py"
SKILL = ROOT / "skills" / "manage-zotero-library"
QUERY_SKILL = ROOT / "skills" / "query-zotero-library"


class FakeCredentialStore:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    def get(self, server_id: str) -> str | None:
        return self.values.get(server_id)

    def set(self, server_id: str, key: str) -> None:
        self.values[server_id] = key

    def delete(self, server_id: str) -> bool:
        return self.values.pop(server_id, None) is not None


@pytest.fixture
def manager_module():
    return load_script("zotero_manager", SCRIPT)


def root_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True},
        headers={
            "Zotero-API-Version": "3",
            "Zotero-Server-ID": "SERVER-ONE",
        },
    )


def get_only_root_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True},
        headers={
            "Zotero-API-Version": "3",
            "X-Zotero-Version": "9.0.6",
        },
    )


def web_key_response(*, write: bool = True, user_id: int = 12345) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "userID": user_id,
            "username": "Researcher",
            "access": {
                "user": {
                    "library": True,
                    "files": False,
                    "notes": True,
                    "write": write,
                },
                "groups": {},
            },
        },
    )


def item(
    key: str,
    *,
    version: int,
    title: str,
    tags: list[dict[str, object]] | None = None,
    collections: list[str] | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "version": version,
            "itemType": "journalArticle",
            "title": title,
            "tags": tags or [],
            "collections": collections or [],
        },
    }


def collection(
    key: str,
    *,
    version: int,
    name: str,
    parent: str | bool = False,
) -> dict[str, object]:
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "version": version,
            "name": name,
            "parentCollection": parent,
        },
    }


def test_client_rejects_non_loopback_write_target(manager_module):
    with pytest.raises(ValueError, match="loopback"):
        manager_module.ManageZotero(
            base_url="https://api.zotero.org/",
        )


def test_web_client_rejects_nonofficial_api_target(manager_module):
    with pytest.raises(ValueError, match="api.zotero.org"):
        manager_module.ManageZotero(
            backend="web",
            base_url="https://example.com/",
            credential_store=FakeCredentialStore(),
        )


def test_web_plan_uses_stored_key_and_binds_personal_library(manager_module):
    requests: list[httpx.Request] = []
    store = FakeCredentialStore({"research": "WEB-SECRET"})

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Zotero-API-Key"] == "WEB-SECRET"
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.url.path == "/users/12345/items/ITEM2345":
            return httpx.Response(
                200,
                json=item(
                    "ITEM2345",
                    version=12,
                    title="Web API paper",
                    tags=[{"tag": "unread"}],
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(handler),
        credential_store=store,
    ) as client:
        plan = client.plan_items(
            ["ITEM2345"],
            add_tags=["reviewed"],
            remove_tags=["unread"],
        )

    assert plan["api_backend"] == "web"
    assert plan["application_mode"] == "web_api"
    assert plan["library"] == {"type": "user", "id": 12345}
    assert plan["web_profile"] == "research"
    assert "WEB-SECRET" not in json.dumps(plan)
    assert {request.method for request in requests} == {"GET"}


def test_web_plan_rejects_key_without_personal_write_access(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/keys/current"
        return web_key_response(write=False)

    with (
        manager_module.ManageZotero(
            backend="web",
            transport=httpx.MockTransport(handler),
            credential_store=FakeCredentialStore({"default": "READ-ONLY"}),
        ) as client,
        pytest.raises(manager_module.AuthorizationError, match="write access"),
    ):
        client.plan_items(["ITEM2345"], add_tags=["reviewed"])

    assert [request.url.path for request in requests] == ["/keys/current"]


def test_plan_items_merges_tags_and_collection_membership_without_writes(
    manager_module,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    collection(
                        "PARENT23",
                        version=4,
                        name="Projects",
                    ),
                    collection(
                        "CHILD234",
                        version=7,
                        name="ITS",
                        parent="PARENT23",
                    ),
                ],
            )
        if request.url.path == "/api/users/0/items/ITEM2345":
            return httpx.Response(
                200,
                json=item(
                    "ITEM2345",
                    version=12,
                    title="Interrupted Time Series",
                    tags=[
                        {"tag": "unread"},
                        {"tag": "important", "type": 1},
                    ],
                    collections=["PARENT23"],
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_items(
            ["ITEM2345"],
            add_tags=["reviewed"],
            remove_tags=["unread"],
            add_collections=["Projects / ITS"],
            remove_collections=["PARENT23"],
        )

    assert plan["action"] == "update_items"
    assert plan["server_id"] == "SERVER-ONE"
    assert plan["local_api_write_supported"] is True
    assert plan["application_mode"] == "local_api"
    assert len(plan["plan_id"]) == 16
    change = plan["changes"][0]
    assert change["before"] == {
        "tags": [
            {"tag": "unread"},
            {"tag": "important", "type": 1},
        ],
        "collections": ["PARENT23"],
    }
    assert change["after"] == {
        "tags": [
            {"tag": "important", "type": 1},
            {"tag": "reviewed"},
        ],
        "collections": ["CHILD234"],
    }
    assert {request.method for request in requests} == {"GET"}


def test_get_only_zotero_still_creates_manual_collection_plan(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return get_only_root_response()
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    collection(
                        "PARENT23",
                        version=10,
                        name="Old Project",
                    )
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_update(
            "PARENT23",
            name="Renamed Project",
        )

    assert plan["server_id"] is None
    assert plan["local_api_write_supported"] is False
    assert plan["application_mode"] == "manual_zotero_desktop"
    assert plan["after"]["name"] == "Renamed Project"
    assert {request.method for request in requests} == {"GET"}


def test_manual_plan_cannot_apply_or_request_authorization(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        pytest.fail(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_collection",
        "server_id": None,
        "local_api_write_supported": False,
        "application_mode": "manual_zotero_desktop",
        "before": {
            "key": "PARENT23",
            "version": 10,
            "name": "Old Project",
            "parentCollection": False,
            "path": "Old Project",
        },
        "after": {
            "key": "PARENT23",
            "version": 10,
            "name": "Renamed Project",
            "parentCollection": False,
        },
    }
    plan = manager_module.sign_plan(unsigned)

    with (
        manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(manager_module.ZoteroManagementError, match="GET-only"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert requests == []


def test_manual_application_mode_blocks_apply_even_with_server_id(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        pytest.fail(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_collection",
        "server_id": "SERVER-ONE",
        "application_mode": "manual_zotero_desktop",
        "before": {
            "key": "PARENT23",
            "version": 10,
            "name": "Old Project",
            "parentCollection": False,
            "path": "Old Project",
        },
        "after": {
            "key": "PARENT23",
            "version": 10,
            "name": "Renamed Project",
            "parentCollection": False,
        },
    }
    plan = manager_module.sign_plan(unsigned)

    with (
        manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(manager_module.ZoteroManagementError, match="GET-only"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert requests == []


def test_plan_items_rejects_child_items_and_noop_changes(manager_module):
    def child_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            payload = item(
                "ITEM2345",
                version=2,
                title="PDF",
            )
            payload["data"]["itemType"] = "attachment"
            payload["data"]["parentItem"] = "PARENT23"
            return httpx.Response(200, json=payload)
        raise AssertionError(f"Unexpected request: {request.url}")

    with (
        manager_module.ManageZotero(
            transport=httpx.MockTransport(child_handler)
        ) as client,
        pytest.raises(ValueError, match="top-level"),
    ):
        client.plan_items(["ITEM2345"], add_tags=["reviewed"])

    def noop_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            return httpx.Response(
                200,
                json=item(
                    "ITEM2345",
                    version=2,
                    title="Paper",
                    tags=[{"tag": "reviewed"}],
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with (
        manager_module.ManageZotero(
            transport=httpx.MockTransport(noop_handler)
        ) as client,
        pytest.raises(ValueError, match="No item changes"),
    ):
        client.plan_items(["ITEM2345"], add_tags=["reviewed"])


def test_delete_plan_discloses_descendants_members_and_unfiled_items(
    manager_module,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    collection(
                        "PARENT23",
                        version=10,
                        name="Old Project",
                    ),
                    collection(
                        "CHILD234",
                        version=11,
                        name="Archive",
                        parent="PARENT23",
                    ),
                    collection(
                        "OTHER234",
                        version=12,
                        name="Methods",
                    ),
                ],
            )
        if request.url.path == "/api/users/0/items/top":
            return httpx.Response(
                200,
                json=[
                    item(
                        "ITEM2345",
                        version=20,
                        title="Only in old project",
                        collections=["PARENT23"],
                    ),
                    item(
                        "ITEM2346",
                        version=21,
                        title="Also filed elsewhere",
                        collections=["CHILD234", "OTHER234"],
                    ),
                ],
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_delete("PARENT23")

    assert plan["action"] == "delete_collection"
    assert plan["target"] == {
        "key": "PARENT23",
        "path": "Old Project",
        "version": 10,
    }
    assert [entry["path"] for entry in plan["collection_snapshot"]] == [
        "Old Project",
        "Old Project / Archive",
    ]
    assert plan["impact"]["deleted_collection_count"] == 2
    assert plan["impact"]["affected_item_count"] == 2
    assert plan["impact"]["becomes_unfiled_count"] == 1
    affected = {entry["key"]: entry for entry in plan["affected_items"]}
    assert affected["ITEM2345"]["becomes_unfiled"] is True
    assert affected["ITEM2346"]["remaining_collections"] == ["OTHER234"]
    assert plan["requires_delete_confirmation"] == "PARENT23"


def test_delete_plan_paginates_before_reporting_affected_items(manager_module):
    item_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    collection(
                        "PARENT23",
                        version=10,
                        name="Old Project",
                    )
                ],
                headers={"Total-Results": "1", "Last-Modified-Version": "10"},
            )
        if request.url.path == "/api/users/0/items/top":
            item_requests.append(request)
            start = int(request.url.params["start"])
            if start == 0:
                return httpx.Response(
                    200,
                    json=[
                        item(
                            f"ITEM{number:04d}",
                            version=number,
                            title=f"Unrelated {number}",
                        )
                        for number in range(100)
                    ],
                    headers={"Total-Results": "101"},
                )
            if start == 100:
                return httpx.Response(
                    200,
                    json=[
                        item(
                            "LAST2345",
                            version=101,
                            title="Affected item on the second page",
                            collections=["PARENT23"],
                        )
                    ],
                    headers={"Total-Results": "101"},
                )
        raise AssertionError(f"Unexpected request: {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_delete("PARENT23")

    assert len(item_requests) == 2
    assert [entry["key"] for entry in plan["affected_items"]] == ["LAST2345"]
    assert plan["impact"]["affected_item_count"] == 1


def test_apply_rejects_wrong_approval_before_authorization(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        pytest.fail(f"Unexpected request: {request.url}")

    plan = {
        "schema_version": 1,
        "plan_id": "RIGHTPLAN1234567",
        "action": "update_items",
        "server_id": "SERVER-ONE",
        "changes": [],
    }
    with (
        manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="approval"),
    ):
        client.apply_plan(plan, approval="WRONG")

    assert requests == []


def test_apply_rejects_delete_without_exact_collection_confirmation(
    manager_module,
):
    plan = {
        "schema_version": 1,
        "plan_id": "RIGHTPLAN1234567",
        "action": "delete_collection",
        "server_id": "SERVER-ONE",
        "target": {"key": "PARENT23"},
        "requires_delete_confirmation": "PARENT23",
    }
    with (
        manager_module.ManageZotero(
            transport=httpx.MockTransport(
                lambda request: pytest.fail(f"Unexpected request: {request.url}")
            )
        ) as client,
        pytest.raises(ValueError, match="delete confirmation"),
    ):
        client.apply_plan(
            plan,
            approval="RIGHTPLAN1234567",
            confirm_delete="OTHER234",
        )


def test_apply_item_plan_uses_one_time_auth_versions_and_verifies(
    manager_module,
):
    requests: list[httpx.Request] = []
    before = item(
        "ITEM2345",
        version=12,
        title="Paper",
        tags=[{"tag": "unread"}],
        collections=["PARENT23"],
    )
    after = item(
        "ITEM2345",
        version=13,
        title="Paper",
        tags=[{"tag": "reviewed"}],
        collections=["CHILD234"],
    )
    item_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal item_reads
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            item_reads += 1
            return httpx.Response(
                200,
                json=before if item_reads <= 2 else after,
            )
        if request.url.path == "/api/local/authorize":
            assert request.method == "POST"
            assert request.headers["Zotero-Server-ID"] == "SERVER-ONE"
            assert json.loads(request.content) == {
                "appName": "Social Science Research Skills"
            }
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.url.path == "/api/users/0/items":
            assert request.method == "POST"
            assert request.headers["Zotero-API-Key"] == "LOCAL-SECRET"
            assert request.headers["Zotero-Server-ID"] == "SERVER-ONE"
            assert json.loads(request.content) == [
                {
                    "key": "ITEM2345",
                    "version": 12,
                    "tags": [{"tag": "reviewed"}],
                    "collections": ["CHILD234"],
                }
            ]
            return httpx.Response(
                200,
                json={
                    "successful": {"0": after},
                    "unchanged": {},
                    "failed": {},
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        unsigned = {
            "schema_version": 1,
            "action": "update_items",
            "server_id": "SERVER-ONE",
            "changes": [
                {
                    "key": "ITEM2345",
                    "title": "Paper",
                    "version": 12,
                    "before": {
                        "tags": [{"tag": "unread"}],
                        "collections": ["PARENT23"],
                    },
                    "after": {
                        "tags": [{"tag": "reviewed"}],
                        "collections": ["CHILD234"],
                    },
                }
            ],
        }
        plan = manager_module.sign_plan(unsigned)
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    assert receipt["verified"] is True
    assert receipt["action"] == "update_items"
    assert receipt["plan_id"] == plan["plan_id"]
    assert receipt["authorization_mode"] == "one_time"
    assert "LOCAL-SECRET" not in json.dumps(receipt)
    assert [request.method for request in requests] == [
        "GET",
        "GET",
        "POST",
        "GET",
        "POST",
        "GET",
    ]


def test_apply_web_item_plan_uses_bound_account_and_no_local_auth(
    manager_module,
):
    requests: list[httpx.Request] = []
    before = item(
        "ITEM2345",
        version=12,
        title="Paper",
        tags=[{"tag": "unread"}],
    )
    after = item(
        "ITEM2345",
        version=13,
        title="Paper",
        tags=[{"tag": "reviewed"}],
    )
    item_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal item_reads
        requests.append(request)
        assert request.headers["Zotero-API-Key"] == "WEB-SECRET"
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.url.path == "/users/12345/items/ITEM2345":
            item_reads += 1
            return httpx.Response(200, json=before if item_reads == 1 else after)
        if request.url.path == "/users/12345/items":
            assert request.method == "POST"
            assert "Zotero-Server-ID" not in request.headers
            assert json.loads(request.content) == [
                {
                    "key": "ITEM2345",
                    "version": 12,
                    "tags": [{"tag": "reviewed"}],
                    "collections": [],
                }
            ]
            return httpx.Response(
                200,
                json={
                    "successful": {"0": after},
                    "unchanged": {},
                    "failed": {},
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "api_backend": "web",
        "application_mode": "web_api",
        "library": {"type": "user", "id": 12345},
        "web_profile": "research",
        "changes": [
            {
                "key": "ITEM2345",
                "title": "Paper",
                "version": 12,
                "before": {
                    "tags": [{"tag": "unread"}],
                    "collections": [],
                },
                "after": {
                    "tags": [{"tag": "reviewed"}],
                    "collections": [],
                },
            }
        ],
    }
    plan = manager_module.sign_plan(unsigned)
    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(handler),
        credential_store=FakeCredentialStore({"research": "WEB-SECRET"}),
    ) as client:
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    assert receipt["verified"] is True
    assert receipt["authorization_mode"] == "web_api_key"
    assert receipt["api_backend"] == "web"
    assert receipt["library"] == {"type": "user", "id": 12345}
    assert "WEB-SECRET" not in json.dumps(receipt)
    assert not any(
        request.url.path.endswith("/local/authorize") for request in requests
    )


def test_apply_web_collection_create_uses_library_version(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Zotero-API-Key"] == "WEB-SECRET"
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.method == "GET" and request.url.path == "/users/12345/collections":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "20", "Total-Results": "0"},
            )
        if request.method == "POST" and request.url.path == "/users/12345/collections":
            assert request.headers["If-Unmodified-Since-Version"] == "20"
            assert "Zotero-Server-ID" not in request.headers
            assert json.loads(request.content) == [
                {"name": "New Project", "parentCollection": False}
            ]
            return httpx.Response(
                200,
                json={"successful": {"0": {"key": "NEWC2LL2"}}},
            )
        if request.url.path == "/users/12345/collections/NEWC2LL2":
            return httpx.Response(
                200,
                json=collection("NEWC2LL2", version=21, name="New Project"),
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(handler),
        credential_store=FakeCredentialStore({"research": "WEB-SECRET"}),
    ) as client:
        plan = client.plan_collection_create("New Project")
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    assert receipt["verified"] is True
    assert receipt["created_collection_key"] == "NEWC2LL2"
    assert receipt["library"] == {"type": "user", "id": 12345}


def test_apply_web_collection_delete_uses_atomic_library_version_guard(
    manager_module,
):
    requests: list[httpx.Request] = []
    list_reads = {"collections": 0, "items": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Zotero-API-Key"] == "WEB-SECRET"
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.method == "GET" and request.url.path in {
            "/users/12345/collections",
            "/users/12345/items/top",
        }:
            kind = (
                "collections" if request.url.path.endswith("collections") else "items"
            )
            list_reads[kind] += 1
            payload = (
                [collection("PARENT23", version=10, name="Old Project")]
                if kind == "collections"
                else []
            )
            return httpx.Response(
                200,
                json=payload,
                headers={
                    "Last-Modified-Version": "20",
                    "Total-Results": str(len(payload)),
                },
            )
        if request.method == "DELETE":
            assert request.url.path == "/users/12345/collections"
            assert request.url.params["collectionKey"] == "PARENT23"
            assert request.headers["If-Unmodified-Since-Version"] == "20"
            # Simulate a child collection or membership added after the final
            # read. The library-wide guard must make Zotero reject the delete.
            return httpx.Response(412)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(handler),
        credential_store=FakeCredentialStore({"research": "WEB-SECRET"}),
    ) as client:
        plan = client.plan_collection_delete("PARENT23")
        assert plan["expected_library_version"] == 20
        with pytest.raises(manager_module.PlanDriftError, match="library changed"):
            client.apply_plan(
                plan,
                approval=plan["plan_id"],
                confirm_delete="PARENT23",
            )

    assert list_reads == {"collections": 2, "items": 2}
    assert sum(request.method == "DELETE" for request in requests) == 1


def test_web_delete_plan_rejects_inconsistent_impact_snapshot(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.url.path == "/users/12345/collections":
            return httpx.Response(
                200,
                json=[collection("PARENT23", version=10, name="Old Project")],
                headers={"Last-Modified-Version": "20", "Total-Results": "1"},
            )
        if request.url.path == "/users/12345/items/top":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "21", "Total-Results": "0"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with (
        manager_module.ManageZotero(
            backend="web",
            web_profile="research",
            transport=httpx.MockTransport(handler),
            credential_store=FakeCredentialStore({"research": "WEB-SECRET"}),
        ) as client,
        pytest.raises(manager_module.PlanDriftError, match="snapshot"),
    ):
        client.plan_collection_delete("PARENT23")

    assert not any(request.method == "DELETE" for request in requests)


def test_apply_web_plan_rejects_different_credential_profile(manager_module):
    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "api_backend": "web",
        "application_mode": "web_api",
        "library": {"type": "user", "id": 12345},
        "web_profile": "research",
        "changes": [],
    }
    plan = manager_module.sign_plan(unsigned)
    with (
        manager_module.ManageZotero(
            backend="web",
            web_profile="other",
            transport=httpx.MockTransport(
                lambda request: pytest.fail(f"Unexpected request: {request.url}")
            ),
            credential_store=FakeCredentialStore({"other": "OTHER-SECRET"}),
        ) as client,
        pytest.raises(manager_module.PlanDriftError, match="credential profile"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])


def test_apply_web_plan_rejects_different_personal_library(manager_module):
    requests: list[httpx.Request] = []
    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "api_backend": "web",
        "application_mode": "web_api",
        "library": {"type": "user", "id": 12345},
        "web_profile": "research",
        "changes": [],
    }
    plan = manager_module.sign_plan(unsigned)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/keys/current"
        return web_key_response(user_id=98765)

    with (
        manager_module.ManageZotero(
            backend="web",
            web_profile="research",
            transport=httpx.MockTransport(handler),
            credential_store=FakeCredentialStore({"research": "WEB-SECRET"}),
        ) as client,
        pytest.raises(manager_module.PlanDriftError, match="personal library"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert [request.url.path for request in requests] == ["/keys/current"]


def test_apply_collection_create_uses_library_version_and_verifies(
    manager_module,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json=[],
                    headers={
                        "Total-Results": "0",
                        "Last-Modified-Version": "12",
                    },
                )
            assert request.method == "POST"
            assert request.headers["If-Unmodified-Since-Version"] == "12"
            assert json.loads(request.content) == [
                {"name": "New Project", "parentCollection": False}
            ]
            return httpx.Response(
                200,
                json={
                    "successful": {
                        "0": collection(
                            "NEWC2LL2",
                            version=13,
                            name="New Project",
                        )
                    }
                },
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.url.path == "/api/users/0/collections/NEWC2LL2":
            return httpx.Response(
                200,
                json=collection(
                    "NEWC2LL2",
                    version=13,
                    name="New Project",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_create("New Project")
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    assert receipt["verified"] is True
    assert receipt["created_collection_key"] == "NEWC2LL2"
    assert "LOCAL-SECRET" not in json.dumps(receipt)


def test_apply_collection_update_preserves_version_and_verifies(
    manager_module,
):
    requests: list[httpx.Request] = []
    updated = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal updated
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections/PARENT23":
            if request.method == "PUT":
                updated = True
                assert json.loads(request.content) == {
                    "key": "PARENT23",
                    "version": 10,
                    "name": "Renamed Project",
                    "parentCollection": False,
                }
                return httpx.Response(204)
            return httpx.Response(
                200,
                json=collection(
                    "PARENT23",
                    version=11 if updated else 10,
                    name="Renamed Project" if updated else "Old Project",
                ),
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_collection",
        "server_id": "SERVER-ONE",
        "before": {
            "key": "PARENT23",
            "version": 10,
            "name": "Old Project",
            "parentCollection": False,
            "path": "Old Project",
        },
        "after": {
            "key": "PARENT23",
            "version": 10,
            "name": "Renamed Project",
            "parentCollection": False,
        },
    }
    plan = manager_module.sign_plan(unsigned)
    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    assert receipt["verified"] is True
    assert receipt["inverse"] == {
        "key": "PARENT23",
        "name": "Old Project",
        "parentCollection": False,
    }
    assert "LOCAL-SECRET" not in json.dumps(receipt)


def test_apply_delete_plan_preserves_items_and_verifies_cascade(manager_module):
    requests: list[httpx.Request] = []
    deleted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    collection("PARENT23", version=10, name="Old Project"),
                    collection(
                        "CHILD234",
                        version=11,
                        name="Archive",
                        parent="PARENT23",
                    ),
                ],
            )
        if request.url.path == "/api/users/0/items/top":
            return httpx.Response(
                200,
                json=[
                    item(
                        "ITEM2345",
                        version=20,
                        title="Preserved paper",
                        collections=["CHILD234"],
                    )
                ],
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.url.path == "/api/users/0/collections/PARENT23":
            if request.method == "DELETE":
                deleted = True
                assert request.headers["If-Unmodified-Since-Version"] == "10"
                return httpx.Response(204)
            return httpx.Response(404 if deleted else 200)
        if request.url.path == "/api/users/0/collections/CHILD234":
            return httpx.Response(404 if deleted else 200)
        if request.url.path == "/api/users/0/items/ITEM2345":
            return httpx.Response(
                200,
                json=item(
                    "ITEM2345",
                    version=21,
                    title="Preserved paper",
                    collections=[],
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_delete("PARENT23")
        receipt = client.apply_plan(
            plan,
            approval=plan["plan_id"],
            confirm_delete="PARENT23",
        )

    assert receipt["verified"] is True
    assert receipt["items_deleted"] == 0
    assert receipt["collections_still_present"] == []
    assert receipt["item_verification"] == [
        {
            "key": "ITEM2345",
            "exists": True,
            "memberships_match": True,
        }
    ]
    assert "LOCAL-SECRET" not in json.dumps(receipt)
    assert any(request.method == "DELETE" for request in requests)


def test_delete_rechecks_cascade_after_authorization(manager_module):
    requests: list[httpx.Request] = []
    collection_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal collection_reads
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/collections":
            collection_reads += 1
            records = [collection("PARENT23", version=10, name="Old Project")]
            if collection_reads == 3:
                records.append(
                    collection(
                        "NEWCHLD2",
                        version=11,
                        name="Added during authorization",
                        parent="PARENT23",
                    )
                )
            return httpx.Response(200, json=records)
        if request.url.path == "/api/users/0/items/top":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client:
        plan = client.plan_collection_delete("PARENT23")
        with pytest.raises(manager_module.PlanDriftError, match="tree"):
            client.apply_plan(
                plan,
                approval=plan["plan_id"],
                confirm_delete="PARENT23",
            )

    assert any(request.url.path == "/api/local/authorize" for request in requests)
    assert not any(request.method == "DELETE" for request in requests)


def test_apply_aborts_on_version_drift_before_authorization(manager_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            return httpx.Response(
                200,
                json=item(
                    "ITEM2345",
                    version=99,
                    title="Changed Paper",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "server_id": "SERVER-ONE",
        "changes": [
            {
                "key": "ITEM2345",
                "title": "Paper",
                "version": 12,
                "before": {"tags": [], "collections": []},
                "after": {"tags": [{"tag": "reviewed"}], "collections": []},
            }
        ],
    }
    plan = manager_module.sign_plan(unsigned)
    with (
        manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(manager_module.PlanDriftError, match="changed"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert "/api/local/authorize" not in [request.url.path for request in requests]
    assert {request.method for request in requests} == {"GET"}


def test_item_apply_rechecks_state_after_authorization(manager_module):
    requests: list[httpx.Request] = []
    item_reads = 0
    before = item(
        "ITEM2345",
        version=12,
        title="Paper",
        tags=[{"tag": "unread"}],
    )
    changed = item(
        "ITEM2345",
        version=13,
        title="Paper",
        tags=[{"tag": "manually changed"}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal item_reads
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            item_reads += 1
            return httpx.Response(
                200,
                json=before if item_reads == 1 else changed,
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "server_id": "SERVER-ONE",
        "changes": [
            {
                "key": "ITEM2345",
                "title": "Paper",
                "version": 12,
                "before": {
                    "tags": [{"tag": "unread"}],
                    "collections": [],
                },
                "after": {
                    "tags": [{"tag": "reviewed"}],
                    "collections": [],
                },
            }
        ],
    }
    plan = manager_module.sign_plan(unsigned)
    with (
        manager_module.ManageZotero(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(manager_module.PlanDriftError, match="changed"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert any(request.url.path == "/api/local/authorize" for request in requests)
    assert not any(
        request.method == "POST" and request.url.path == "/api/users/0/items"
        for request in requests
    )


def test_authorization_stores_user_approved_remembered_key(manager_module):
    store = FakeCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/local/authorize"
        return httpx.Response(
            200,
            json={"key": "REMEMBERED-SECRET", "remember": True},
        )

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler),
        credential_store=store,
    ) as client:
        key = client.authorize_write("SERVER-ONE")

    assert key == "REMEMBERED-SECRET"
    assert store.values == {"SERVER-ONE": "REMEMBERED-SECRET"}
    assert client.authorization_mode == "remembered_new"


def test_web_authorization_validates_then_stores_without_exposing_key(
    manager_module,
):
    store = FakeCredentialStore()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/keys/current"
        assert request.headers["Zotero-API-Key"] == "WEB-SECRET"
        return web_key_response()

    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(handler),
        credential_store=store,
    ) as client:
        result = client.store_web_authorization("WEB-SECRET")

    assert store.values == {"research": "WEB-SECRET"}
    assert result == {
        "web_profile": "research",
        "user_id": 12345,
        "username": "Researcher",
        "personal_library_write_access": True,
        "stored": True,
    }
    assert "WEB-SECRET" not in json.dumps(result)
    assert len(requests) == 1


def test_cli_web_auth_store_fails_closed_without_echo_free_input(
    manager_module,
    monkeypatch,
    capsys,
):
    fallback_read = False

    def unsafe_getpass(prompt: str) -> str:
        nonlocal fallback_read
        warnings.warn(
            "Can not control echo on the terminal.",
            getpass_warning,
            stacklevel=2,
        )
        fallback_read = True
        return "MUST-NOT-BE-READ"

    getpass_warning = manager_module.getpass.GetPassWarning
    monkeypatch.setattr(manager_module.getpass, "getpass", unsafe_getpass)
    monkeypatch.setattr(
        manager_module,
        "ManageZotero",
        lambda **kwargs: pytest.fail(
            "The CLI initialized Zotero before obtaining echo-free secret input"
        ),
    )

    result = manager_module.main(["web-auth-store", "--web-profile", "research"])

    output = capsys.readouterr().out
    assert result == 1
    assert fallback_read is False
    assert "echo-free" in output
    assert "MUST-NOT-BE-READ" not in output


def test_rejected_web_write_preserves_profile_credential(manager_module):
    requests: list[httpx.Request] = []
    store = FakeCredentialStore({"research": "WEB-SECRET"})
    current = item(
        "ITEM2345",
        version=12,
        title="Paper",
        tags=[{"tag": "unread"}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/keys/current":
            return web_key_response()
        if request.url.path == "/users/12345/items/ITEM2345":
            return httpx.Response(200, json=current)
        if request.url.path == "/users/12345/items":
            assert request.method == "POST"
            return httpx.Response(403)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    plan = manager_module.sign_plan(
        {
            "schema_version": 1,
            "action": "update_items",
            "api_backend": "web",
            "application_mode": "web_api",
            "library": {"type": "user", "id": 12345},
            "web_profile": "research",
            "changes": [
                {
                    "key": "ITEM2345",
                    "title": "Paper",
                    "version": 12,
                    "before": {
                        "tags": [{"tag": "unread"}],
                        "collections": [],
                    },
                    "after": {
                        "tags": [{"tag": "reviewed"}],
                        "collections": [],
                    },
                }
            ],
        }
    )
    with (
        manager_module.ManageZotero(
            backend="web",
            web_profile="research",
            transport=httpx.MockTransport(handler),
            credential_store=store,
        ) as client,
        pytest.raises(manager_module.AuthorizationError, match="preserved"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert store.values == {"research": "WEB-SECRET"}
    assert (
        sum(
            request.url.path == "/users/12345/items" and request.method == "POST"
            for request in requests
        )
        == 1
    )


def test_web_authorization_status_and_forget_are_profile_scoped(manager_module):
    store = FakeCredentialStore({"research": "WEB-SECRET", "other": "OTHER-SECRET"})
    with manager_module.ManageZotero(
        backend="web",
        web_profile="research",
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"Unexpected request: {request.url}")
        ),
        credential_store=store,
    ) as client:
        status = client.web_authorization_status()
        removed = client.forget_web_authorization()

    assert status == {
        "web_profile": "research",
        "secure_store_available": True,
        "stored_authorization": True,
    }
    assert removed is True
    assert store.values == {"other": "OTHER-SECRET"}


def test_authorization_reuses_stored_key_without_prompt(manager_module):
    requests: list[httpx.Request] = []
    store = FakeCredentialStore({"SERVER-ONE": "STORED-SECRET"})

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        pytest.fail(f"Unexpected request: {request.url}")

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler),
        credential_store=store,
    ) as client:
        key = client.authorize_write("SERVER-ONE")

    assert key == "STORED-SECRET"
    assert client.authorization_mode == "remembered_reused"
    assert requests == []


def test_authorization_rejects_always_allow_without_secure_store(
    manager_module,
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/local/authorize"
        return httpx.Response(
            200,
            json={"key": "REMEMBERED-SECRET", "remember": True},
        )

    with (
        manager_module.ManageZotero(
            transport=httpx.MockTransport(handler),
            credential_store=None,
        ) as client,
        pytest.raises(
            manager_module.AuthorizationError,
            match="credential store",
        ),
    ):
        client.authorize_write("SERVER-ONE")


def test_rejected_stored_key_is_forgotten_without_automatic_retry(
    manager_module,
):
    requests: list[httpx.Request] = []
    store = FakeCredentialStore({"SERVER-ONE": "STALE-SECRET"})
    current = item(
        "ITEM2345",
        version=12,
        title="Paper",
        tags=[{"tag": "unread"}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ITEM2345":
            return httpx.Response(200, json=current)
        if request.url.path == "/api/users/0/items":
            assert request.headers["Zotero-API-Key"] == "STALE-SECRET"
            return httpx.Response(401)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    unsigned = {
        "schema_version": 1,
        "action": "update_items",
        "server_id": "SERVER-ONE",
        "changes": [
            {
                "key": "ITEM2345",
                "title": "Paper",
                "version": 12,
                "before": {
                    "tags": [{"tag": "unread"}],
                    "collections": [],
                },
                "after": {
                    "tags": [{"tag": "reviewed"}],
                    "collections": [],
                },
            }
        ],
    }
    plan = manager_module.sign_plan(unsigned)
    with (
        manager_module.ManageZotero(
            transport=httpx.MockTransport(handler),
            credential_store=store,
        ) as client,
        pytest.raises(
            manager_module.AuthorizationError,
            match="removed",
        ),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert store.values == {}
    assert not any(request.url.path == "/api/local/authorize" for request in requests)
    assert (
        sum(
            request.url.path == "/api/users/0/items" and request.method == "POST"
            for request in requests
        )
        == 1
    )


def test_forget_remembered_authorization_removes_only_current_server_key(
    manager_module,
):
    store = FakeCredentialStore(
        {
            "SERVER-ONE": "FIRST-SECRET",
            "SERVER-TWO": "SECOND-SECRET",
        }
    )
    with manager_module.ManageZotero(
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"Unexpected request: {request.url}")
        ),
        credential_store=store,
    ) as client:
        removed = client.forget_remembered_authorization("SERVER-ONE")

    assert removed is True
    assert store.values == {"SERVER-TWO": "SECOND-SECRET"}


def test_system_store_accepts_recognized_os_keyring_backend(
    manager_module,
    monkeypatch,
):
    class SecureBackend:
        def __init__(self):
            self.values: dict[tuple[str, str], str] = {}
            self.priority = 5

        def get_password(self, service: str, username: str) -> str | None:
            return self.values.get((service, username))

        def set_password(
            self,
            service: str,
            username: str,
            password: str,
        ) -> None:
            self.values[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            del self.values[(service, username)]

    SecureBackend.__module__ = "keyring.backends.macOS"
    backend = SecureBackend()

    class FakeKeyring:
        @staticmethod
        def get_keyring():
            return backend

    monkeypatch.setattr(manager_module, "keyring", FakeKeyring)
    store = manager_module.SystemCredentialStore()

    store.set("SERVER-ONE", "REMEMBERED-SECRET")

    assert store.get("SERVER-ONE") == "REMEMBERED-SECRET"
    assert store.delete("SERVER-ONE") is True
    assert store.get("SERVER-ONE") is None


def test_system_store_rejects_plaintext_or_unknown_backend(
    manager_module,
    monkeypatch,
):
    class PlaintextBackend:
        priority = 5

    PlaintextBackend.__module__ = "keyrings.alt.file"

    class FakeKeyring:
        @staticmethod
        def get_keyring():
            return PlaintextBackend()

    monkeypatch.setattr(manager_module, "keyring", FakeKeyring)
    store = manager_module.SystemCredentialStore()

    with pytest.raises(
        manager_module.CredentialStoreUnavailable,
        match="not a recognized secure",
    ):
        store.set("SERVER-ONE", "MUST-NOT-BE-STORED")


def test_write_json_exclusive_does_not_overwrite_existing_file(
    manager_module,
    tmp_path,
):
    output = tmp_path / "plan.json"
    manager_module.write_json_exclusive(output, {"first": True})

    with pytest.raises(FileExistsError):
        manager_module.write_json_exclusive(output, {"second": True})

    assert json.loads(output.read_text()) == {"first": True}


def test_cli_refuses_existing_receipt_before_connecting(
    manager_module,
    monkeypatch,
    tmp_path,
    capsys,
):
    plan = tmp_path / "plan.json"
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"existing": true}\n', encoding="utf-8")

    monkeypatch.setattr(
        manager_module,
        "ManageZotero",
        lambda: pytest.fail("The CLI connected before checking its output path"),
    )
    result = manager_module.main(
        [
            "apply",
            str(plan),
            "--approve",
            "PLAN1234",
            "--receipt",
            str(receipt),
        ]
    )

    assert result == 1
    assert "Refusing to overwrite existing output" in capsys.readouterr().out
    assert json.loads(receipt.read_text()) == {"existing": True}


def test_cli_exposes_plan_and_apply_commands(manager_module):
    parser = manager_module.build_parser()

    item_args = parser.parse_args(
        [
            "plan-items",
            "ITEM2345",
            "--add-tag",
            "reviewed",
            "--output",
            "plan.json",
        ]
    )
    delete_args = parser.parse_args(
        [
            "plan-collection-delete",
            "PARENT23",
            "--output",
            "delete.json",
        ]
    )
    apply_args = parser.parse_args(
        [
            "apply",
            "plan.json",
            "--approve",
            "PLAN1234",
            "--receipt",
            "receipt.json",
        ]
    )
    status_args = parser.parse_args(["auth-status"])
    forget_args = parser.parse_args(["auth-forget"])
    web_item_args = parser.parse_args(
        [
            "plan-items",
            "ITEM2345",
            "--backend",
            "web",
            "--web-profile",
            "research",
            "--add-tag",
            "reviewed",
            "--output",
            "web-plan.json",
        ]
    )
    web_store_args = parser.parse_args(["web-auth-store", "--web-profile", "research"])
    web_status_args = parser.parse_args(
        ["web-auth-status", "--web-profile", "research"]
    )
    web_forget_args = parser.parse_args(
        ["web-auth-forget", "--web-profile", "research"]
    )

    assert item_args.command == "plan-items"
    assert delete_args.command == "plan-collection-delete"
    assert apply_args.command == "apply"
    assert status_args.command == "auth-status"
    assert forget_args.command == "auth-forget"
    assert web_item_args.backend == "web"
    assert web_item_args.web_profile == "research"
    assert web_store_args.command == "web-auth-store"
    assert web_status_args.command == "web-auth-status"
    assert web_forget_args.command == "web-auth-forget"


def test_skill_declares_read_dependency_and_write_safety_contract():
    query = (QUERY_SKILL / "SKILL.md").read_text(encoding="utf-8")
    manage = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "capabilities: [zotero-read]" in query
    assert "requires: [zotero-read]" in manage
    assert "Never choose `Always Allow` on the user's behalf" in manage
    assert "system credential store" in manage
    assert "Clear Write Authorizations" in manage
    assert "local_api_write_supported" in manage
    assert "manual_zotero_desktop" in manage
    assert "Zotero-Server-ID" in manage
    assert "GET-only" in manage
    assert "manual change" in manage
    assert "Do not claim" in manage
    assert "Never delete Zotero items or attachments" in manage
    assert "delete confirmation" in manage
    assert "plan ID" in manage
    assert "receipt" in manage
    assert "Bulk PDF import guidance" in manage
    assert "50–100 PDFs" in manage
    assert "Command+Option" in manage
    assert "Ctrl+Shift" in manage
    assert "standalone PDF attachments" in manage
    assert "does not upload local PDFs" in manage
    assert "explicit alternative" in manage
    assert "web-auth-store" in manage
    assert "`/keys/current`" in manage
    assert "personal-library write" in manage
    assert "--backend web --web-profile research" in manage
    assert "environment variable" in manage
    assert "terminal echo cannot be disabled" in manage
    assert "library-versioned multi-object collection" in manage

    safety = (SKILL / "references" / "write-safety.md").read_text(encoding="utf-8")
    assert "https://api.zotero.org/" in safety
    assert "Zotero-Write-Token" in safety
    assert "versioned writes" in safety
    assert "Group permissions do not substitute" in safety
    assert "preserve the selected stored profile" in safety

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"keyring>=' in pyproject
