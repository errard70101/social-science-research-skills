# Manage LaTeX Bibliography Audit Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the new "Mode Selection" prompt in `SKILL.md` and add an `audit` subcommand to `manage_bibliography.py` that syncs existing `.bib` entries with local PDFs or enforces a strict initialization.

**Architecture:** 
1. Rewrite `SKILL.md` Step 1 to present the 4 modes.
2. Add `--audit` CLI capabilities to `manage_bibliography.py` which scans the `references/` directory for existing citation keys, emitting missing matches into the `unresolved` JSON list.
3. Use Test-Driven Development by first asserting the CLI parser, then testing the `build_audit_proposal` logic, and finally implementing it.

**Tech Stack:** Python 3.10+, argparse, json, pytest

---

### Task 1: Update SKILL.md

**Files:**
- Modify: `skills/manage-latex-bibliography/SKILL.md`

- [ ] **Step 1: Replace Workflow Step 1-3 with Mode Selection**

Modify the file manually or using tools. Replace the `## Workflow` section (around lines 8-18) to match the new design:

```markdown
## Workflow

1. **STOP AND ASK THE USER:** "請問您這次需要執行哪一種文獻管理模式？請選擇："
   - **0. Initialize (首次深度健檢)**: Forces every `.bib` entry to be verified online. (Command: `audit --all`)
   - **1. Scan (文獻補漏)**: Checks `.tex` vs `.bib` for missing keys. (Command: `scan`)
   - **2. Audit (日常 PDF 雙向稽核)**: Checks `.bib` vs `references/` for missing PDFs. (Command: `audit`)
   - **3. Update (單點強制更新)**: Forces update on a specific key. (Command: `update-entry`)
2. Confirm the project root, the main `.tex` file, or the `references.bib` file.
3. Locate this skill directory and assign its absolute path to `SKILL_DIR`.
4. Based on the selected mode, generate the proposal without modifying the project:

   **Mode 1 (Scan):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" scan \
     --project /path/to/project \
     --output /path/to/project/bibliography-proposal.json
   ```

   **Mode 0 & 2 (Audit / Initialize):**
   ```bash
   python "$SKILL_DIR/scripts/manage_bibliography.py" audit \
     --bib /path/to/project/references.bib \
     --pdf-dir /path/to/project/references \
     --output /path/to/project/bibliography-proposal.json \
     [--all]  # Include --all for Mode 0 Initialize
   ```
```

- [ ] **Step 2: Update Step numbers**
Ensure the rest of the workflow numbering continues correctly (e.g. Step 4 becomes Step 5).

- [ ] **Step 3: Commit**
```bash
git add skills/manage-latex-bibliography/SKILL.md
git commit -m "docs: update SKILL.md with 4-mode workflow and audit command"
```

### Task 2: Test the CLI Parser for Audit

**Files:**
- Modify: `tests/test_scaffold.py`

- [ ] **Step 1: Add audit to expected commands**

In `tests/test_scaffold.py`, locate the test `test_manage_bibliography_subcommands`.

```python
def test_manage_bibliography_subcommands():
    # ... code ...
    expected = {"scan", "validate", "apply", "approve", "update-entry", "install-aea-style", "audit"}
    # ... code ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n benchmark pytest tests/test_scaffold.py -k test_manage_bibliography_subcommands -v`
Expected: FAIL because `audit` is not in the subparsers.

- [ ] **Step 3: Add audit parser to manage_bibliography.py**

In `skills/manage-latex-bibliography/scripts/manage_bibliography.py`, inside `build_parser()`:

```python
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--bib", type=Path, required=True)
    audit_parser.add_argument("--pdf-dir", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    audit_parser.add_argument("--all", action="store_true")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n benchmark pytest tests/test_scaffold.py -k test_manage_bibliography_subcommands -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_scaffold.py skills/manage-latex-bibliography/scripts/manage_bibliography.py
git commit -m "feat: add audit subcommand to CLI"
```

### Task 3: Test `build_audit_proposal` Logic

**Files:**
- Modify: `tests/manage_latex_bibliography/test_proposal.py`
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Write the failing test**

In `tests/manage_latex_bibliography/test_proposal.py`, add the test:

