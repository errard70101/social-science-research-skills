from pathlib import Path


def test_template_safe_defaults():
    template_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "summarize-academic-paper"
        / "references"
        / "template.tex"
    )
    template = template_path.read_text(encoding="utf-8")

    assert "\\setmainfont{Latin Modern Roman}" not in template
    assert "\\bibliographystyle{plainnat}" in template
