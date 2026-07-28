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
    / "query-zotero-library"
    / "scripts"
    / "zotero_library.py"
)
SKILL = ROOT / "skills" / "query-zotero-library"


@pytest.fixture
def zotero_module():
    return load_script("zotero_library", SCRIPT)


def test_file_url_to_path_handles_posix_unicode(zotero_module):
    path = zotero_module.file_url_to_path(
        "file:///Users/researcher/Zotero/storage/ABCD1234/"
        "%E5%8F%B0%E7%81%A3%20paper.pdf",
        platform="posix",
    )

    assert path == "/Users/researcher/Zotero/storage/ABCD1234/台灣 paper.pdf"


def test_file_url_to_path_handles_windows_drive(zotero_module):
    path = zotero_module.file_url_to_path(
        "file:///C:/Users/Researcher/Zotero/storage/ABCD1234/My%20Paper.pdf",
        platform="windows",
    )

    assert path == (
        r"C:\Users\Researcher\Zotero\storage\ABCD1234\My Paper.pdf"
    )


def test_file_url_to_path_handles_windows_unc(zotero_module):
    path = zotero_module.file_url_to_path(
        "file://server/share/Zotero/My%20Paper.pdf",
        platform="windows",
    )

    assert path == r"\\server\share\Zotero\My Paper.pdf"


def test_file_url_to_path_rejects_non_file_urls(zotero_module):
    with pytest.raises(ValueError, match="file URL"):
        zotero_module.file_url_to_path(
            "https://example.org/paper.pdf",
            platform="posix",
        )


@pytest.mark.parametrize(
    "file_url",
    [
        "file:relative/paper.pdf",
        "file:///tmp/paper.pdf?download=1",
        "file:///tmp/paper.pdf#page=2",
    ],
)
def test_file_url_to_path_rejects_ambiguous_file_urls(
    zotero_module,
    file_url,
):
    with pytest.raises(ValueError, match="absolute|query|fragment"):
        zotero_module.file_url_to_path(file_url, platform="posix")


def test_collection_paths_resolve_nested_names(zotero_module):
    collections = [
        {
            "key": "PARENT01",
            "data": {
                "name": "0 Working Projects",
                "parentCollection": False,
            },
        },
        {
            "key": "CHILD001",
            "data": {
                "name": "ITS",
                "parentCollection": "PARENT01",
            },
        },
    ]

    paths = zotero_module.build_collection_paths(collections)

    assert paths == {
        "PARENT01": "0 Working Projects",
        "CHILD001": "0 Working Projects / ITS",
    }
    assert (
        zotero_module.resolve_collection_key(
            collections,
            "0 Working Projects / ITS",
        )
        == "CHILD001"
    )


def test_collection_resolution_rejects_ambiguous_bare_name(zotero_module):
    collections = [
        {
            "key": "PARENT01",
            "data": {"name": "Project A", "parentCollection": False},
        },
        {
            "key": "PARENT02",
            "data": {"name": "Project B", "parentCollection": False},
        },
        {
            "key": "CHILD001",
            "data": {"name": "Papers", "parentCollection": "PARENT01"},
        },
        {
            "key": "CHILD002",
            "data": {"name": "Papers", "parentCollection": "PARENT02"},
        },
    ]

    with pytest.raises(ValueError, match="ambiguous"):
        zotero_module.resolve_collection_key(collections, "Papers")


def test_editor_only_item_does_not_relabel_editor_as_author(zotero_module):
    data = {
        "creators": [
            {
                "firstName": "Eleanor",
                "lastName": "Editor",
                "creatorType": "editor",
            }
        ]
    }

    assert zotero_module._authors(data) == []
    assert zotero_module._creators(data) == [
        {"name": "Eleanor Editor", "role": "editor"}
    ]


