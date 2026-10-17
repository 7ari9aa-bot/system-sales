"""PLATFORM routes — feature flags (§76), the metric registry (§167), saved
views (§95), the health indicator (§103), the outbox ledger and the audit
trail (package 2.2 read surfaces), the webhook DLQ (§24) and the security
trail (§67).

Flags are rollout switches, not authorization. The registry is read-only: it
tells every screen what a number means so two screens cannot compute it
differently. Saved views are the cross-cutting "list layout" store every entity
screen saves into, and the health surface is what the UI badges. The outbox
ledger and audit trail are the operator-visible halves of "no event is lost"
(§19) and "every sensitive action is answerable" (§66) — both reads, never
writes; their writers live in their own modules.

This module is now an AGGREGATOR: the endpoint implementations live in the
``routers/`` sub-package, grouped by domain. Every symbol that any external
module or test file historically imported from ``app.modules.platform.router``
is re-exported here so that **zero import paths change**.
"""

from fastapi import APIRouter

# ── Sub-routers (the actual endpoint implementations) ────────────────────
from app.modules.platform.routers.admin import router as _admin_router
from app.modules.platform.routers.audit import router as _audit_router
from app.modules.platform.routers.dr import router as _dr_router
from app.modules.platform.routers.flags import router as _flags_router
from app.modules.platform.routers.health import router as _health_router
from app.modules.platform.routers.metrics import router as _metrics_router
from app.modules.platform.routers.secrets import router as _secrets_router
from app.modules.platform.routers.views import router as _views_router
from app.modules.platform.routers.webhooks import router as _webhooks_router

# ── Assemble the public router ───────────────────────────────────────────
#
# Each sub-router defines routes with ``prefix="/platform"`` and ``tags=["platform"]``.
# Extending ``router.routes`` preserves exact Route objects without wrapping
# in `_IncludedRouter` proxies so test suites inspecting `router.routes` work
# identically.
router = APIRouter(prefix="/platform", tags=["platform"])
for _sub in (
    _flags_router,
    _metrics_router,
    _views_router,
    _health_router,
    _admin_router,
    _webhooks_router,
    _secrets_router,
    _dr_router,
    _audit_router,
):
    router.routes.extend(_sub.routes)

for _r in router.routes:
    if hasattr(_r, "endpoint") and callable(_r.endpoint):
        _r.endpoint.__module__ = "app.modules.platform.router"


# ── Re-exports: backward compatibility for every external importer ───────

# Dependency helpers & paging knobs
# The DR health indicator module — test_dead_module_wiring.py pins this import
# edge because DRService's only caller is the health route.
from app.modules.platform import dr  # noqa: E402, F401
from app.modules.platform.dr import DRService  # noqa: E402, F401
from app.modules.platform.routers._deps import (  # noqa: E402
    PageLimit,
    PageOffset,
    _require_platform_admin,
)

# Admin plane (§160, §147)
from app.modules.platform.routers.admin import (  # noqa: E402
    BreakGlassRequest,
    BreakGlassValidateRequest,
    admin_break_glass,
    admin_get_tenant,
    admin_list_tenants,
    admin_update_tenant_status,
    admin_validate_break_glass,
)

# Security events (§67), Outbox ledger (§19), Audit logs (§66)
from app.modules.platform.routers.audit import (  # noqa: E402
    _AUDIT_SOURCES,
    _OUTBOX_STATUSES,
    _outbox_event_summary,
    inspect_outbox_event,
    list_audit_logs,
    list_outbox_events,
    list_security_events,
)

# Disaster recovery (§164)
from app.modules.platform.routers.dr import (  # noqa: E402
    TenantRestoreJobCreate,
    _restore_job_payload,
    create_tenant_restore_job,
    execute_tenant_restore_job,
    extract_tenant_restore_job,
    get_tenant_restore_job,
    validate_tenant_restore_job,
)

# Feature flags (§76)
from app.modules.platform.routers.flags import (  # noqa: E402
    FEATURE_MAX_LEN,
    FlagUpsert,
    _flag_payload,
    check_flag,
    list_flags,
    upsert_flag,
)

# Health & Diagnostics (§103)
from app.modules.platform.routers.health import (  # noqa: E402
    DLQ_DEPTH_DEGRADED,
    DLQ_DEPTH_DOWN,
    DLQ_STREAMS,
    HEALTH_STATUSES,
    OUTBOX_LAG_DEGRADED_SECONDS,
    OUTBOX_LAG_DOWN_SECONDS,
    WEBHOOK_FAILURES_DOWN,
    _database_subsystem,
    _dlq_subsystem,
    _dr_subsystem,
    _integrations_subsystem,
    _outbox_subsystem,
    _redis_subsystem,
    build_health_response,
    health,
    integration_health,
    overall_health_status,
    remediate_system_issues,
    subsystem,
    system_diagnostics,
)

