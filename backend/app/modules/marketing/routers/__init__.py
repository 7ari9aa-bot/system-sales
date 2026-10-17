"""marketing/routers — sub-package entry point.

Imports the sub-routers so their ``@router.*`` and ``@analytics_router.*``
decorators execute and register their endpoints on the shared routers from ``_deps.py``.
"""

from app.modules.marketing.routers import analytics as _analytics  # noqa: F401
from app.modules.marketing.routers import campaigns as _campaigns  # noqa: F401
from app.modules.marketing.routers import engagement as _engagement  # noqa: F401
from app.modules.marketing.routers._deps import analytics_router, router  # noqa: F401

__all__ = ["analytics_router", "router"]
