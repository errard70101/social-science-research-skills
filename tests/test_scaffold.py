from __future__ import annotations


def test_rename_cli_parser_loads(rename_module):
    assert rename_module.build_parser().prog


def test_installer_cli_parser_loads(install_module):
    assert install_module.build_parser().prog
