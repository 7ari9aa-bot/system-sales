"""CUSTOMERS routes — list/search; plus PLATFORM routes for the settings screen
(invitations list, integrations).

.. deprecated:: refactored
   Route handlers now live in ``routers/customers.py`` and
   ``routers/integrations.py``. This file is a backward-compatible aggregator
   that re-exports ``router`` and ``platform_router`` so existing mounts
   (``from app.modules.customers.router import router, platform_router``)
   keep working.
"""

from __future__ import annotations

from app.modules.billing.service import EntitlementService  # noqa: F401

# Also re-export shared helpers that other modules may import from here.
from app.modules.customers.routers._deps import (  # noqa: F401
    ReadCtx,
    SettingsReadCtx,
    WriteCtx,
    _canonicalize_contact_fields,
    _customer_summary,
    _redact_issue_item,
)
from app.modules.customers.routers.customers import (
    list_contact_data_issues as list_contact_data_issues,
)

# Re-export from the routers sub-package.
from app.modules.customers.routers.customers import router  # noqa: F401
from app.modules.customers.routers.customers import (
    update_customer as update_customer,
)

# Re-export integration symbols that tests monkeypatch via this module path.
from app.modules.customers.routers.integrations import (  # noqa: F401
    _CHANNEL_CONFIG_FIELDS,
    _CHANNEL_CREDENTIAL_FIELDS,
    _telegram_webhook_url,
    platform_router,  # noqa: F401
)
from app.modules.customers.routers.integrations import (
    _activate_verified_channel as _activate_verified_channel,
)
from app.modules.customers.routers.integrations import (
    _integration_output as _integration_output,
)
from app.modules.customers.routers.integrations import (
    connect_integration as connect_integration,
)
from app.modules.customers.routers.integrations import (
    disconnect_integration as disconnect_integration,
)
from app.modules.customers.routers.integrations import (
    verify_integration as verify_integration,
)
from app.modules.customers.schemas import (  # noqa: F401
    ArchiveBody,
    ContactIssueResolution,
    CustomerUpdate,
    MergeBody,
    NoteBody,
    TagBody,
)
from app.modules.platform.integration_verifier import (  # noqa: F401
    configure_telegram_webhook,
    verify_channel_credentials,
)

# Preserve endpoint.__module__ so test_route_parameter_declarations.py and
# other introspection tests see the original module path.
_THIS = "app.modules.customers.router"
for _r in router.routes:
    if hasattr(_r, "endpoint"):
        _r.endpoint.__module__ = _THIS
for _r in platform_router.routes:
    if hasattr(_r, "endpoint"):
        _r.endpoint.__module__ = _THIS
