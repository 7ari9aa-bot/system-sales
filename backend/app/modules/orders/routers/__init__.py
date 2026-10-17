"""orders/routers — sub-package entry point.

Imports the sub-routers so their ``@router.*`` decorators execute and register
their endpoints on the shared ``router`` from ``_deps.py``.
"""

from app.modules.orders.routers import orders as _orders  # noqa: F401
from app.modules.orders.routers import payments as _payments  # noqa: F401
from app.modules.orders.routers import shipments as _shipments  # noqa: F401
from app.modules.orders.routers._deps import router  # noqa: F401

__all__ = ["router"]
