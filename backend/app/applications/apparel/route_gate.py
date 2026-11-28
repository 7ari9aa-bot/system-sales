"""Which trading router is guarded by which apparel permission.

The gate has to run before a handler can touch the database, which in FastAPI
means a router-level dependency. Attaching it per route would be thirty chances
to forget one, so the mapping lives here and ``main`` attaches it to the whole
router in one call.

The codes are the module's *view* permission on purpose: it is the one the
compatibility bridge can satisfy from today's ``products:read`` /
``inventory:read`` / ``orders:read`` codes, so an employee who could open the
screen yesterday is not locked out by the gate today.
"""

from __future__ import annotations

from typing import Protocol

from app.applications.apparel.guard import require_apparel

#: module key -> the permission the whole router requires.
ROUTER_PERMISSIONS: dict[str, str] = {
    "catalog": "apparel.products.view",
    "inventory": "apparel.inventory.view",
    "purchasing": "apparel.purchases.view",
    "pos": "apparel.pos.access",
    "orders": "apparel.sales.view",
    "customers": "apparel.customers.view",
}


class _Router(Protocol):
    dependencies: list[object]


def gate_routers(*pairs: tuple[_Router, str]) -> int:
    """Attach the gate to each ``(router, module_key)`` pair; return how many.

    Idempotent: calling it twice does not stack two gates on one router, which
    would double the licence lookup on every request.
    """
    attached = 0
    for router, module_key in pairs:
        try:
            code = ROUTER_PERMISSIONS[module_key]
        except KeyError as exc:  # a typo must fail at import, not at a sale
            raise KeyError(f"no apparel permission declared for router {module_key!r}") from exc
        dependency = require_apparel(code)
        # A fresh closure each call, so identity cannot be the test: the code
        # stamped on it is what says "this router already carries this gate".
        already = any(
            getattr(existing, "apparel_permission_code", None) == code
            for existing in router.dependencies
        )
        if already:
            continue
        dependency.apparel_permission_code = code  # type: ignore[attr-defined]
        router.dependencies.append(dependency)
        attached += 1
    return attached
