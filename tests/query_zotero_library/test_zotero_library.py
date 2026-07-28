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


def test_collection_resolution_accepts_exact_collection_key(zotero_module):
    collections = [
        {
            "key": "2JY7DCQX",
            "data": {"name": "Japanese Female", "parentCollection": False},
        }
    ]

    assert (
        zotero_module.resolve_collection_key(collections, "2JY7DCQX")
        == "2JY7DCQX"
    )

    with pytest.raises(ValueError, match="key"):
        zotero_module.resolve_collection_key(collections, "3ABCDEFH")


def test_key_shaped_collection_name_still_resolves_by_name(zotero_module):
    collections = [
        {
            "key": "2JY7DCQX",
            "data": {"name": "RESEARCH", "parentCollection": False},
        }
    ]

    assert (
        zotero_module.resolve_collection_key(collections, "RESEARCH")
        == "2JY7DCQX"
    )


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


def test_collection_catalog_returns_paths_keys_and_counts(zotero_module):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/users/0/collections"
        return httpx.Response(
            200,
            json=[
                {
                    "key": "PARENT01",
                    "data": {
                        "name": "Projects",
                        "parentCollection": False,
                    },
                    "meta": {"numItems": 2},
                },
                {
                    "key": "2JY7DCQX",
                    "data": {
                        "name": "Japanese Female",
                        "parentCollection": "PARENT01",
                    },
                    "meta": {"numItems": 7},
                },
            ],
        )

    with zotero_module.LocalZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = client.collection_catalog()

    assert result == {
        "count": 2,
        "collections": [
            {
                "name": "Projects",
                "path": "Projects",
                "key": "PARENT01",
                "item_count": 2,
            },
            {
                "name": "Japanese Female",
                "path": "Projects / Japanese Female",
                "key": "2JY7DCQX",
                "item_count": 7,
            },
        ],
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
    assert "%20" not in item["attachments"][0]["path"]
    assert "file_url" not in item["attachments"][0]
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


def test_notes_and_annotations_returns_readable_context(zotero_module):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/users/0/items/PAPER234":
            return httpx.Response(
                200,
                json={
                    "key": "PAPER234",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "An ITS Paper",
                    },
                },
            )
        if request.url.path == "/api/users/0/items/PAPER234/children":
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "NOTE0001",
                        "data": {
                            "itemType": "note",
                            "note": "<p>Main result &amp; caveat.</p>",
                            "tags": [{"tag": "reviewed"}],
                            "dateModified": "2026-07-29T00:00:00Z",
                        },
                    },
                    {
                        "key": "ATTACH01",
                        "data": {
                            "itemType": "attachment",
                            "contentType": "application/pdf",
                            "filename": "paper.pdf",
                            "title": "Full Text PDF",
                        },
                    },
                ],
            )
        if request.url.path == "/api/users/0/items":
            assert request.url.params["itemType"] == "annotation"
            assert request.url.params["limit"] == "100"
            if request.url.params["start"] == "0":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "key": "ANNOT001",
                            "data": {
                                "itemType": "annotation",
                                "parentItem": "ATTACH01",
                                "annotationType": "highlight",
                                "annotationText": "Bandwidth choice matters.",
                                "annotationComment": "Compare with placebo.",
                                "annotationColor": "#ffd400",
                                "annotationPageLabel": "12",
                                "annotationSortIndex": "00012|000001",
                                "tags": [{"tag": "identification"}],
                                "dateModified": "2026-07-29T00:01:00Z",
                            },
                        }
                    ],
                    headers={"Total-Results": "2"},
                )
            assert request.url.params["start"] == "1"
            return httpx.Response(
                200,
                json=[
                    {
                        "key": "OTHER001",
                        "data": {
                            "itemType": "annotation",
                            "parentItem": "OTHERPDF",
                            "annotationType": "highlight",
                            "annotationText": "Unrelated annotation.",
                        },
                    }
                ],
                headers={"Total-Results": "2"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with zotero_module.LocalZotero(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = client.notes_and_annotations("PAPER234")

    assert result["item"] == {
        "key": "PAPER234",
        "item_type": "journalArticle",
        "title": "An ITS Paper",
    }
    assert result["note_count"] == 1
    assert result["notes"] == [
        {
            "key": "NOTE0001",
            "text": "Main result & caveat.",
            "tags": ["reviewed"],
            "date_modified": "2026-07-29T00:00:00Z",
        }
    ]
    assert result["annotation_count"] == 1
    assert result["attachments"] == [
        {
            "key": "ATTACH01",
            "title": "Full Text PDF",
            "filename": "paper.pdf",
            "annotations": [
                {
                    "key": "ANNOT001",
                    "type": "highlight",
                    "text": "Bandwidth choice matters.",
                    "comment": "Compare with placebo.",
                    "color": "#ffd400",
                    "page_label": "12",
                    "sort_index": "00012|000001",
                    "tags": ["identification"],
                    "date_modified": "2026-07-29T00:01:00Z",
                }
            ],
        }
    ]
    assert {request.method for request in requests} == {"GET"}


def test_notes_and_annotations_rejects_invalid_item_key(zotero_module):
    with zotero_module.LocalZotero(
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"Unexpected request: {request.url}")
        )
    ) as client, pytest.raises(ValueError, match="item key"):
        client.notes_and_annotations("../secret")


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
    assert result["selection_mode"] == "query-ranked"
    assert result["parser"] == "pypdf"
    assert result["fallback_pages"] == []


def test_extract_pdf_without_query_returns_leading_pages(
    zotero_module,
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class Page:
        def __init__(self, text: str, *, should_fail: bool = False):
            self.text = text
            self.should_fail = should_fail

        def extract_text(self) -> str:
            if self.should_fail:
                raise AssertionError("A trailing page should not be extracted")
            return self.text

    class Reader:
        pages = [
            Page("Cover page."),
            Page("Abstract and introduction."),
            Page("Methods.", should_fail=True),
        ]

    monkeypatch.setattr(zotero_module, "PdfReader", lambda _: Reader())

    result = zotero_module.extract_pdf(pdf, max_pages=2)

    assert result["selection_mode"] == "leading-pages"
    assert result["query"] is None
    assert result["matched_pages"] is None
    assert [page["page"] for page in result["pages"]] == [1, 2]


def test_extract_pdf_uses_pymupdf_for_nearly_empty_page(
    zotero_module,
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "cjk-paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class PrimaryPage:
        def extract_text(self) -> str:
            return "?"

    class Reader:
        pages = [PrimaryPage()]

    class FallbackPage:
        def get_text(self, mode: str) -> str:
            assert mode == "text"
            return "近藤絢子：日本勞動市場的實證結果。"

    class Document:
        def __len__(self) -> int:
            return 1

        def load_page(self, page_index: int) -> FallbackPage:
            assert page_index == 0
            return FallbackPage()

        def close(self) -> None:
            pass

    class PyMuPDF:
        @staticmethod
        def open(path: str) -> Document:
            assert path == str(pdf)
            return Document()

    monkeypatch.setattr(zotero_module, "PdfReader", lambda _: Reader())
    monkeypatch.setattr(zotero_module, "pymupdf", PyMuPDF())

    result = zotero_module.extract_pdf(pdf, max_pages=1)

    assert result["pages"][0]["text"].startswith("近藤絢子")
    assert result["parser"] == "pymupdf"
    assert result["fallback_pages"] == [1]
    assert any("PyMuPDF" in warning for warning in result["warnings"])


def test_extract_pdf_replaces_control_character_garble_with_pymupdf(
    zotero_module,
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "encoded-cjk-paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class PrimaryPage:
        def extract_text(self) -> str:
            return "RIETI IUUQT\x1b\x10XXX\x0fSJFUJ encoded title"

    class Reader:
        pages = [PrimaryPage()]

    class FallbackPage:
        def get_text(self, mode: str) -> str:
            assert mode == "text"
            return "市町村税務データを用いた既婚女性の就労調整の分析"

    class Document:
        def __len__(self) -> int:
            return 1

        def load_page(self, page_index: int) -> FallbackPage:
            assert page_index == 0
            return FallbackPage()

        def close(self) -> None:
            pass

    class PyMuPDF:
        @staticmethod
        def open(path: str) -> Document:
            assert path == str(pdf)
            return Document()

    monkeypatch.setattr(zotero_module, "PdfReader", lambda _: Reader())
    monkeypatch.setattr(zotero_module, "pymupdf", PyMuPDF())

    result = zotero_module.extract_pdf(pdf, max_pages=1)

    assert result["pages"][0]["text"].startswith("市町村税務")
    assert result["parser"] == "pymupdf"
    assert result["fallback_pages"] == [1]


def test_extract_pdf_uses_pymupdf_when_pypdf_cannot_open(
    zotero_module,
    monkeypatch,
    tmp_path,
):
    pdf = tmp_path / "legacy-paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    class FallbackPage:
        def get_text(self, mode: str) -> str:
            assert mode == "text"
            return "Fallback text from a legacy PDF."

    class Document:
        def __len__(self) -> int:
            return 1

        def load_page(self, page_index: int) -> FallbackPage:
            assert page_index == 0
            return FallbackPage()

        def close(self) -> None:
            pass

    class PyMuPDF:
        @staticmethod
        def open(path: str) -> Document:
            assert path == str(pdf)
            return Document()

    def fail_reader(path: str):
        raise zotero_module.PyPdfError(f"pypdf cannot read {path}")

    monkeypatch.setattr(zotero_module, "PdfReader", fail_reader)
    monkeypatch.setattr(zotero_module, "pymupdf", PyMuPDF())

    result = zotero_module.extract_pdf(pdf, max_pages=1)

    assert result["pages"][0]["text"] == "Fallback text from a legacy PDF."
    assert result["parser"] == "pymupdf"
    assert result["fallback_pages"] == [1]


def test_extract_pdf_rejects_blank_query_and_warns_when_nothing_matches(
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


def test_cli_exposes_collections_and_optional_extract_query(zotero_module):
    parser = zotero_module.build_parser()

    collections_args = parser.parse_args(["collections"])
    annotations_args = parser.parse_args(["annotations", "PAPER001"])
    extract_args = parser.parse_args(
        ["extract", "paper.pdf", "--max-pages", "2"]
    )

    assert collections_args.command == "collections"
    assert annotations_args.command == "annotations"
    assert annotations_args.item_key == "PAPER001"
    assert extract_args.command == "extract"
    assert extract_args.query is None


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


def test_main_reports_unreadable_pdf_as_json(
    zotero_module,
    monkeypatch,
    tmp_path,
    capsys,
):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a PDF")
    monkeypatch.setattr(zotero_module, "pymupdf", None)
    monkeypatch.setattr(zotero_module, "_PYMUPDF_IMPORT_ATTEMPTED", True)

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
    assert "collections" in text
    assert "annotations" in text
    assert "PyMuPDF" in text
    assert "Do not use `find`" in text
    assert "decoded `path`" in text


def test_readme_lists_query_zotero_library():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### `query-zotero-library`" in readme
    assert "macOS, Windows, and Linux" in readme
    assert "Web API keys" in readme
    assert "SQLite" in readme