# Metrics registry (§167)
from app.modules.platform.routers.metrics import (  # noqa: E402
    _DEFINITION_FIELDS,
    list_metric_definitions,
    list_tenant_metric_definitions,
)

# Secrets (§68, §69)
from app.modules.platform.routers.secrets import (  # noqa: E402
    SecretRefCreate,
    SecretRotateRequest,
    create_secret_reference,
    rotate_secret,
)

# Saved views (§95)
from app.modules.platform.routers.views import (  # noqa: E402
    SAVED_VIEW_ENTITY_MAX,
    SAVED_VIEW_NAME_MAX,
    SAVED_VIEW_VISIBILITIES,
    SavedViewCreate,
    SavedViewUpdate,
    _load_view,
    _view_out,
    can_modify_saved_view,
    can_read_saved_view,
    create_saved_view,
    delete_saved_view,
    get_saved_view,
    list_saved_views,
    update_saved_view,
)

# Webhook DLQ surface (§24)
from app.modules.platform.routers.webhooks import (  # noqa: E402
    _WEBHOOK_IGNORE_FROM,
    _WEBHOOK_RESOLVE_FROM,
    _audit_webhook_dlq_op,
    _load_webhook_event,
    _webhook_event_summary,
    admin_ignore_webhook_event,
    admin_inspect_webhook_event,
    admin_list_webhook_events,
    admin_resolve_webhook_event,
    admin_retry_webhook_event,
)

__all__ = [
    "router",
    "PageLimit",
    "PageOffset",
    "_require_platform_admin",
    "FEATURE_MAX_LEN",
    "FlagUpsert",
    "_flag_payload",
    "list_flags",
    "upsert_flag",
    "check_flag",
    "_DEFINITION_FIELDS",
    "list_metric_definitions",
    "list_tenant_metric_definitions",
    "SAVED_VIEW_VISIBILITIES",
    "SAVED_VIEW_NAME_MAX",
    "SAVED_VIEW_ENTITY_MAX",
    "SavedViewCreate",
    "SavedViewUpdate",
    "can_read_saved_view",
    "can_modify_saved_view",
    "_view_out",
    "_load_view",
    "list_saved_views",
    "create_saved_view",
    "get_saved_view",
    "update_saved_view",
    "delete_saved_view",
    "HEALTH_STATUSES",
    "OUTBOX_LAG_DEGRADED_SECONDS",
    "OUTBOX_LAG_DOWN_SECONDS",
    "WEBHOOK_FAILURES_DOWN",
    "DLQ_DEPTH_DEGRADED",
    "DLQ_DEPTH_DOWN",
    "DLQ_STREAMS",
    "subsystem",
    "overall_health_status",
    "build_health_response",
    "integration_health",
    "_database_subsystem",
    "_redis_subsystem",
    "_outbox_subsystem",
    "_dlq_subsystem",
    "_integrations_subsystem",
    "_dr_subsystem",
    "health",
    "system_diagnostics",
    "remediate_system_issues",
    "admin_list_tenants",
    "admin_get_tenant",
    "admin_update_tenant_status",
    "BreakGlassRequest",
    "admin_break_glass",
    "BreakGlassValidateRequest",
    "admin_validate_break_glass",
    "SecretRefCreate",
    "create_secret_reference",
    "SecretRotateRequest",
    "rotate_secret",
    "TenantRestoreJobCreate",
    "_restore_job_payload",
    "create_tenant_restore_job",
    "get_tenant_restore_job",
    "extract_tenant_restore_job",
    "validate_tenant_restore_job",
    "execute_tenant_restore_job",
    "_WEBHOOK_IGNORE_FROM",
    "_WEBHOOK_RESOLVE_FROM",
    "_load_webhook_event",
    "_audit_webhook_dlq_op",
    "_webhook_event_summary",
    "admin_retry_webhook_event",
    "admin_list_webhook_events",
    "admin_inspect_webhook_event",
    "admin_ignore_webhook_event",
    "admin_resolve_webhook_event",
    "list_security_events",
    "_OUTBOX_STATUSES",
    "_outbox_event_summary",
    "list_outbox_events",
    "inspect_outbox_event",
    "_AUDIT_SOURCES",
    "list_audit_logs",
]
