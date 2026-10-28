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