def test_mixed_creator_roles_preserve_authorship(zotero_module):
    data = {
        "creators": [
            {
                "firstName": "Ada",
                "lastName": "Author",
                "creatorType": "author",
            },
            {
                "firstName": "Eleanor",
                "lastName": "Editor",
                "creatorType": "editor",
            },
        ]
    }

    assert zotero_module._authors(data) == ["Ada Author"]
    assert zotero_module._creators(data) == [
        {"name": "Ada Author", "role": "author"},
        {"name": "Eleanor Editor", "role": "editor"},
    ]


def test_client_rejects_non_loopback_base_url(zotero_module):
    with pytest.raises(ValueError, match="loopback"):
        zotero_module.LocalZotero(base_url="https://api.zotero.org/")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:9999/api/",
        "http://user@localhost:23119/api/",
        "http://localhost:23119/api/?key=secret",
        "http://localhost:23119/api/#fragment",
    ],
)
def test_client_rejects_noncanonical_local_api_base(zotero_module, base_url):
    with pytest.raises(ValueError, match="23119|credentials|query|fragment"):
        zotero_module.LocalZotero(base_url=base_url)


def test_check_reports_documented_header_versions(zotero_module):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/"
        assert "Zotero-API-Key" not in request.headers
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={"version": "undocumented-body-value"},
            headers={
                "Zotero-API-Version": "3",
                "Zotero-Schema-Version": "42",
            },
        )

    transport = httpx.MockTransport(handler)
    with zotero_module.LocalZotero(transport=transport) as client:
        result = client.check()

    assert result == {
        "ok": True,
        "api_version": "3",
        "schema_version": "42",
    }


def test_search_collection_uses_full_text_and_returns_pdf(zotero_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "PARENT01",
                        "data": {
                            "name": "0 Working Projects",
                            "parentCollection": False,
                        },
                    },
                    {
                        "key": "CHILD001",
                        "data": {
                            "name": "ITS",
                            "parentCollection": "PARENT01",
                        },
                    },
                ],
            )
        if request.url.path == (
            "/api/users/0/collections/CHILD001/items/top"
        ):
            assert request.url.params["q"] == "bandwidth selection"
            assert request.url.params["qmode"] == "everything"
            assert request.url.params["limit"] == "5"
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "PAPER001",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Bandwidth Selection for ITS",
                            "date": "2025",
                            "abstractNote": "A study of bandwidth selection.",
                            "DOI": "10.1234/example",
                            "url": "https://example.org/paper",
                            "creators": [
                                {
                                    "firstName": "Ada",
                                    "lastName": "Lovelace",
                                    "creatorType": "author",
                                }
                            ],
                            "tags": [{"tag": "ITS"}],
                            "collections": ["CHILD001"],
                        },
                    }
                ],
                headers={"Total-Results": "7"},
            )
        if request.url.path == "/api/users/0/items/PAPER001/children":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "ATTACH01",
                        "data": {
                            "itemType": "attachment",
                            "contentType": "application/pdf",
                            "filename": "ITS paper.pdf",
                            "title": "Full Text PDF",
                        },
                    }
                ],
            )
        if request.url.path == (
            "/api/users/0/items/ATTACH01/file/view/url"
        ):
            return httpx.Response(
                200,
                text="file:///Users/researcher/Zotero/storage/ATTACH01/"
                "ITS%20paper.pdf",
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    with zotero_module.LocalZotero(transport=transport) as client:
        result = client.search(
            "bandwidth selection",
            collection="0 Working Projects / ITS",
            limit=5,
        )

    assert result["scope"] == {
        "kind": "collection",
        "name": "0 Working Projects / ITS",
        "key": "CHILD001",
    }
    assert result["count"] == 1
    assert result["total_results"] == 7
    assert result["truncated"] is True
    item = result["items"][0]
    assert item["key"] == "PAPER001"
    assert item["authors"] == ["Ada Lovelace"]
    assert item["year"] == "2025"
    assert item["attachments"][0]["path"].endswith("ITS paper.pdf")
    assert {request.method for request in requests} == {"GET"}


def test_search_without_collection_uses_whole_library(zotero_module):
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/users/0/items/top":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    with zotero_module.LocalZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = client.search("fiscal multiplier", limit=3)

    assert result["scope"] == {"kind": "library"}
    assert result["items"] == []
    assert result["total_results"] == 0
    assert result["truncated"] is False
    assert "/api/users/0/collections" not in paths


def test_missing_local_pdf_is_reported_without_losing_item(zotero_module):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/users/0/items/top":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "PAPER001",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "A Paper",
                            "creators": [],
                            "tags": [],
                            "collections": [],
                        },
                    }
                ],
            )
        if request.url.path == "/api/users/0/items/PAPER001/children":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "ATTACH01",
                        "data": {
                            "itemType": "attachment",
                            "contentType": "application/pdf",
                            "filename": "paper.pdf",
                        },
                    }
                ],
            )
        if request.url.path.endswith("/file/view/url"):
            return httpx.Response(404, text="File not found")
        raise AssertionError(f"Unexpected request: {request.url}")

    with zotero_module.LocalZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = client.search("paper")

    attachment = result["items"][0]["attachments"][0]
    assert attachment["available"] is False
    assert attachment["path"] is None
    assert "not available" in attachment["error"].lower()


