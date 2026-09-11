from __future__ import annotations

import json
from pathlib import Path

import httpx
import pymupdf
import pytest

from tests.conftest import load_script

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "skills"
    / "annotate-zotero-pdf"
    / "scripts"
    / "annotate_zotero_pdf.py"
)


@pytest.fixture
def annotation_module():
    return load_script("annotate_zotero_pdf", SCRIPT)


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 80), "Policy effects are persistent.")
    document.save(path)
    document.close()
    return path


def root_response(version: int = 10) -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True},
        headers={
            "Zotero-API-Version": "3",
            "Zotero-Server-ID": "SERVER-ONE",
        },
    )


def attachment_record(*, version: int = 4) -> dict[str, object]:
    return {
        "key": "ATTACH23",
        "version": version,
        "data": {
            "key": "ATTACH23",
            "version": version,
            "itemType": "attachment",
            "parentItem": "PARENT23",
            "linkMode": "imported_file",
            "contentType": "application/pdf",
            "filename": "paper.pdf",
        },
    }


def manifest_entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "attachment_key": "ATTACH23",
        "page": 1,
        "text": "Policy effects are persistent.",
        "type": "highlight",
        "color": "#FFD400",
        "comment": "Core result",
        "tags": ["evidence", "result"],
    }
    entry.update(changes)
    return entry


def planning_handler(
    sample_pdf: Path,
    requests: list[httpx.Request],
    *,
    annotations: list[dict[str, object]] | None = None,
    attachment_version: int = 4,
    library_version: int = 10,
):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response(library_version)
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(
                200,
                json=attachment_record(version=attachment_version),
                headers={"Last-Modified-Version": str(library_version)},
            )
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.url.path == "/api/users/0/items":
            values = annotations or []
            return httpx.Response(
                200,
                json=values,
                headers={
                    "Last-Modified-Version": str(library_version),
                    "Total-Results": str(len(values)),
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return handler


def test_plan_is_get_only_and_normalizes_one_reviewed_batch(
    annotation_module,
    sample_pdf,
):
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(planning_handler(sample_pdf, requests))

    with annotation_module.AnnotateZotero(transport=transport) as client:
        plan = client.plan_manifest([manifest_entry()])

    assert plan["action"] == "create_pdf_annotations"
    assert plan["server_id"] == "SERVER-ONE"
    assert plan["expected_library_version"] == 10
    assert len(plan["plan_id"]) == 16
    assert plan["summary"] == {"annotation_count": 1, "attachment_count": 1}
    planned = plan["annotations"][0]
    assert planned["type"] == "highlight"
    assert planned["color"] == "#ffd400"
    assert planned["tags"] == [{"tag": "evidence"}, {"tag": "result"}]
    assert planned["page_label"] == "1"
    assert planned["position"]["pageIndex"] == 0
    assert planned["position"]["rects"]
    assert {request.method for request in requests} == {"GET"}


def test_one_batch_supports_both_mark_types_comments_colors_and_tags(
    annotation_module,
    sample_pdf,
):
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(planning_handler(sample_pdf, requests))
    manifest = [
        manifest_entry(),
        manifest_entry(
            type="underline",
            color="#2EA8E5",
            comment="Method to revisit",
            tags=["method"],
        ),
    ]

    with annotation_module.AnnotateZotero(transport=transport) as client:
        plan = client.plan_manifest(manifest)

    assert plan["summary"] == {"annotation_count": 2, "attachment_count": 1}
    payloads = [
        annotation_module.AnnotateZotero._payload(annotation)
        for annotation in plan["annotations"]
    ]
    assert [payload["annotationType"] for payload in payloads] == [
        "highlight",
        "underline",
    ]
    assert payloads[0]["annotationComment"] == "Core result"
    assert payloads[0]["annotationColor"] == "#ffd400"
    assert payloads[0]["tags"] == [{"tag": "evidence"}, {"tag": "result"}]
    assert payloads[1]["annotationComment"] == "Method to revisit"
    assert payloads[1]["annotationColor"] == "#2ea8e5"
    assert payloads[1]["tags"] == [{"tag": "method"}]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"attachment_key": "bad"}, "attachment key"),
        ({"page": 0}, "one-based"),
        ({"page": True}, "one-based"),
        ({"text": ""}, "passage"),
        ({"type": "note"}, "highlight or underline"),
        ({"color": "ffd400"}, "color"),
        ({"color": "#abcd"}, "color"),
        ({"tags": "evidence"}, "tags"),
        ({"tags": [""]}, "tag"),
        ({"comment": ["not", "text"]}, "comment"),
        ({"unexpected": "field"}, "unsupported fields"),
    ],
)
def test_manifest_rejects_invalid_entries_before_http(
    annotation_module,
    changes,
    message,
):
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"Unexpected request: {request.url}")
    )
    with (
        annotation_module.AnnotateZotero(transport=transport) as client,
        pytest.raises(ValueError, match=message),
    ):
        client.plan_manifest([manifest_entry(**changes)])


