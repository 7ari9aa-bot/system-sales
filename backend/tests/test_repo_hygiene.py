"""Keep the repository organised: a stale index or a personal path is a test failure.

Three things drifted before this existed: docs were added without being listed anywhere,
helper scripts sat in backend/ root with another developer's Windows paths hard-coded, and
two token guides held real credentials. These checks make the cheap ones permanent.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True)
    return [p for p in out.stdout.decode().split("\0") if p]


def test_every_top_level_doc_is_in_the_docs_index() -> None:
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    missing = [
        p.name
        for p in sorted(DOCS.glob("*.md"))
        if p.name != "README.md" and f"({p.name})" not in index
    ]
    assert not missing, f"add these to docs/README.md: {missing}"


def test_docs_index_links_all_resolve() -> None:
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    broken = [
        t
        for t in re.findall(r"\]\(([^)#]+)\)", index)
        if not t.startswith("http") and not (DOCS / t).exists()
    ]
    assert not broken, f"docs/README.md links to missing paths: {broken}"


def test_backend_root_holds_only_project_files() -> None:
    """Helper scripts belong in backend/scripts/, not next to pyproject.toml."""
    stray = [
        p
        for p in _tracked()
        if p.startswith("backend/")
        and p.count("/") == 1
        and p.endswith((".sh", ".bat", ".ps1", ".log", ".bak"))
    ]
    assert not stray, f"move these into backend/scripts/: {stray}"


def test_no_script_hardcodes_a_personal_machine_path() -> None:
    """A script that only runs from one developer's drive letter is broken for everyone else."""
    pattern = re.compile(r"""["']?[A-Za-z]:[/\\](?:Users|sales system)[/\\]""")
    offenders: list[str] = []
    for rel in _tracked():
        if not rel.endswith((".sh", ".py", ".ps1", ".yml", ".yaml")) or rel.startswith(
            "backend/tests/"
        ):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        offenders += [
            f"{rel}:{i + 1}" for i, ln in enumerate(text.splitlines()) if pattern.search(ln)
        ]
    assert not offenders, f"machine-specific paths: {offenders}"


def test_root_readme_links_resolve() -> None:
    """The first file anyone opens must not point at moved or deleted documents."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    broken = [
        t
        for t in re.findall(r"\]\(([^)#]+)\)", text)
        if not t.startswith("http") and not (REPO / t).exists()
    ]
    assert not broken, f"README.md links to missing paths: {broken}"


def test_root_readme_names_every_backend_module() -> None:
    """A module added without a line in the README is how the layout went stale before."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    modules = REPO / "backend" / "app" / "modules"
    missing = [
        p.name
        for p in sorted(modules.iterdir())
        if p.is_dir() and p.name != "__pycache__" and f"`{p.name}`" not in text
    ]
    assert not missing, f"name these modules in README.md: {missing}"


def _modules() -> list[Path]:
    root = REPO / "backend" / "app" / "modules"
    return [p for p in sorted(root.iterdir()) if p.is_dir() and p.name != "__pycache__"]


def test_every_backend_module_has_a_readme() -> None:
    """A module nobody can orient themselves in is how a 3,000-line file goes unnoticed."""
    missing = [p.name for p in _modules() if not (p / "README.md").exists()]
    assert not missing, f"add a README.md to: {missing}"


def test_module_readmes_only_list_tables_that_exist() -> None:
    """A README that names a table the code no longer has is worse than no README."""
    wrong: list[str] = []
    for mod in _modules():
        readme = mod / "README.md"
        if not readme.exists():
            continue
        code = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in mod.rglob("*.py"))
        section = readme.read_text(encoding="utf-8").split("## Tables", 1)[-1].split("##", 1)[0]
        for table in re.findall(r"^- `([a-z_0-9]+)`", section, re.M):
            if f'"{table}"' not in code and f"'{table}'" not in code:
                wrong.append(f"{mod.name}.{table}")
    assert not wrong, f"README lists tables missing from the code: {wrong}"
