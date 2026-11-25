"""Fail CI if ``docs/settings/registry-specification.md`` is out of sync with the code.

The registry is the single source of truth. A hand-edited doc drifts silently;
this test regenerates the document in-memory and compares it to the committed
file, so a PR that changes ``registry.py`` without regenerating the spec is
caught at CI time.

Run ``python scripts/dev/gen_registry_spec.py`` to regenerate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_SPEC = _REPO / "docs" / "settings" / "registry-specification.md"


def test_registry_spec_in_sync() -> None:
    """The committed registry-specification.md must match what the code generates."""
    result = subprocess.run(
        [sys.executable, str(_BACKEND / "scripts" / "dev" / "gen_registry_spec.py"), "--check"],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"registry-specification.md is out of sync with registry.py.\n"
        f"Run: python scripts/dev/gen_registry_spec.py\n\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
