from __future__ import annotations


def test_caption_regex_captures_table_and_figure(summary_module):
    pages = [
        {"page": 4, "text": "Some body.\nTable 1: Summary statistics."},
        {
            "page": 11,
            "text": (
                "Earlier text.\n"
                "Table 3: Main effects of institutions on income.\n"
                "More text."
            ),
        },
        {
            "page": 12,
            "text": "Figure 2: Settler mortality and outcomes.",
        },
    ]

    candidates = summary_module.collect_caption_candidates(pages)

    assert candidates == [
        {
            "label": "Table 1",
            "caption": "Summary statistics.",
            "page": 4,
            "kind": "table",
        },
        {
            "label": "Table 3",
            "caption": "Main effects of institutions on income.",
            "page": 11,
            "kind": "table",
        },
        {
            "label": "Figure 2",
            "caption": "Settler mortality and outcomes.",
            "page": 12,
            "kind": "figure",
        },
    ]


def test_caption_regex_ignores_inline_references(summary_module):
    pages = [
        {
            "page": 1,
            "text": (
                "We refer to Table 1 throughout. "
                "Figure 1 illustrates the design."
            ),
        }
    ]

    assert summary_module.collect_caption_candidates(pages) == []


def test_collect_caption_candidates_expanded_prefixes_and_multiline(summary_module):
    pages = [
        {
            "page": 2,
            "text": (
                "Some body text.\n"
                "Fig. 1: Multi-line figure caption\n"
                "that continues here.\n"
                "Unrelated text starts here."
            )
        },
        {
            "page": 3,
            "text": (
                "Appendix Table A.2: Summary of results.\n"
                "Panel B — Specific details."
            )
        }
    ]
    
    candidates = summary_module.collect_caption_candidates(pages)
    assert candidates == [
        {
            "label": "Figure 1",
            "caption": "Multi-line figure caption that continues here.",
            "page": 2,
            "kind": "figure",
        },
        {
            "label": "Appendix Table A.2",
            "caption": "Summary of results.",
            "page": 3,
            "kind": "table",
        },
        {
            "label": "Panel B",
            "caption": "Specific details.",
            "page": 3,
            "kind": "panel",
        }
    ]

