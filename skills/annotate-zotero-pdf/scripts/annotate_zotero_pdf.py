#!/usr/bin/env python3
"""Plan and apply verified batches of Zotero-native PDF annotations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import httpx
import pymupdf

MAX_BATCH_ANNOTATIONS = 50
PLAN_SCHEMA_VERSION = 1
ANNOTATION_TYPES = {"highlight", "underline"}
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ALLOWED_MANIFEST_FIELDS = {
    "attachment_key",
    "page",
    "text",
    "type",
    "comment",
    "color",
    "tags",
}


def _load_sibling(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load required skill helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_manager = _load_sibling(
    "_ssrs_zotero_manager",
    _SKILLS_ROOT
    / "manage-zotero-library"
    / "scripts"
    / "zotero_manager.py",
)
_reader = _load_sibling(
    "_ssrs_zotero_reader",
    _SKILLS_ROOT / "query-zotero-library" / "scripts" / "zotero_library.py",
)

PlanDriftError = _manager.PlanDriftError
PlanIntegrityError = _manager.PlanIntegrityError
AuthorizationError = _manager.AuthorizationError


class ZoteroAnnotationError(RuntimeError):
    """Base error for PDF annotation planning and application."""


class DuplicateAnnotationError(ZoteroAnnotationError):
    """A proposed annotation already exists in the batch or library."""


class VerificationError(ZoteroAnnotationError):
    """A created annotation did not match its reviewed plan."""


class IndeterminateWriteError(ZoteroAnnotationError):
    """A submitted batch may have changed Zotero but lacks a safe result."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("PDF page geometry contains a non-finite coordinate")
    return number


