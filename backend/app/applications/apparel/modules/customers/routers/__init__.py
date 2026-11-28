"""Customer routers package — re-exports router and platform_router."""

from app.applications.apparel.modules.customers.routers.customers import router
from app.applications.apparel.modules.customers.routers.integrations import platform_router

__all__ = ["router", "platform_router"]
