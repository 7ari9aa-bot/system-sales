"""orders/routers — sub-package entry point.

Imports the sub-routers so their ``@router.*`` decorators execute and register
their endpoints on the shared ``router`` from ``_deps.py``.

THE IMPORT ORDER IS ROUTE ORDER. FastAPI matches in registration order, so a
literal path under a prefix that also has a ``{uuid}`` route must be registered
FIRST or it is parsed as an id and rejected with a 422 before its own handler is
ever reached. ``deposits`` owns ``/orders/deposit-policies`` beside ``orders``'
``/orders/{order_id}``, so it goes first — and
``test_the_policy_list_is_not_swallowed_by_the_order_route`` fails if this line
is ever reordered.
"""

from app.modules.orders.routers import deposits as _deposits  # noqa: F401  (must precede orders)
from app.modules.orders.routers import orders as _orders  # noqa: F401
from app.modules.orders.routers import payments as _payments  # noqa: F401
from app.modules.orders.routers import shipments as _shipments  # noqa: F401
from app.modules.orders.routers._deps import router  # noqa: F401

__all__ = ["router"]
