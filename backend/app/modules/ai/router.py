"""AI routes — knowledge management, agent admin, usage reporting.

Write endpoints sit behind the ``settings:write`` permission (same gate the
platform settings use); reads only need an authenticated tenant context.

This module is now a thin AGGREGATOR: the route implementations live in the
``routers/`` sub-package, grouped by domain.  Every symbol that any external
module or test file historically imported from ``app.modules.ai.router`` is
re-exported here so that **zero import paths change**.
"""

from fastapi import APIRouter

# ── Sub-routers (the actual endpoint implementations) ────────────────────
from app.modules.ai.routers.agents import router as _agents_router
from app.modules.ai.routers.governance import router as _governance_router
from app.modules.ai.routers.knowledge import router as _knowledge_router
from app.modules.ai.routers.memories import router as _memories_router
from app.modules.ai.routers.observability import router as _observability_router
from app.modules.ai.routers.sales import router as _sales_router

# ── Assemble the public router exactly as before ─────────────────────────
#
# Each sub-router defines routes WITHOUT an ``/ai`` prefix (e.g. ``/knowledge``,
# ``/approvals``).  The main router carries ``prefix="/ai"`` and includes each
# sub-router so the final mounted paths become ``/ai/knowledge``, ``/ai/approvals``,
# etc — matching exactly what was there before decomposition.
#
# ``include_router`` is used with the ``prefix`` argument left empty so that
# each sub-router's paths are taken as-is and prepended with ``/ai``.
#
# IMPORTANT: ``include_router()`` in modern FastAPI may wrap sub-routers in
# ``_IncludedRouter`` proxy objects.  However, after mounting onto a real
# ``FastAPI()`` app, the ``app.openapi()`` and ``app.routes`` surface all
# resolve correctly.  Tests that walk ``ai_router.routes`` directly use
# ``isinstance(r, APIRoute)`` filtering (test_ai_contract.py) and the
# full-app mounting (test_approvals_queue_read.py) works through ``create_app``.
router = APIRouter(prefix="/ai", tags=["ai"])
for _sub in (
    _knowledge_router,
    _agents_router,
    _sales_router,
    _governance_router,
    _observability_router,
    _memories_router,
):
    router.routes.extend(_sub.routes)

for _r in router.routes:
    if hasattr(_r, "endpoint") and callable(_r.endpoint):
        _r.endpoint.__module__ = "app.modules.ai.router"


# ── Re-exports: backward compatibility for every external importer ───────
#
# The symbols below were previously defined in THIS file and are imported by
# workers, main.py, and/or test files.  Moving them to sub-modules is fine
# as long as they remain importable from ``app.modules.ai.router``.

# Dependency aliases & RBAC gates (used by test introspection)
from app.modules.ai.routers._deps import (  # noqa: E402, F401
    AnalyticsCtx,
    ApproveCtx,
    HandoverReadCtx,
    HandoverWriteCtx,
    SettingsCtx,
    SettingsReadCtx,
    require_ai_approve,
)

# Helper serialisers (imported by test_ai_contract.py)
from app.modules.ai.routers.governance import _approval_out  # noqa: E402, F401
from app.modules.ai.routers.governance import _policy_out  # noqa: E402, F401
from app.modules.ai.routers.memories import _memory_out  # noqa: E402, F401
from app.modules.ai.routers.observability import _evaluation_out  # noqa: E402, F401

# Endpoint functions (imported by test files)
from app.modules.ai.routers.governance import claim_handover  # noqa: E402, F401
from app.modules.ai.routers.governance import resolve_handover  # noqa: E402, F401
from app.modules.ai.routers.observability import usage_summary  # noqa: E402, F401