def test_extract_pdf_ranks_matching_pages(zotero_module, monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class Page:
        def __init__(self, text: str):
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Reader:
        pages = [
            Page("Introduction to interrupted time series."),
            Page("Bandwidth selection bandwidth methods and evidence."),
            Page("Conclusion."),
        ]

    monkeypatch.setattr(zotero_module, "PdfReader", lambda _: Reader())

    result = zotero_module.extract_pdf(
        pdf,
        query="bandwidth selection",
        max_pages=2,
    )

    assert result["total_pages"] == 3
    assert result["pages"][0]["page"] == 2
    assert result["pages"][0]["score"] > 0
    assert len(result["pages"]) == 1
    assert result["matched_pages"] == 1


def test_extract_pdf_requires_query_and_warns_when_nothing_matches(
    zotero_module,
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class Page:
        def extract_text(self) -> str:
            return "A page about an unrelated topic."

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(zotero_module, "PdfReader", lambda _: Reader())

    with pytest.raises(ValueError, match="query"):
        zotero_module.extract_pdf(pdf, query=" ")

    result = zotero_module.extract_pdf(
        pdf,
        query="bandwidth selection",
        max_pages=2,
    )

    assert result["pages"] == []
    assert result["matched_pages"] == 0
    assert any("No pages matched" in warning for warning in result["warnings"])


def test_main_reports_local_api_connection_failure(
    zotero_module,
    monkeypatch,
    capsys,
):
    def fail_check(self):
        request = httpx.Request("GET", "http://localhost:23119/api/")
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(zotero_module.LocalZotero, "check", fail_check)

    exit_code = zotero_module.main(["check"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert "Start Zotero Desktop" in output["error"]
    assert "Local API" in output["error"]


def test_main_reports_unreadable_pdf_as_json(zotero_module, tmp_path, capsys):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a PDF")

    exit_code = zotero_module.main(
        ["extract", str(pdf), "--query", "identification"]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert "PDF" in output["error"]
    assert "read" in output["error"].lower()


def test_skill_documents_zero_config_read_only_evidence_contract():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "The entire personal Zotero library" in text
    assert "optional preferred Zotero collection" in text
    assert "metadata match as a candidate, not evidence" in text
    assert "Do not request, store, or use a Zotero Web API key" in text
    assert "Do not use a third-party Zotero MCP server" in text
    assert "Do not create embeddings" in text
    assert "If the extracted evidence is insufficient" in text
    assert "Total-Results" in text


def test_readme_lists_query_zotero_library():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### `query-zotero-library`" in readme
    assert "macOS, Windows, and Linux" in readme
    assert "Web API keys" in readme
    assert "SQLite" in readme
