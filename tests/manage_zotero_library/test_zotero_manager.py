from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.conftest import load_script

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "skills"
    / "manage-zotero-library"
    / "scripts"
    / "zotero_manager.py"
)
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        plan = client.plan_items(
            ["ITEM2345"],
            add_tags=["reviewed"],
            remove_tags=["unread"],
            add_collections=["Projects / ITS"],
            remove_collections=["PARENT23"],
        )

    assert plan["action"] == "update_items"
    assert plan["server_id"] == "SERVER-ONE"
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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
        manager_module.ManageZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
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
                lambda request: pytest.fail(
                    f"Unexpected request: {request.url}"
                )
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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
    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
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
            records = [
                collection("PARENT23", version=10, name="Old Project")
            ]
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

    with manager_module.ManageZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        plan = client.plan_collection_delete("PARENT23")
        with pytest.raises(manager_module.PlanDriftError, match="tree"):
            client.apply_plan(
                plan,
                approval=plan["plan_id"],
                confirm_delete="PARENT23",
            )

    assert any(
        request.url.path == "/api/local/authorize" for request in requests
    )
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
        manager_module.ManageZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(manager_module.PlanDriftError, match="changed"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert "/api/local/authorize" not in [
        request.url.path for request in requests
    ]
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
        manager_module.ManageZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(manager_module.PlanDriftError, match="changed"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert any(
        request.url.path == "/api/local/authorize" for request in requests
    )
    assert not any(
        request.method == "POST"
        and request.url.path == "/api/users/0/items"
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
    assert not any(
        request.url.path == "/api/local/authorize" for request in requests
    )
    assert sum(
        request.url.path == "/api/users/0/items"
        and request.method == "POST"
        for request in requests
    ) == 1


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

    assert item_args.command == "plan-items"
    assert delete_args.command == "plan-collection-delete"
    assert apply_args.command == "apply"
    assert status_args.command == "auth-status"
    assert forget_args.command == "auth-forget"


def test_skill_declares_read_dependency_and_write_safety_contract():
    query = (QUERY_SKILL / "SKILL.md").read_text(encoding="utf-8")
    manage = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "capabilities: [zotero-read]" in query
    assert "requires: [zotero-read]" in manage
    assert "Never choose `Always Allow` on the user's behalf" in manage
    assert "system credential store" in manage
    assert "Clear Write Authorizations" in manage
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

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"keyring>=' in pyproject
