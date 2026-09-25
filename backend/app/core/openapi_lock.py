"""The published schema, measured — the shared core of the R1 drift gate.

``desktop/openapi.lock.json`` is the committed export of ``create_app().openapi()``
with the counts the export measured. Both consumers of that file — the drift gate
``tests/test_openapi_lock.py`` and the export tool ``scripts/export_openapi_lock.py``
— measure through this module, so the gate verifies the file with the exact code
that produced it. The counts come from the published schema, never from grepping
decorators (DESKTOP_ARCH_REVIEW.md C-D2).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "desktop" / "openapi.lock.json"

# Measured when the lock was introduced (245 operations, 112 publishing a 2xx
# schema — DESKTOP_ARCH_REVIEW.md C-D2). ``typed_operations`` is a ratchet: it
# may only grow, so stripping a response_model fails even after a regeneration.
TYPED_FLOOR = 112

_HTTP_OPERATION_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def canonical_json(spec: dict) -> str:
    """The one byte form a lock may hold, so schema diffs read as schema diffs."""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def measure_spec(spec: dict) -> dict:
    """Counts over the published schema: operations, typed operations, sha256."""
    typed = 0
    operations = 0
    for item in spec.get("paths", {}).values():
        for method, op in item.items():
            if method not in _HTTP_OPERATION_METHODS:
                continue
            operations += 1
            responses = op.get("responses", {})
            if any(str(code).startswith("2") for code in responses):
                body = responses[next(c for c in responses if str(c).startswith("2"))]
                if (body.get("content") or {}).get("application/json", {}).get("schema"):
                    typed += 1
    return {
        "operations": operations,
        "typed_operations": typed,
        "sha256": hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest(),
    }


def build_lock_document(spec: dict) -> dict:
    return {"measured": measure_spec(spec), "spec": spec}


def regenerate_lock_document() -> dict:
    """Build a lock document from the LIVE application schema."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    os.environ.setdefault("ENVIRONMENT", "local")
    from app.main import create_app

    return build_lock_document(create_app().openapi())
