from __future__ import annotations


def _write_skill(root, name, *, requires=None, capabilities=None):
    skill = root / "skills" / name
    skill.mkdir(parents=True)
    lines = ["---", f"name: {name}", "description: Use when testing."]
    if requires:
        lines.append("requires: [" + ", ".join(requires) + "]")
    if capabilities:
        lines.append("capabilities: [" + ", ".join(capabilities) + "]")
    lines.append("---")
    (skill / "SKILL.md").write_text("\n".join(lines) + "\n")
    return skill


def test_parse_frontmatter_parses_inline_list(install_module, tmp_path):
    skill = _write_skill(
        tmp_path, "alpha", requires=["beta", "gamma"], capabilities=["search"]
    )
    metadata = install_module.parse_frontmatter(skill / "SKILL.md")
    assert metadata["requires"] == ["beta", "gamma"]
    assert metadata["capabilities"] == ["search"]
    assert metadata["name"] == "alpha"


def test_discover_capabilities_groups_providers(install_module, tmp_path):
    _write_skill(tmp_path, "alpha", capabilities=["search"])
    _write_skill(tmp_path, "bravo", capabilities=["search"])
    _write_skill(tmp_path, "charlie")
    providers = install_module.discover_capabilities(tmp_path / "skills")
    assert providers == {"search": ["alpha", "bravo"]}


def test_resolve_dependencies_pulls_in_direct_skill(install_module, tmp_path):
    _write_skill(tmp_path, "lib")
    parent = _write_skill(tmp_path, "parent", requires=["lib"])
    expanded, warnings = install_module.resolve_dependencies(
        [parent], tmp_path / "skills"
    )
    assert [p.name for p in expanded] == ["lib", "parent"]
    assert warnings == []


def test_resolve_dependencies_picks_capability_provider(install_module, tmp_path):
    _write_skill(tmp_path, "search-a", capabilities=["search"])
    parent = _write_skill(tmp_path, "parent", requires=["search"])
    expanded, warnings = install_module.resolve_dependencies(
        [parent], tmp_path / "skills"
    )
    assert "search-a" in {p.name for p in expanded}
    assert warnings == []


def test_resolve_dependencies_warns_on_missing_capability(install_module, tmp_path):
    parent = _write_skill(tmp_path, "parent", requires=["search"])
    expanded, warnings = install_module.resolve_dependencies(
        [parent], tmp_path / "skills"
    )
    assert [p.name for p in expanded] == ["parent"]
    assert len(warnings) == 1
    assert "graceful-degradation" in warnings[0]


def test_resolve_dependencies_is_idempotent_when_provider_preselected(
    install_module, tmp_path
):
    provider = _write_skill(tmp_path, "search-a", capabilities=["search"])
    parent = _write_skill(tmp_path, "parent", requires=["search"])
    expanded, warnings = install_module.resolve_dependencies(
        [parent, provider], tmp_path / "skills"
    )
    assert sorted(p.name for p in expanded) == ["parent", "search-a"]
    assert warnings == []
