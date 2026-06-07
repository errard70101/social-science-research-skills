from __future__ import annotations

import json


def valid_mapping(root, items):
    return {
        "schema_version": 1,
        "root": str(root),
        "generated_at": "2026-06-07T12:00:00+00:00",
        "items": items,
        "unresolved": [],
    }


def test_apply_moves_files_and_writes_result(rename_module, tmp_path):
    (tmp_path / "paper.pdf").write_text("paper")
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "Lee_2024_Trade.pdf",
                "kind": "main-paper",
                "confidence": "high",
            }
        ],
    )
    result_path = tmp_path / "result.json"

    result = rename_module.apply_mapping(data, result_path)

    assert not (tmp_path / "paper.pdf").exists()
    assert (tmp_path / "Lee_2024_Trade.pdf").read_text() == "paper"
    assert result["status"] == "completed"
    assert result["completed"][0]["reverse"]["source"] == "Lee_2024_Trade.pdf"
    assert json.loads(result_path.read_text()) == result


def test_apply_refuses_invalid_mapping_before_changes(rename_module, tmp_path):
    (tmp_path / "paper.pdf").write_text("paper")
    (tmp_path / "target.pdf").write_text("existing")
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "paper.pdf",
                "destination": "target.pdf",
                "kind": "main-paper",
                "confidence": "high",
            }
        ],
    )

    try:
        rename_module.apply_mapping(data, tmp_path / "result.json")
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("invalid mapping must be rejected")

    assert (tmp_path / "paper.pdf").exists()


def test_apply_logs_partial_completion_on_runtime_failure(
    rename_module, tmp_path, monkeypatch
):
    (tmp_path / "one.pdf").touch()
    (tmp_path / "two.pdf").touch()
    data = valid_mapping(
        tmp_path,
        [
            {
                "source": "one.pdf",
                "destination": "one-new.pdf",
                "kind": "main-paper",
                "confidence": "high",
            },
            {
                "source": "two.pdf",
                "destination": "two-new.pdf",
                "kind": "main-paper",
                "confidence": "high",
            },
        ],
    )
    original_move = rename_module.shutil.move
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated failure")
        return original_move(source, destination)

    monkeypatch.setattr(rename_module.shutil, "move", fail_second)
    result_path = tmp_path / "result.json"

    try:
        rename_module.apply_mapping(data, result_path)
    except OSError:
        pass
    else:
        raise AssertionError("runtime failure must be propagated")

    result = json.loads(result_path.read_text())
    assert result["status"] == "failed"
    assert len(result["completed"]) == 1
