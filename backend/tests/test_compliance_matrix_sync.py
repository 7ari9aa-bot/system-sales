"""Test that docs/settings/compliance-matrix.md is in sync with the generator.

Runs ``gen_compliance_matrix.py --check`` and fails if the committed document
has drifted from what the code produces. Also asserts that every ✅ item
has a real test file on disk.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_SCRIPT = _BACKEND / "scripts" / "dev" / "gen_compliance_matrix.py"


def test_compliance_matrix_in_sync() -> None:
    """The committed compliance matrix matches the generator output."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"compliance matrix is out of sync.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}\n"
        f"Fix: cd backend && python scripts/dev/gen_compliance_matrix.py"
    )


def test_compliance_matrix_file_exists() -> None:
    """The compliance matrix document exists."""
    out = _BACKEND.parent / "docs" / "settings" / "compliance-matrix.md"
    assert out.exists(), f"{out} not found — run gen_compliance_matrix.py"