def test_manifest_batch_limit_and_in_batch_duplicate_are_rejected(
    annotation_module,
    sample_pdf,
):
    with pytest.raises(ValueError, match="at most 50"):
        annotation_module.normalize_manifest([manifest_entry()] * 51)

    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(planning_handler(sample_pdf, requests))
    with (
        annotation_module.AnnotateZotero(transport=transport) as client,
        pytest.raises(ValueError, match="duplicate"),
    ):
        client.plan_manifest([manifest_entry(), manifest_entry()])


def test_position_conversion_includes_crop_offset(annotation_module):
    converted = annotation_module.convert_top_left_rect(
        (10.0, 20.0, 50.0, 40.0),
        media_height=800.0,
        crop_x=15.0,
        crop_y=25.0,
    )
    assert converted == [25.0, 735.0, 65.0, 755.0]


def test_pdf_page_label_is_preserved_for_zotero(annotation_module, tmp_path):
    path = tmp_path / "labeled.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 80), "Policy effects are persistent.")
    document.set_page_labels(
        [{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 255}]
    )
    document.save(path)
    document.close()
    snapshot = {"path": str(path)}

    planned = annotation_module.AnnotateZotero._pdf_annotation(
        annotation_module.normalize_manifest([manifest_entry()])[0],
        snapshot,
    )

    assert planned["page"] == 1
    assert planned["page_label"] == "255"
    assert (
        annotation_module.AnnotateZotero._payload(planned)["annotationPageLabel"]
        == "255"
    )


def test_missing_and_ambiguous_passages_are_rejected(
    annotation_module,
    tmp_path,
):
    path = tmp_path / "ambiguous.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 80), "Repeated passage.")
    page.insert_text((40, 120), "Repeated passage.")
    document.save(path)
    document.close()

    with pymupdf.open(path) as opened:
        with pytest.raises(ValueError, match="not found"):
            annotation_module.locate_unique_passage(opened[0], "Missing passage.")
        with pytest.raises(ValueError, match="ambiguous"):
            annotation_module.locate_unique_passage(opened[0], "Repeated passage.")


def test_rotated_and_unsupported_cropbox_pages_are_rejected(
    annotation_module,
    sample_pdf,
):
    with pymupdf.open(sample_pdf) as document:
        page = document[0]
        page.set_rotation(90)
        with pytest.raises(ValueError, match="rotated"):
            annotation_module.validate_page_geometry(page)

    class BadPage:
        rotation = 0
        mediabox = pymupdf.Rect(10, 0, 310, 400)
        cropbox = pymupdf.Rect(0, 0, 300, 400)
        cropbox_position = pymupdf.Point(0, 0)
        rect = pymupdf.Rect(0, 0, 300, 400)

    with pytest.raises(ValueError, match="MediaBox"):
        annotation_module.validate_page_geometry(BadPage())


