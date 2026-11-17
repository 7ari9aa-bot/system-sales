"""inventory/routers — sub-package entry point.

The inventory domain grew past what one router file can hold, so the routes are
split the same way `orders/routers` is: one file per capability, each holding
its own `APIRouter`, and this package deciding the order they are registered in.

THE IMPORT ORDER IS ROUTE ORDER. FastAPI matches in registration order, so a
literal path under a prefix that also has a `{uuid}` route must be registered
FIRST or it is parsed as an id and rejected with a 422 before its own handler is
ever reached.

Each sub-router owns its own `APIRouter` and is mounted by
`app/modules/inventory/router.py`, which is the module's public route
surface. A sub-router never imports another sub-router.
"""

from __future__ import annotations

__all__: list[str] = []
