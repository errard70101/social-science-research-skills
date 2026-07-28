from __future__ import annotations


def make_skill(root, name="example-skill"):
    skill = root / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing.\n---\n"
    )
    return skill


def test_resolve_targets_deduplicates_shared_agents_directory(install_module, tmp_path):
    home = tmp_path / "home"

    destinations = install_module.resolve_destinations(
        ["codex", "opencode", "copilot"], home=home
    )

    assert destinations == [home / ".agents" / "skills"]


def test_antigravity_uses_current_shared_global_skills_directory(
    install_module,
    tmp_path,
):
    home = tmp_path / "home"

    destinations = install_module.resolve_destinations(
        ["antigravity"],
        home=home,
    )

    assert destinations == [home / ".gemini" / "config" / "skills"]


def test_copy_install_replaces_only_selected_skill(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"
    unrelated = destination / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "SKILL.md").write_text("keep")

    install_module.install_skill(skill, destination, link=False, dry_run=False)

    assert (destination / "example-skill" / "SKILL.md").exists()
    assert (unrelated / "SKILL.md").read_text() == "keep"


def test_copy_install_excludes_python_bytecode_caches(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    scripts = skill / "scripts"
    cache = scripts / "__pycache__"
    cache.mkdir(parents=True)
    (scripts / "runner.py").write_text("print('run')\n")
    (cache / "runner.cpython-312.pyc").write_bytes(b"cached")
    (scripts / "stale.pyc").write_bytes(b"stale")
    (scripts / "stale.pyo").write_bytes(b"optimized")
    destination = tmp_path / "installed"

    install_module.install_skill(skill, destination, link=False, dry_run=False)

    installed_scripts = destination / "example-skill" / "scripts"
    assert (installed_scripts / "runner.py").is_file()
    assert not (installed_scripts / "__pycache__").exists()
    assert not (installed_scripts / "stale.pyc").exists()
    assert not (installed_scripts / "stale.pyo").exists()


def test_link_install_creates_symlink(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"

    install_module.install_skill(skill, destination, link=True, dry_run=False)

    assert (destination / "example-skill").is_symlink()


def test_dry_run_does_not_modify_destination(install_module, tmp_path):
    repo = tmp_path / "repo"
    skill = make_skill(repo)
    destination = tmp_path / "installed"

    install_module.install_skill(skill, destination, link=False, dry_run=True)

    assert not destination.exists()


def test_validate_skill_rejects_mismatched_name(install_module, tmp_path):
    skill = make_skill(tmp_path, name="folder-name")
    (skill / "SKILL.md").write_text(
        "---\nname: different-name\ndescription: Use when testing.\n---\n"
    )

    try:
        install_module.validate_skill(skill)
    except ValueError as error:
        assert "must match" in str(error)
    else:
        raise AssertionError("mismatched skill names must fail")


def test_install_discovers_summary_skill(install_module):
    skills = sorted(install_module.discover_skills())
    assert "rename-and-organize-references" in skills
    assert "summarize-academic-paper" in skills