def annotation_record(planned: dict[str, object], *, key: str = "ANNOT234"):
    return {
        "key": key,
        "version": 11,
        "data": {
            "key": key,
            "version": 11,
            "itemType": "annotation",
            "parentItem": planned["attachment_key"],
            "annotationType": planned["type"],
            "annotationText": planned["text"],
            "annotationComment": planned["comment"],
            "annotationColor": planned["color"],
            "annotationPageLabel": planned["page_label"],
            "annotationSortIndex": planned["sort_index"],
            "annotationPosition": json.dumps(
                planned["position"], separators=(",", ":")
            ),
            "tags": planned["tags"],
        },
    }


def test_existing_duplicate_blocks_planning(annotation_module, sample_pdf):
    requests: list[httpx.Request] = []
    empty_transport = httpx.MockTransport(planning_handler(sample_pdf, requests))
    with annotation_module.AnnotateZotero(transport=empty_transport) as client:
        preliminary = client.plan_manifest([manifest_entry()])

    duplicate = annotation_record(preliminary["annotations"][0])
    duplicate_requests: list[httpx.Request] = []
    transport = httpx.MockTransport(
        planning_handler(sample_pdf, duplicate_requests, annotations=[duplicate])
    )
    with (
        annotation_module.AnnotateZotero(transport=transport) as client,
        pytest.raises(annotation_module.DuplicateAnnotationError, match="already"),
    ):
        client.plan_manifest([manifest_entry()])

    assert {request.method for request in duplicate_requests} == {"GET"}


def make_plan(annotation_module, sample_pdf):
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(planning_handler(sample_pdf, requests))
    with annotation_module.AnnotateZotero(transport=transport) as client:
        return client.plan_manifest([manifest_entry()])


def test_wrong_batch_approval_and_tampering_stop_before_http(
    annotation_module,
    sample_pdf,
):
    plan = make_plan(annotation_module, sample_pdf)
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(
        lambda request: requests.append(request) or root_response()
    )
    with annotation_module.AnnotateZotero(transport=transport) as client:
        with pytest.raises(ValueError, match="exactly match"):
            client.apply_plan(plan, approval="WRONG")

        tampered = json.loads(json.dumps(plan))
        tampered["annotations"][0]["comment"] = "changed"
        with pytest.raises(annotation_module.PlanIntegrityError, match="plan ID"):
            client.apply_plan(tampered, approval=plan["plan_id"])

    assert requests == []


