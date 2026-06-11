from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "literature-search-repec"


def load_script(name: str):
    path = SKILL / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_script_with_blocked_import(name: str, blocked: str):
    script = (SKILL / "scripts" / name).as_posix()
    code = textwrap.dedent(
        f"""
        from __future__ import annotations

        import importlib.abc
        import runpy
        import sys


        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == {blocked!r} or fullname.startswith({blocked!r} + "."):
                    raise ImportError("blocked", name={blocked!r})
                return None


        sys.meta_path.insert(0, Blocker())
        runpy.run_path({script!r}, run_name="__main__")
        """
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class StatusErrorResponse:
    text = "server error"

    def raise_for_status(self) -> None:
        request = httpx.Request("GET", "https://ideas.repec.org/example")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("server error", request=request, response=response)


class XmlResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_search_handles_http_status_errors_as_json(monkeypatch, capsys):
    search_repec = load_script("search_repec.py")
    monkeypatch.setattr(
        search_repec.httpx,
        "post",
        lambda *args, **kwargs: StatusErrorResponse(),
    )

    exit_code = search_repec.search_ideas_repec("tax incidence")

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_search_main_returns_failure_without_required_input(capsys):
    search_repec = load_script("search_repec.py")

    exit_code = search_repec.main([])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_search_argparse_errors_are_json(capsys):
    search_repec = load_script("search_repec.py")

    with pytest.raises(SystemExit) as exc_info:
        search_repec.main(["tax", "--limit", "not-a-number"])

    assert exc_info.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_search_missing_dependency_errors_are_json():
    result = run_script_with_blocked_import("search_repec.py", "bs4")

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output == {"error": "Missing dependency: bs4"}
    assert "Traceback" not in result.stderr


def test_get_citations_handles_http_status_errors_as_json(monkeypatch, capsys):
    get_citations = load_script("get_citations.py")
    monkeypatch.setattr(
        get_citations.httpx,
        "get",
        lambda *args, **kwargs: StatusErrorResponse(),
    )

    exit_code = get_citations.get_citations("RePEc:nbr:nberwo:35310")

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_get_citations_returns_failure_for_citec_error(monkeypatch, capsys):
    get_citations = load_script("get_citations.py")
    monkeypatch.setattr(
        get_citations.httpx,
        "get",
        lambda *args, **kwargs: XmlResponse(
            "<errorString>invalid handle</errorString>"
        ),
    )

    exit_code = get_citations.get_citations("RePEc:bad")

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {"error": "invalid handle"}


def test_get_citations_argparse_errors_are_json(capsys):
    get_citations = load_script("get_citations.py")

    with pytest.raises(SystemExit) as exc_info:
        get_citations.main([])

    assert exc_info.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_get_citations_missing_dependency_errors_are_json():
    result = run_script_with_blocked_import("get_citations.py", "httpx")

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert "httpx is not installed" in output["error"]
    assert "Traceback" not in result.stderr


def test_get_citations_returns_failure_for_nonnumeric_counts(monkeypatch, capsys):
    get_citations = load_script("get_citations.py")
    monkeypatch.setattr(
        get_citations.httpx,
        "get",
        lambda *args, **kwargs: XmlResponse(
            "<citationData><citedBy>many</citedBy><cites>1</cites></citationData>"
        ),
    )

    exit_code = get_citations.get_citations("RePEc:nbr:nberwo:35310")

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert "error" in output
