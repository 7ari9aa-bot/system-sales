"""R1 — the desktop team consumes the PUBLISHED schema, pinned here.

``desktop/openapi.lock.json`` is a committed export of ``create_app().openapi()``
with the counts and SHA-256 the export measured. This file is the drift gate the
architecture review's C-D2 promised: any route change that does not come with a
regenerated lock fails here, in the same job that runs the rest of the suite —
no separate CI surface to forget.

The measurement logic lives in ``app/core/openapi_lock.py`` so the gate measures
with the exact code that produced the file. ``typed_operations`` is a ratchet —
it may only grow, so stripping a ``response_model`` fails even when the lock was
regenerated.
"""

from __future__ import annotations

import json

from app.core.openapi_lock import (
    LOCK_PATH,
    TYPED_FLOOR,
    canonical_json,
    regenerate_lock_document,
)


def test_the_committed_lock_matches_the_live_schema() -> None:
    assert LOCK_PATH.exists(), (
        "desktop/openapi.lock.json is missing — run "
        "`python scripts/export_openapi_lock.py` and commit the result"
    )
    committed = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    fresh = regenerate_lock_document()

    assert committed["measured"]["sha256"] == fresh["measured"]["sha256"], (
        "the published schema drifted from the committed lock — regenerate it "
        "with `python scripts/export_openapi_lock.py` and commit"
    )
    assert committed["spec"] == fresh["spec"], "lock spec drifts from the live schema"
    assert committed["measured"]["operations"] == fresh["measured"]["operations"]
    # The bytes are canonical, so lock diffs read as schema diffs.
    assert LOCK_PATH.read_text(encoding="utf-8") == canonical_json(committed)


def test_typed_route_coverage_never_shrinks() -> None:
    committed = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    typed = committed["measured"]["typed_operations"]
    assert typed >= TYPED_FLOOR, (
        f"typed operations fell to {typed} (floor {TYPED_FLOOR}) — a "
        "response_model was removed or a new route shipped untyped"
    )
