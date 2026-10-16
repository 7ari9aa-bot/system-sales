"""operations/routers subpackage entry point."""

from ._deps import router, search_router, sla_router
from . import tasks as _tasks  # noqa: F401
from . import search as _search  # noqa: F401
from . import jobs as _jobs  # noqa: F401
from . import sla as _sla  # noqa: F401

__all__ = ["router", "search_router", "sla_router"]