```python
def test_build_audit_proposal(tmp_path: Path):
    from manage_bibliography import build_audit_proposal

    bib_file = tmp_path / "references.bib"
    bib_file.write_text(
        "@article{smith2024test,\n"
        "  title={Test Title},\n"
        "  author={Smith, John},\n"
        "  year={2024}\n"
        "}\n"
        "@article{doe2023test,\n"
        "  title={Another Test},\n"
        "  author={Doe, Jane},\n"
        "  year={2023}\n"
        "}",
        encoding="utf-8"
    )

    pdf_dir = tmp_path / "references"
    pdf_dir.mkdir()
    # Create PDF for Smith but not for Doe
    (pdf_dir / "Smith_2024_Test_Title.pdf").touch()

    proposal = build_audit_proposal(bib_file, pdf_dir, strict_all=False)
    
    assert proposal["schema_version"] == 1
    assert proposal["target_bib"] == "references.bib"
    assert len(proposal["unresolved"]) == 1
    assert proposal["unresolved"][0]["source"] == "doe2023test"
    assert proposal["unresolved"][0]["reason"] == "PDF not found or mismatch"

    # Test strict_all
    proposal_all = build_audit_proposal(bib_file, pdf_dir, strict_all=True)
    assert len(proposal_all["unresolved"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n benchmark pytest tests/manage_latex_bibliography/test_proposal.py::test_build_audit_proposal -v`
Expected: FAIL with ImportError or NameError since `build_audit_proposal` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

In `skills/manage-latex-bibliography/scripts/manage_bibliography.py`, add the `build_audit_proposal` function before `def build_scan_proposal(...)`:

```python
import hashlib

def build_audit_proposal(bib_path: Path, pdf_dir: Path, strict_all: bool = False) -> dict[str, object]:
    content = ""
    if bib_path.is_file():
        content = bib_path.read_text(encoding="utf-8")
    entries = parse_bibtex_entries(content)
    
    unresolved = []
    
    pdf_files = [f.name for f in pdf_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"] if pdf_dir.is_dir() else []

    for entry in entries:
        key = str(entry.get("key", ""))
        if not key:
            continue
            
        if strict_all:
            unresolved.append({"source": key, "reason": "Strict initialization check"})
            continue
            
        # Basic matching: check if citation key is in any PDF name
        found = False
        for pdf in pdf_files:
            if key.lower() in pdf.lower():
                found = True
                break
            # Fallback fuzzy match (Author_Year format)
            fields = entry.get("fields", {})
            year = str(fields.get("year", ""))
            author_field = str(fields.get("author", ""))
            if year and author_field:
                first_author = author_field.split(",")[0].split(" ")[-1]
                if first_author.lower() in pdf.lower() and year in pdf:
                    found = True
                    break
                    
        if not found:
            unresolved.append({"source": key, "reason": "PDF not found or mismatch"})

    return {
        "schema_version": 1,
        "project_root": str(bib_path.parent.absolute()),
        "main_tex": "",
        "target_bib": bib_path.name,
        "file_digests": {
            bib_path.name: hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        },
        "citations": [],
        "tex_changes": [],
        "new_entries": [],
        "existing_entry_corrections": [],
        "unresolved": unresolved,
        "warnings": [],
        "bibliography_system": "bibtex",
        "verification_report": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n benchmark pytest tests/manage_latex_bibliography/test_proposal.py::test_build_audit_proposal -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/manage_latex_bibliography/test_proposal.py skills/manage-latex-bibliography/scripts/manage_bibliography.py
git commit -m "feat: implement build_audit_proposal logic and tests"
```

### Task 4: Hook Audit Command into Main

**Files:**
- Modify: `skills/manage-latex-bibliography/scripts/manage_bibliography.py`

- [ ] **Step 1: Add audit handling to main()**

In `skills/manage-latex-bibliography/scripts/manage_bibliography.py`, inside `main()` around line 1570:

```python
    if args.command == "scan":
        proposal = build_scan_proposal(args.project)
        args.output.write_text(
            json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif args.command == "audit":
        proposal = build_audit_proposal(args.bib, args.pdf_dir, args.all)
        args.output.write_text(
            json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif args.command == "validate":
```

- [ ] **Step 2: Verify linting**

Run: `conda run -n benchmark ruff check skills/manage-latex-bibliography/scripts/manage_bibliography.py`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `conda run -n benchmark pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add skills/manage-latex-bibliography/scripts/manage_bibliography.py
git commit -m "feat: wire audit subcommand to main execution"
```
