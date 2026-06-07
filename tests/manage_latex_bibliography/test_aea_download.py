from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def test_extract_aea_style_accepts_exactly_one_regular_file(
    bibliography_module, tmp_path
):
    data = archive_bytes(
        {
            "folder/aea.bst": b"% official style\n",
            "folder/template.tex": b"ignored",
        }
    )

    result = bibliography_module.extract_aea_style(data, tmp_path)

    assert (tmp_path / "aea.bst").read_bytes() == b"% official style\n"
    assert result == {
        "path": str(tmp_path.resolve() / "aea.bst"),
        "sha256": bibliography_module.sha256_bytes(b"% official style\n"),
        "status": "installed",
    }


@pytest.mark.parametrize(
    "files",
    [
        {"../aea.bst": b"bad"},
        {"one/aea.bst": b"one", "two/aea.bst": b"two"},
        {"other.bst": b"missing"},
    ],
)
def test_extract_aea_style_rejects_unsafe_archives(
    bibliography_module, tmp_path, files
):
    with pytest.raises(ValueError):
        bibliography_module.extract_aea_style(archive_bytes(files), tmp_path)


def test_extract_aea_style_rejects_duplicate_members(
    bibliography_module, tmp_path
):
    buffer = io.BytesIO()
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(buffer, "w") as archive,
    ):
        archive.writestr("aea.bst", b"one")
        archive.writestr("aea.bst", b"two")

    with pytest.raises(ValueError, match="duplicate archive member"):
        bibliography_module.extract_aea_style(buffer.getvalue(), tmp_path)


def test_extract_aea_style_rejects_symbolic_link(
    bibliography_module, tmp_path
):
    buffer = io.BytesIO()
    link = zipfile.ZipInfo("aea.bst")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(link, "target")

    with pytest.raises(ValueError, match="links are not allowed"):
        bibliography_module.extract_aea_style(buffer.getvalue(), tmp_path)


def test_extract_aea_style_refuses_different_existing_file(
    bibliography_module, tmp_path
):
    (tmp_path / "aea.bst").write_bytes(b"local")
    data = archive_bytes({"aea.bst": b"official"})

    with pytest.raises(ValueError, match="refusing to overwrite"):
        bibliography_module.extract_aea_style(data, tmp_path)

    assert (tmp_path / "aea.bst").read_bytes() == b"local"


def test_extract_aea_style_enforces_archive_limits(
    bibliography_module, tmp_path, monkeypatch
):
    payload = archive_bytes({"aea.bst": b"style"})
    monkeypatch.setattr(
        bibliography_module, "MAX_ARCHIVE_BYTES", len(payload) - 1
    )
    with pytest.raises(ValueError, match="size limit"):
        bibliography_module.extract_aea_style(payload, tmp_path)

    monkeypatch.setattr(bibliography_module, "MAX_ARCHIVE_BYTES", 5_000_000)
    monkeypatch.setattr(bibliography_module, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(ValueError, match="too many entries"):
        bibliography_module.extract_aea_style(
            archive_bytes({"aea.bst": b"style", "extra": b"x"}), tmp_path
        )

    monkeypatch.setattr(bibliography_module, "MAX_ARCHIVE_ENTRIES", 100)
    monkeypatch.setattr(bibliography_module, "MAX_UNCOMPRESSED_BYTES", 3)
    with pytest.raises(ValueError, match="uncompressed size"):
        bibliography_module.extract_aea_style(
            archive_bytes({"aea.bst": b"style"}), tmp_path
        )


def test_install_requires_official_final_host(
    bibliography_module, tmp_path
):
    def downloader(url):
        return (
            "https://mirror.example/aea.zip",
            archive_bytes({"aea.bst": b"style"}),
        )

    with pytest.raises(ValueError, match="official AEA host"):
        bibliography_module.install_aea_style(tmp_path, downloader=downloader)


def test_install_records_provenance_and_identical_file(
    bibliography_module, tmp_path
):
    payload = archive_bytes({"aea.bst": b"style"})

    def downloader(url):
        assert url == bibliography_module.AEA_TEMPLATE_URL
        return (
            "https://www.aeaweb.org/journals/templates/latex_templates",
            payload,
        )

    first = bibliography_module.install_aea_style(
        tmp_path, downloader=downloader
    )
    second = bibliography_module.install_aea_style(
        tmp_path, downloader=downloader
    )

    assert first["status"] == "installed"
    assert second["status"] == "unchanged"
    report = json.loads(
        (tmp_path / "aea-style-download.json").read_text(encoding="utf-8")
    )
    assert report["source_url"].startswith("https://www.aeaweb.org/")
    assert report["sha256"] == bibliography_module.sha256_bytes(b"style")
    assert report["retrieved_at"]


def test_confirmed_install_cli_invokes_installer(
    bibliography_module, tmp_path, monkeypatch
):
    calls = []

    def fake_install(project):
        calls.append(project)
        return {}

    monkeypatch.setattr(bibliography_module, "install_aea_style", fake_install)

    assert bibliography_module.main(
        [
            "install-aea-style",
            "--project",
            str(tmp_path),
            "--confirm-download",
        ]
    ) == 0
    assert calls == [tmp_path]
