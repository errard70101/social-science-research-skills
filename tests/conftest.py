from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.fixture(scope="session")
def rename_module() -> ModuleType:
    return load_script(
        "rename_references",
        REPO_ROOT
        / "skills"
        / "rename-and-organize-references"
        / "scripts"
        / "rename_references.py",
    )


@pytest.fixture(scope="session")
def install_module() -> ModuleType:
    return load_script("install_skills", REPO_ROOT / "scripts" / "install.py")
