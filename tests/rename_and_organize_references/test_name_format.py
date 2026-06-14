from __future__ import annotations

import pytest

METADATA = {
    "title": "A Study of Things",
    "year": 2020,
    "authors": [{"display_name": "John Smith", "family_name": "Smith"}],
}


def test_default_format_preserves_existing_behavior(rename_module):
    name = rename_module.build_filename(METADATA, kind="main-paper")
    assert name == "Smith_2020_A_Study_of_Things.pdf"


def test_kebab_lowercase_template(rename_module):
    fmt = rename_module.NameFormat(
        template="{authors}-{year}-{title}{suffix}{ext}",
        transform="kebab-case",
        separator="-",
    )
    name = rename_module.build_filename(METADATA, kind="main-paper", fmt=fmt)
    assert name == "smith-2020-a-study-of-things.pdf"


def test_snake_case_lowercase(rename_module):
    fmt = rename_module.NameFormat(transform="snake_case")
    name = rename_module.build_filename(METADATA, kind="main-paper", fmt=fmt)
    assert name == "smith_2020_a_study_of_things.pdf"


def test_kebab_with_appendix_suffix(rename_module):
    fmt = rename_module.NameFormat(
        template="{authors}-{year}-{title}{suffix}{ext}",
        transform="kebab-case",
        separator="-",
    )
    name = rename_module.build_filename(METADATA, kind="appendix", fmt=fmt)
    assert name == "smith-2020-a-study-of-things-appendix.pdf"


def test_invalid_transform_rejected(rename_module):
    with pytest.raises(ValueError):
        rename_module.NameFormat(transform="bogus-case")


def test_custom_template_max_length_truncation(rename_module):
    metadata = {
        "title": "A Very Long Title That Will Need To Be Truncated Quite A Bit",
        "year": 2020,
        "authors": [{"display_name": "John Smith", "family_name": "Smith"}],
    }
    fmt = rename_module.NameFormat(
        template="{authors}-{year}-{title}{ext}",
        transform="kebab-case",
        separator="-",
    )
    name = rename_module.build_filename(
        metadata, kind="main-paper", max_length=30, fmt=fmt
    )
    assert len(name) <= 30
    assert name.startswith("smith-2020-")
    assert name.endswith(".pdf")