def test_apply_rejects_attachment_version_drift_before_authorization(
    annotation_module,
    sample_pdf,
):
    plan = make_plan(annotation_module, sample_pdf)
    requests: list[httpx.Request] = []
    handler = planning_handler(
        sample_pdf,
        requests,
        attachment_version=5,
        library_version=10,
    )
    with (
        annotation_module.AnnotateZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(annotation_module.PlanDriftError, match="attachment"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert not any(
        request.url.path.endswith("/local/authorize") for request in requests
    )
    assert not any(request.method == "POST" for request in requests)


def test_apply_rechecks_duplicate_after_authorization(
    annotation_module,
    sample_pdf,
):
    plan = make_plan(annotation_module, sample_pdf)
    duplicate = annotation_record(plan["annotations"][0])
    requests: list[httpx.Request] = []
    annotation_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal annotation_reads
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(
                200,
                json=attachment_record(),
                headers={"Last-Modified-Version": "10"},
            )
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.url.path == "/api/users/0/items":
            annotation_reads += 1
            values = [] if annotation_reads == 1 else [duplicate]
            return httpx.Response(
                200,
                json=values,
                headers={
                    "Last-Modified-Version": "10",
                    "Total-Results": str(len(values)),
                },
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with (
        annotation_module.AnnotateZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(annotation_module.DuplicateAnnotationError, match="already"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert (
        sum(request.url.path.endswith("/local/authorize") for request in requests)
        == 1
    )
    assert not any(
        request.method == "POST" and request.url.path.endswith("/users/0/items")
        for request in requests
    )


def test_apply_uses_one_versioned_post_and_verifies_every_created_annotation(
    annotation_module,
    sample_pdf,
):
    plan = make_plan(annotation_module, sample_pdf)
    planned = plan["annotations"][0]
    created = annotation_record(planned)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(
                200,
                json=attachment_record(),
                headers={"Last-Modified-Version": "10"},
            )
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.method == "GET" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "10", "Total-Results": "0"},
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.method == "POST" and request.url.path == "/api/users/0/items":
            assert request.headers["If-Unmodified-Since-Version"] == "10"
            assert request.headers["Zotero-Server-ID"] == "SERVER-ONE"
            assert request.headers["Zotero-API-Key"] == "LOCAL-SECRET"
            payload = json.loads(request.content, object_pairs_hook=dict)
            assert len(payload) == 1
            assert next(iter(payload[0])) == "annotationType"
            return httpx.Response(
                200,
                json={"successful": {"0": "ANNOT234"}, "unchanged": {}, "failed": {}},
            )
        if request.url.path == "/api/users/0/items/ANNOT234":
            return httpx.Response(200, json=created)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with annotation_module.AnnotateZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        receipt = client.apply_plan(plan, approval=plan["plan_id"])

    item_posts = [
        request
        for request in requests
        if request.method == "POST" and request.url.path.endswith("/users/0/items")
    ]
    assert len(item_posts) == 1
    assert receipt["plan_id"] == plan["plan_id"]
    assert receipt["authorization_mode"] == "one_time"
    assert receipt["verified"] is True
    assert receipt["created_annotations"] == [
        {"manifest_index": 1, "key": "ANNOT234", "verified": True}
    ]
    assert "LOCAL-SECRET" not in json.dumps(receipt)


def test_response_failure_is_not_retried(annotation_module, sample_pdf):
    plan = make_plan(annotation_module, sample_pdf)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(
                200,
                json=attachment_record(),
                headers={"Last-Modified-Version": "10"},
            )
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.method == "GET" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "10", "Total-Results": "0"},
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.method == "POST" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json={
                    "successful": {},
                    "unchanged": {},
                    "failed": {"0": {"code": 400}},
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with (
        annotation_module.AnnotateZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(annotation_module.ZoteroAnnotationError, match="failed"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert sum(
        request.method == "POST" and request.url.path.endswith("/users/0/items")
        for request in requests
    ) == 1


def test_server_error_after_submission_is_indeterminate_and_not_retried(
    annotation_module,
    sample_pdf,
):
    plan = make_plan(annotation_module, sample_pdf)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.method == "GET" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "10", "Total-Results": "0"},
            )
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(200, json=attachment_record())
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.method == "POST" and request.url.path == "/api/users/0/items":
            return httpx.Response(503, json={"error": "temporary failure"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with (
        annotation_module.AnnotateZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(
            annotation_module.IndeterminateWriteError,
            match="do not retry automatically",
        ),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])

    assert sum(
        request.method == "POST" and request.url.path.endswith("/users/0/items")
        for request in requests
    ) == 1


def test_readback_mismatch_fails_verification(annotation_module, sample_pdf):
    plan = make_plan(annotation_module, sample_pdf)
    requests: list[httpx.Request] = []
    mismatched = annotation_record(plan["annotations"][0])
    mismatched["data"]["annotationColor"] = "#ff0000"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return root_response()
        if request.url.path == "/api/users/0/items/ATTACH23":
            return httpx.Response(
                200,
                json=attachment_record(),
                headers={"Last-Modified-Version": "10"},
            )
        if request.url.path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx.Response(200, text=sample_pdf.as_uri())
        if request.method == "GET" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json=[],
                headers={"Last-Modified-Version": "10", "Total-Results": "0"},
            )
        if request.url.path == "/api/local/authorize":
            return httpx.Response(
                200,
                json={"key": "LOCAL-SECRET", "remember": False},
            )
        if request.method == "POST" and request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json={"successful": {"0": "ANNOT234"}, "failed": {}},
            )
        if request.url.path == "/api/users/0/items/ANNOT234":
            return httpx.Response(200, json=mismatched)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with (
        annotation_module.AnnotateZotero(
            transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(annotation_module.VerificationError, match="verification"),
    ):
        client.apply_plan(plan, approval=plan["plan_id"])
