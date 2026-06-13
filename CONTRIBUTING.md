# Contributing Guide

Welcome to the `social-science-research-skills` repository! This project heavily utilizes AI agents for development. Whether you are a human or an AI, you must strictly follow the development and release protocols outlined below.

## 1. Development & Testing Workflow

This repository relies on Agentic CI/CD. Do not manually hack skill scripts without running tests.

- **Use the Engine**: For major modifications, use the built-in `implement-review-fix-workflow` skill to orchestrate an automated Maker/Checker development loop.
- **Testing**: Run `python -m pytest` before considering any task complete. Tests are located in the `tests/` directory.
- **Linting**: Ensure code complies with formatting rules by running `python -m ruff check .`.
- **Zero-Trust for Dependencies**: Always favor graceful degradation if external skills (e.g., OpenAlex) are unavailable. Fail gracefully instead of crashing.

## 2. Release SOP (Standard Operating Procedure)

We strictly follow [Semantic Versioning (SemVer)](https://semver.org/). Version numbers should only be bumped when explicitly deciding to "cut a release."

When instructed to cut a release, follow these exact 4 steps in order:

1. **Determine the new Version**: 
   - `PATCH` (e.g., 0.1.1) for bugfixes.
   - `MINOR` (e.g., 0.2.0) for new backwards-compatible features.
   - `MAJOR` (e.g., 1.0.0) for breaking changes.
2. **Update Configuration**: Update the `version = "X.Y.Z"` field in `pyproject.toml`.
3. **Write the Changelog**: Prepend a new section to `CHANGELOG.md` following the format `## [X.Y.Z] - YYYY-MM-DD`. Categorize changes under `### Added`, `### Changed`, `### Fixed`, or `### Removed`.
4. **Commit & Tag**: 
   - Commit the changes with the message: `chore: release vX.Y.Z`.
   - Push the commit to the `main` branch.
   - Create a Git Tag and a GitHub Release (e.g., using `gh release create vX.Y.Z --notes-file CHANGELOG.md`).