def normalize_manifest(manifest: object) -> list[dict[str, object]]:
    """Validate and normalize the reviewed annotation manifest."""
    if not isinstance(manifest, list):
        raise ValueError("The annotation manifest must be a JSON array")
    if not manifest:
        raise ValueError("At least one PDF annotation is required")
    if len(manifest) > MAX_BATCH_ANNOTATIONS:
        raise ValueError(
            f"An annotation batch can contain at most {MAX_BATCH_ANNOTATIONS} entries"
        )

    normalized: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for index, raw in enumerate(manifest, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest entry {index} must be an object")
        unexpected = set(raw) - ALLOWED_MANIFEST_FIELDS
        if unexpected:
            fields = ", ".join(sorted(unexpected))
            raise ValueError(
                f"Manifest entry {index} has unsupported fields: {fields}"
            )

        try:
            attachment_key = _manager.normalize_key(
                str(raw.get("attachment_key") or ""),
                kind="attachment",
            )
        except ValueError as exc:
            raise ValueError(
                f"Manifest entry {index} has an invalid attachment key"
            ) from exc

        page = raw.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError(
                f"Manifest entry {index} page must be a positive one-based integer"
            )

        passage = raw.get("text")
        if not isinstance(passage, str) or not passage.strip():
            raise ValueError(f"Manifest entry {index} passage text cannot be blank")
        passage = passage.strip()

        annotation_type = raw.get("type")
        if annotation_type not in ANNOTATION_TYPES:
            raise ValueError(
                f"Manifest entry {index} type must be highlight or underline"
            )

        color = raw.get("color")
        if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
            raise ValueError(
                f"Manifest entry {index} color must be a six-digit hex color"
            )
        color = color.casefold()

        comment = raw.get("comment", "")
        if not isinstance(comment, str):
            raise ValueError(f"Manifest entry {index} comment must be text")

        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ValueError(f"Manifest entry {index} tags must be an array")
        tags: list[dict[str, str]] = []
        seen_tags: set[str] = set()
        for raw_tag in raw_tags:
            if not isinstance(raw_tag, str) or not raw_tag.strip():
                raise ValueError(
                    f"Manifest entry {index} annotation tag cannot be blank"
                )
            tag = raw_tag.strip()
            if tag not in seen_tags:
                tags.append({"tag": tag})
                seen_tags.add(tag)

        duplicate_identity = (
            attachment_key,
            page,
            passage,
            annotation_type,
        )
        if duplicate_identity in seen:
            raise ValueError(
                f"Manifest entry {index} is a duplicate annotation in this batch"
            )
        seen.add(duplicate_identity)
        normalized.append(
            {
                "manifest_index": index,
                "attachment_key": attachment_key,
                "page": page,
                "text": passage,
                "type": annotation_type,
                "color": color,
                "comment": comment,
                "tags": tags,
            }
        )
    return normalized


def validate_page_geometry(page: object) -> dict[str, float]:
    """Return safe page-box geometry or reject unsupported PDF geometry."""
    rotation = getattr(page, "rotation", None)
    if rotation != 0:
        raise ValueError("rotated PDF pages are not supported")

    media = page.mediabox
    media_x0 = _finite(media.x0)
    media_y0 = _finite(media.y0)
    media_width = _finite(media.width)
    media_height = _finite(media.height)
    if media_x0 != 0 or media_y0 != 0:
        raise ValueError("PDF pages with a non-zero MediaBox origin are unsupported")
    if media_width <= 0 or media_height <= 0:
        raise ValueError("PDF page MediaBox must have positive dimensions")

    crop = page.cropbox
    crop_position = page.cropbox_position
    page_rect = page.rect
    crop_x = _finite(crop_position.x)
    crop_y = _finite(crop_position.y)
    crop_width = _finite(crop.width)
    crop_height = _finite(crop.height)
    rect_width = _finite(page_rect.width)
    rect_height = _finite(page_rect.height)
    tolerance = 0.01
    if (
        crop_x < 0
        or crop_y < 0
        or crop_width <= 0
        or crop_height <= 0
        or crop_x + crop_width > media_width + tolerance
        or crop_y + crop_height > media_height + tolerance
        or abs(rect_width - crop_width) > tolerance
        or abs(rect_height - crop_height) > tolerance
    ):
        raise ValueError("Unsupported PDF CropBox geometry")
    return {
        "media_height": media_height,
        "crop_x": crop_x,
        "crop_y": crop_y,
    }


def convert_top_left_rect(
    rect: object,
    *,
    media_height: float,
    crop_x: float,
    crop_y: float,
) -> list[float]:
    """Convert a PyMuPDF top-left rectangle to Zotero PDF coordinates."""
    x0, y0, x1, y1 = (_finite(value) for value in rect)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("PDF text rectangle has invalid bounds")
    converted = [
        crop_x + x0,
        media_height - (crop_y + y1),
        crop_x + x1,
        media_height - (crop_y + y0),
    ]
    return [round(value, 3) for value in converted]


def locate_unique_passage(page: object, passage: str) -> dict[str, object]:
    """Locate one exact word sequence and return its top-left rectangles."""
    expected_words = passage.split()
    words = list(page.get_text("words", sort=False))
    extracted_words = [str(word[4]) for word in words]
    width = len(expected_words)
    matches = [
        index
        for index in range(len(words) - width + 1)
        if extracted_words[index : index + width] == expected_words
    ]
    if not matches:
        raise ValueError(f"Exact passage was not found on PDF page: {passage!r}")
    if len(matches) > 1:
        raise ValueError(f"Exact passage is ambiguous on PDF page: {passage!r}")

    start = matches[0]
    selected = words[start : start + width]
    merged: list[list[float]] = []
    line_identity: tuple[object, object] | None = None
    for word in selected:
        current_line = (word[5], word[6])
        bounds = [_finite(value) for value in word[:4]]
        if merged and current_line == line_identity:
            merged[-1][0] = min(merged[-1][0], bounds[0])
            merged[-1][1] = min(merged[-1][1], bounds[1])
            merged[-1][2] = max(merged[-1][2], bounds[2])
            merged[-1][3] = max(merged[-1][3], bounds[3])
        else:
            merged.append(bounds)
            line_identity = current_line

    character_offset = sum(len(value) + 1 for value in extracted_words[:start])
    return {
        "rects": merged,
        "character_offset": character_offset,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _position_value(value: object) -> dict[str, object] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _canonical_rects(value: object) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for rect in value:
        if not isinstance(rect, list) or len(rect) != 4:
            return ()
        try:
            result.append(tuple(round(_finite(point), 3) for point in rect))
        except (TypeError, ValueError):
            return ()
    return tuple(result)


def _planned_duplicate_identity(annotation: dict[str, object]) -> tuple[object, ...]:
    position = annotation.get("position")
    if not isinstance(position, dict):
        raise PlanIntegrityError("Annotation plan has malformed position geometry")
    return (
        annotation.get("attachment_key"),
        annotation.get("type"),
        annotation.get("text"),
        position.get("pageIndex"),
        _canonical_rects(position.get("rects")),
    )


def _existing_duplicate_identity(record: dict[str, object]) -> tuple[object, ...]:
    data = record.get("data")
    if not isinstance(data, dict):
        return ()
    position = _position_value(data.get("annotationPosition"))
    if position is None:
        return ()
    return (
        data.get("parentItem"),
        data.get("annotationType"),
        data.get("annotationText"),
        position.get("pageIndex"),
        _canonical_rects(position.get("rects")),
    )


def sign_plan(plan: dict[str, object]) -> dict[str, object]:
    """Return a deep-copied plan with a deterministic content ID."""
    return _manager.sign_plan(plan)


def validate_plan(plan: dict[str, object]) -> None:
    """Validate annotation plan integrity before any external request."""
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanIntegrityError("Unsupported PDF annotation plan schema")
    if plan.get("action") != "create_pdf_annotations":
        raise PlanIntegrityError("Unsupported PDF annotation plan action")
    plan_id = plan.get("plan_id")
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    expected_id = sign_plan(unsigned)["plan_id"]
    if not isinstance(plan_id, str) or plan_id != expected_id:
        raise PlanIntegrityError("PDF annotation plan ID does not match content")
    annotations = plan.get("annotations")
    snapshots = plan.get("attachment_snapshots")
    if (
        not isinstance(annotations, list)
        or not annotations
        or len(annotations) > MAX_BATCH_ANNOTATIONS
        or any(not isinstance(value, dict) for value in annotations)
    ):
        raise PlanIntegrityError("PDF annotation plan has malformed annotations")
    if not isinstance(snapshots, list) or not snapshots:
        raise PlanIntegrityError("PDF annotation plan has no attachment snapshots")
    version = plan.get("expected_library_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise PlanIntegrityError("PDF annotation plan has no library version")


class AnnotateZotero(_manager.ManageZotero):
    """Create Zotero-native PDF annotations through one reviewed batch."""

    def __init__(self, **kwargs: object) -> None:
        if kwargs.get("backend", "local") != "local":
            raise ValueError("PDF annotation creation supports only the Local API")
        super().__init__(**kwargs)

    def _planning_context(self) -> dict[str, object]:
        response = self._request("GET", "")
        server_id = response.headers.get("Zotero-Server-ID", "").strip()
        return {
            "api_backend": "local",
            "server_id": server_id or None,
            "local_api_write_supported": bool(server_id),
            "application_mode": (
                "local_api" if server_id else "manual_zotero_desktop"
            ),
        }

    def _attachment_snapshot(
        self,
        key: str,
    ) -> dict[str, object]:
        response = self._request("GET", self._library_path(f"items/{key}"))
        record = _manager._response_json(response, f"attachment {key}")
        if not isinstance(record, dict):
            raise ZoteroAnnotationError(f"Zotero attachment {key} is malformed")
        data = record.get("data")
        if not isinstance(data, dict):
            raise ZoteroAnnotationError(f"Zotero attachment {key} has malformed data")
        content_type = str(data.get("contentType") or "").casefold()
        filename = str(data.get("filename") or "")
        if data.get("itemType") != "attachment" or not (
            content_type == "application/pdf" or filename.casefold().endswith(".pdf")
        ):
            raise ValueError(f"Zotero item {key} is not a PDF attachment")
        version = data.get("version", record.get("version"))
        if not isinstance(version, int) or isinstance(version, bool):
            raise ZoteroAnnotationError(f"Zotero attachment {key} has no version")

        file_response = self._request(
            "GET", self._library_path(f"items/{key}/file/view/url")
        )
        path = Path(_reader.file_url_to_path(file_response.text.strip()))
        if not path.is_file():
            raise ValueError(f"The exact local PDF for attachment {key} is unavailable")
        return {
            "key": key,
            "version": version,
            "parent_item": data.get("parentItem") or "",
            "link_mode": data.get("linkMode") or "",
            "content_type": data.get("contentType") or "",
            "filename": filename,
            "path": str(path),
            "file_size": path.stat().st_size,
            "pdf_sha256": _file_sha256(path),
        }

    def _all_annotations(
        self,
        *,
        expected_library_version: int | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        records: list[dict[str, object]] = []
        start = 0
        observed_version: int | None = None
        while True:
            response = self._request(
                "GET",
                self._library_path("items"),
                params={"itemType": "annotation", "limit": 100, "start": start},
            )
            response_version = _manager._response_version(response)
            if observed_version is None:
                observed_version = response_version
            if response_version != observed_version or (
                expected_library_version is not None
                and response_version != expected_library_version
            ):
                raise PlanDriftError(
                    "The Zotero library changed while reading annotations"
                )
            payload = _manager._response_json(response, "PDF annotations")
            if not isinstance(payload, list) or any(
                not isinstance(record, dict) for record in payload
            ):
                raise ZoteroAnnotationError(
                    "Zotero returned malformed PDF annotations"
                )
            records.extend(payload)
            total_value = response.headers.get("Total-Results", "")
            total = int(total_value) if total_value.isdecimal() else None
            if (total is not None and len(records) >= total) or not payload:
                break
            if total is None and len(payload) < 100:
                break
            start += len(payload)
        if observed_version is None:
            raise ZoteroAnnotationError(
                "Zotero did not report a library version for annotations"
            )
        return records, observed_version

    @staticmethod
    def _assert_no_duplicates(
        planned: list[dict[str, object]],
        existing: list[dict[str, object]],
    ) -> None:
        existing_by_identity = {
            identity
            for record in existing
            if (identity := _existing_duplicate_identity(record))
        }
        for annotation in planned:
            if _planned_duplicate_identity(annotation) in existing_by_identity:
                raise DuplicateAnnotationError(
                    "A planned PDF annotation already exists in Zotero"
                )

    @staticmethod
    def _pdf_annotation(
        entry: dict[str, object],
        snapshot: dict[str, object],
    ) -> dict[str, object]:
        page_number = int(entry["page"])
        path = Path(str(snapshot["path"]))
        with pymupdf.open(path) as document:
            if page_number > document.page_count:
                raise ValueError(
                    f"PDF page {page_number} does not exist in attachment "
                    f"{entry['attachment_key']}"
                )
            page = document[page_number - 1]
            geometry = validate_page_geometry(page)
            located = locate_unique_passage(page, str(entry["text"]))
            top_left_rects = located["rects"]
            position_rects = [
                convert_top_left_rect(rect, **geometry) for rect in top_left_rects
            ]
            first_top_left_rect = top_left_rects[0]
            top = max(
                0,
                math.floor(geometry["crop_y"] + first_top_left_rect[1]),
            )
            character_offset = min(int(located["character_offset"]), 999999)
            page_label = page.get_label() or str(page_number)
            if page_number - 1 > 99999 or top > 99999:
                raise ValueError("PDF annotation sort index exceeds Zotero limits")

        return {
            **entry,
            "page_label": page_label,
            "position": {"pageIndex": page_number - 1, "rects": position_rects},
            "sort_index": (
                f"{page_number - 1:05d}|{character_offset:06d}|{top:05d}"
            ),
        }

    def plan_manifest(self, manifest: object) -> dict[str, object]:
        entries = normalize_manifest(manifest)
        context = self._planning_context()
        existing, library_version = self._all_annotations()
        attachment_keys = list(
            dict.fromkeys(str(entry["attachment_key"]) for entry in entries)
        )
        snapshots = [
            self._attachment_snapshot(key)
            for key in attachment_keys
        ]
        snapshots_by_key = {
            str(snapshot["key"]): snapshot for snapshot in snapshots
        }
        annotations = [
            self._pdf_annotation(
                entry,
                snapshots_by_key[str(entry["attachment_key"])],
            )
            for entry in entries
        ]
        self._assert_no_duplicates(annotations, existing)
        return sign_plan(
            {
                "schema_version": PLAN_SCHEMA_VERSION,
                "created_at": _now(),
                "action": "create_pdf_annotations",
                **context,
                "expected_library_version": library_version,
                "summary": {
                    "annotation_count": len(annotations),
                    "attachment_count": len(snapshots),
                },
                "attachment_snapshots": snapshots,
                "annotations": annotations,
            }
        )

    @staticmethod
    def _snapshot_by_key(plan: dict[str, object]) -> dict[str, dict[str, object]]:
        snapshots = plan["attachment_snapshots"]
        if not isinstance(snapshots, list):
            raise PlanIntegrityError("PDF annotation plan has malformed snapshots")
        result: dict[str, dict[str, object]] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, dict) or not isinstance(
                snapshot.get("key"), str
            ):
                raise PlanIntegrityError(
                    "PDF annotation plan has a malformed attachment snapshot"
                )
            result[str(snapshot["key"])] = snapshot
        if len(result) != len(snapshots):
            raise PlanIntegrityError("PDF annotation plan repeats an attachment")
        return result

    def _assert_unchanged(self, plan: dict[str, object]) -> None:
        expected_version = int(plan["expected_library_version"])
        context = self._planning_context()
        if context.get("server_id") != plan.get("server_id"):
            raise PlanDriftError(
                "The plan belongs to a different Zotero database instance"
            )
        existing, current_version = self._all_annotations()
        if current_version != expected_version:
            raise PlanDriftError("The Zotero library version changed after planning")

        planned_snapshots = self._snapshot_by_key(plan)
        current_snapshots = {
            key: self._attachment_snapshot(key)
            for key in planned_snapshots
        }
        for key, planned in planned_snapshots.items():
            if current_snapshots[key] != planned:
                raise PlanDriftError(
                    f"Zotero attachment {key} changed after planning"
                )

        annotations = plan["annotations"]
        if not isinstance(annotations, list):
            raise PlanIntegrityError("PDF annotation plan has malformed annotations")
        for planned in annotations:
            if not isinstance(planned, dict):
                raise PlanIntegrityError("PDF annotation plan has malformed entries")
            current = self._pdf_annotation(
                {
                    key: planned[key]
                    for key in (
                        "manifest_index",
                        "attachment_key",
                        "page",
                        "page_label",
                        "text",
                        "type",
                        "color",
                        "comment",
                        "tags",
                    )
                },
                current_snapshots[str(planned["attachment_key"])],
            )
            if current != planned:
                raise PlanDriftError(
                    "The exact PDF passage geometry changed after planning"
                )
        self._assert_no_duplicates(annotations, existing)

    @staticmethod
    def _payload(annotation: dict[str, object]) -> dict[str, object]:
        return {
            "annotationType": annotation["type"],
            "itemType": "annotation",
            "parentItem": annotation["attachment_key"],
            "annotationText": annotation["text"],
            "annotationComment": annotation["comment"],
            "annotationColor": annotation["color"],
            "annotationPageLabel": annotation["page_label"],
            "annotationSortIndex": annotation["sort_index"],
            "annotationPosition": json.dumps(
                annotation["position"], ensure_ascii=False, separators=(",", ":")
            ),
            "tags": annotation["tags"],
            "relations": {},
        }

    @staticmethod
    def _created_key(value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            return str(value["key"])
        return None

    @staticmethod
    def _readback_matches(
        record: dict[str, object],
        planned: dict[str, object],
    ) -> bool:
        data = record.get("data")
        if not isinstance(data, dict):
            return False
        position = _position_value(data.get("annotationPosition"))
        expected_position = planned.get("position")
        actual_tags = data.get("tags")
        expected_tags = planned.get("tags")
        if not isinstance(actual_tags, list) or not isinstance(expected_tags, list):
            return False
        tag_names = sorted(
            str(tag.get("tag"))
            for tag in actual_tags
            if isinstance(tag, dict) and tag.get("tag")
        )
        expected_tag_names = sorted(
            str(tag.get("tag"))
            for tag in expected_tags
            if isinstance(tag, dict) and tag.get("tag")
        )
        return (
            data.get("itemType") == "annotation"
            and data.get("parentItem") == planned.get("attachment_key")
            and data.get("annotationType") == planned.get("type")
            and data.get("annotationText") == planned.get("text")
            and data.get("annotationComment") == planned.get("comment")
            and data.get("annotationColor") == planned.get("color")
            and data.get("annotationPageLabel") == planned.get("page_label")
            and data.get("annotationSortIndex") == planned.get("sort_index")
            and position == expected_position
            and tag_names == expected_tag_names
        )

    def apply_plan(
        self,
        plan: dict[str, object],
        *,
        approval: str,
    ) -> dict[str, object]:
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or approval != plan_id:
            raise ValueError("The approval must exactly match the batch plan ID")
        validate_plan(plan)
        if (
            plan.get("application_mode") != "local_api"
            or plan.get("local_api_write_supported") is not True
            or not isinstance(plan.get("server_id"), str)
        ):
            raise ZoteroAnnotationError(
                "This Zotero Local API cannot apply PDF annotation writes"
            )

        self._assert_unchanged(plan)
        server_id = str(plan["server_id"])
        api_key = self.authorize_write(server_id)
        self._assert_unchanged(plan)

        annotations = plan["annotations"]
        if not isinstance(annotations, list):
            raise PlanIntegrityError("PDF annotation plan has malformed entries")
        payload = [self._payload(annotation) for annotation in annotations]
        try:
            response = self._write_request(
                "POST",
                self._library_path("items"),
                server_id=server_id,
                json_body=payload,
                headers=self._write_headers(
                    server_id,
                    api_key,
                    version=int(plan["expected_library_version"]),
                ),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise IndeterminateWriteError(
                    "Zotero returned a server error after the annotation batch "
                    f"was submitted for plan {plan_id}; inspect with GET requests "
                    "and do not retry automatically"
                ) from exc
            raise
        result = _manager._response_json(response, "PDF annotation batch creation")
        if not isinstance(result, dict):
            raise ZoteroAnnotationError(
                "Zotero returned a malformed annotation batch response"
            )
        successes = result.get("successful", result.get("success"))
        failures = result.get("failed", {})
        unchanged = result.get("unchanged", {})
        if not isinstance(successes, dict):
            successes = {}
        if not isinstance(failures, dict):
            failures = {"response": failures}
        if not isinstance(unchanged, dict):
            unchanged = {"response": unchanged}

        created: list[dict[str, object]] = []
        verification_failed = False
        for index, planned in enumerate(annotations):
            if not isinstance(planned, dict):
                raise PlanIntegrityError("PDF annotation plan has malformed entries")
            key = self._created_key(successes.get(str(index)))
            if key is None:
                continue
            record = self._get_item(key)
            verified = self._readback_matches(record, planned)
            verification_failed = verification_failed or not verified
            created.append(
                {
                    "manifest_index": planned["manifest_index"],
                    "key": key,
                    "verified": verified,
                }
            )

        if failures or unchanged or len(created) != len(annotations):
            created_keys = ", ".join(str(value["key"]) for value in created)
            created_note = (
                f" Created keys observed before stopping: {created_keys}."
                if created_keys
                else ""
            )
            raise ZoteroAnnotationError(
                "Zotero annotation batch failed or returned incomplete results; "
                f"the write was not retried.{created_note}"
            )
        if verification_failed:
            raise VerificationError(
                "Created Zotero annotation verification did not match the plan"
            )
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "action": "create_pdf_annotations",
            "applied_at": _now(),
            "authorization_mode": self.authorization_mode,
            "verified": True,
            "created_annotations": created,
        }


def _load_json(path: Path, *, expected: type) -> object:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, expected):
        label = "array" if expected is list else "object"
        raise ValueError(f"{path} must contain a JSON {label}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _manager.JsonArgumentParser(
        description="Plan and apply Zotero-native PDF annotation batches."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Create a GET-only batch plan")
    plan.add_argument("manifest", type=Path)
    plan.add_argument("--output", type=Path, required=True)
    apply = subparsers.add_parser("apply", help="Apply one approved batch plan")
    apply.add_argument("plan", type=Path)
    apply.add_argument("--approve", required=True)
    apply.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output = args.output if args.command == "plan" else args.receipt
    try:
        _manager.ensure_output_available(output)
        with AnnotateZotero() as client:
            if args.command == "plan":
                manifest = _load_json(args.manifest, expected=list)
                result = client.plan_manifest(manifest)
            else:
                plan = _load_json(args.plan, expected=dict)
                result = client.apply_plan(plan, approval=args.approve)
        _manager.write_json_exclusive(output, result)
        _manager.print_json(result)
        return 0
    except (httpx.ConnectError, httpx.ConnectTimeout):
        _manager.print_json(
            {
                "error": (
                    "Cannot connect to Zotero Desktop. Start Zotero and enable "
                    "local application access."
                )
            }
        )
        return 1
    except httpx.TimeoutException:
        details: dict[str, object] = {
            "error": "Zotero request timed out; do not retry a possible write",
            "safe_to_retry": False,
        }
        if args.command == "apply":
            details["plan"] = str(args.plan)
        _manager.print_json(details)
        return 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        httpx.HTTPStatusError,
        ZoteroAnnotationError,
        _manager.ZoteroManagementError,
    ) as exc:
        _manager.print_json({"error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
