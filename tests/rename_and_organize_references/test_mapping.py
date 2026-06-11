from __future__ import annotations

import json


def mapping(root, items, unresolved=None):
    return {
        "schema_version": 1,
        "root": str(root),
        "generated_at": "2026-06-07T12:00:00+00:00",
        "items": items,
        "unresolved": unresolved or [],
    }


def item(source, destination, *, kind="main-paper", confidence="high"):
    return {
        "source": source,
        "destination": destination,
        "kind": kind,
        "confidence": confidence,
    }


def test_contained_path_rejects_absolute_empty_and_dot_paths(rename_module, tmp_path):
    assert rename_module.contained_path(tmp_path, str(tmp_path / "paper.pdf")) is None
    assert rename_module.contained_path(tmp_path, "") is None
    assert rename_module.contained_path(tmp_path, ".") is None


def test_contained_path_rejects_symlink_escape(rename_module, tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    assert rename_module.contained_path(tmp_path, "link/escape.pdf") is None


def test_validate_rejects_path_traversal(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    data = mapping(tmp_path, [item("paper.pdf", "../escape.pdf")])

    errors = rename_module.validate_mapping(data)

    assert any("within root" in error for error in errors)


def test_validate_rejects_duplicate_sources(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    data = mapping(
        tmp_path,
        [
            item("paper.pdf", "one.pdf"),
            item("paper.pdf", "two.pdf", kind="appendix"),
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("duplicate source" in error for error in errors)


def test_validate_rejects_duplicate_destinations(rename_module, tmp_path):
    (tmp_path / "one.pdf").touch()
    (tmp_path / "two.pdf").touch()
    data = mapping(
        tmp_path,
        [
            item("one.pdf", "target.pdf"),
            item("two.pdf", "target.pdf"),
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("duplicate destination" in error for error in errors)


def test_validate_rejects_missing_source(rename_module, tmp_path):
    errors = rename_module.validate_mapping(
        mapping(tmp_path, [item("missing.pdf", "target.pdf")])
    )

    assert any("source does not exist" in error for error in errors)


def test_validate_rejects_unrelated_destination_collision(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    (tmp_path / "target.pdf").touch()
    data = mapping(tmp_path, [item("paper.pdf", "target.pdf")])

    errors = rename_module.validate_mapping(data)

    assert any("already exists" in error for error in errors)


def test_validate_refuses_unresolved_or_review_confidence(rename_module, tmp_path):
    (tmp_path / "paper.pdf").touch()
    data = mapping(
        tmp_path,
        [item("paper.pdf", "target.pdf", confidence="review")],
        unresolved=[{"source": "other.pdf", "reason": "metadata"}],
    )

    errors = rename_module.validate_mapping(data)

    assert any("unresolved" in error for error in errors)
    assert any("confidence" in error for error in errors)


def test_validate_rejects_destination_that_is_another_source(rename_module, tmp_path):
    (tmp_path / "one.pdf").touch()
    (tmp_path / "two.pdf").touch()
    data = mapping(
        tmp_path,
        [
            item("one.pdf", "two.pdf"),
            item("two.pdf", "three.pdf"),
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("another source" in error for error in errors)


def test_validate_rejects_directory_renamed_into_itself(rename_module, tmp_path):
    (tmp_path / "replication").mkdir()
    data = mapping(
        tmp_path,
        [item("replication", "replication/archive", kind="replication")],
    )

    errors = rename_module.validate_mapping(data)

    assert any("overlaps source" in error for error in errors)


def test_validate_rejects_any_destination_inside_directory_source(
    rename_module, tmp_path
):
    replication = tmp_path / "replication"
    replication.mkdir()
    (replication / "code.do").touch()
    data = mapping(
        tmp_path,
        [
            item("replication", "renamed-replication", kind="replication"),
            item("replication/code.do", "replication/renamed.do"),
        ],
    )

    errors = rename_module.validate_mapping(data)

    assert any("overlaps source" in error for error in errors)


def test_validate_accumulates_schema_and_item_errors(rename_module, tmp_path):
    data = {
        "schema_version": 2,
        "root": str(tmp_path),
        "items": [
            "not-an-object",
            item("same.pdf", "same.pdf", kind=[]),
        ],
        "unresolved": "review required",
    }

    errors = rename_module.validate_mapping(data)

    assert "schema_version must equal 1" in errors
    assert any("unresolved" in error for error in errors)
    assert any("must be an object" in error for error in errors)
    assert any("unsupported kind" in error for error in errors)
    assert any("must differ" in error for error in errors)


def test_validate_cli_reports_errors_and_success(rename_module, tmp_path, capsys):
    source = tmp_path / "paper.pdf"
    source.touch()
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(mapping(tmp_path, [item("paper.pdf", "../escape.pdf")])),
        encoding="utf-8",
    )

    assert rename_module.main(["validate", "--mapping", str(mapping_path)]) == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err

    mapping_path.write_text(
        json.dumps(mapping(tmp_path, [item("paper.pdf", "renamed.pdf")])),
        encoding="utf-8",
    )

    assert rename_module.main(["validate", "--mapping", str(mapping_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Mapping is valid.\n"
    assert captured.err == ""
