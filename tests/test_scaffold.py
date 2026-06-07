from __future__ import annotations

import sys

import pytest
from conftest import load_script


def test_rename_cli_parser_loads(rename_module):
    assert rename_module.build_parser().prog


def test_installer_cli_parser_loads(install_module):
    assert install_module.build_parser().prog


def test_load_script_supports_dataclass_modules(tmp_path):
    script = tmp_path / "dataclass_script.py"
    script.write_text(
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Record:\n"
        "    value: str\n"
    )

    module = load_script("dataclass_script", script)

    assert module.Record("loaded").value == "loaded"


def test_load_script_removes_module_when_execution_fails(tmp_path):
    script = tmp_path / "failing_script.py"
    script.write_text(
        "import sys\n"
        "\n"
        "assert __name__ in sys.modules\n"
        "raise RuntimeError('load failed')\n"
    )

    with pytest.raises(RuntimeError, match="load failed"):
        load_script("failing_script", script)

    assert "failing_script" not in sys.modules


def test_rename_parser_requires_subcommand(rename_module):
    with pytest.raises(SystemExit) as exc_info:
        rename_module.build_parser().parse_args([])

    assert exc_info.value.code != 0


@pytest.mark.parametrize("module_fixture", ["rename_module", "install_module"])
def test_main_accepts_help(module_fixture, request):
    module = request.getfixturevalue(module_fixture)

    with pytest.raises(SystemExit) as exc_info:
        module.main(["--help"])

    assert exc_info.value.code == 0
