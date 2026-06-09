from __future__ import annotations

import pytest


def _valid_content() -> dict:
    return {
        "schema_version": 1,
        "paper": {
            "authors": ["Acemoglu, Daron", "Johnson, Simon"],
            "year": 2001,
            "title": "Colonial Origins",
            "venue": "American Economic Review",
            "citation_key": "acemoglu2001colonial",
        },
        "one_sentence": "Institutions shape long-run income.",
        "setup": "We study cross-country differences.",
        "empirical_strategy": "Two-stage least squares.",
        "identification_cartoon": "Compare colonies that differed only in mortality.",
        "headline_visual": {"kind": "none"},
        "key_result": "Institutions matter a lot.",
        "placement_in_literature": "Builds on North (1990).",
        "predecessor_citations": [],
        "limitations": "Settler mortality data is contested.",
        "followups": "Test mechanisms in modern panel data.",
    }


def test_valid_content_passes_validation(summary_module):
    summary_module.validate_content(_valid_content())


def test_missing_section_raises(summary_module):
    content = _valid_content()
    del content["empirical_strategy"]
    with pytest.raises(ValueError) as exc:
        summary_module.validate_content(content)
    assert "empirical_strategy" in str(exc.value)


def test_empty_section_raises(summary_module):
    content = _valid_content()
    content["setup"] = "  "
    with pytest.raises(ValueError) as exc:
        summary_module.validate_content(content)
    assert "setup" in str(exc.value)


def test_predecessor_entry_requires_key(summary_module):
    content = _valid_content()
    content["predecessor_citations"] = [{"prose_hint": "North (1990)"}]
    with pytest.raises(ValueError) as exc:
        summary_module.validate_content(content)
    assert "key" in str(exc.value)


def test_visual_table_mode_requires_latex(summary_module):
    content = _valid_content()
    content["headline_visual"] = {"kind": "table"}
    with pytest.raises(ValueError) as exc:
        summary_module.validate_content(content)
    assert "latex_table" in str(exc.value)


def test_visual_image_mode_requires_label_and_page(summary_module):
    content = _valid_content()
    content["headline_visual"] = {"kind": "image"}
    with pytest.raises(ValueError) as exc:
        summary_module.validate_content(content)
    assert "label" in str(exc.value)


def test_unknown_visual_kind_raises(summary_module):
    content = _valid_content()
    content["headline_visual"] = {"kind": "graph"}
    with pytest.raises(ValueError):
        summary_module.validate_content(content)
