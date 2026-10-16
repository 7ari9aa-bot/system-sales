"""Customer routers package — re-exports router and platform_router."""

from app.modules.customers.routers.customers import router
from app.modules.customers.routers.integrations import platform_router

__all__ = ["router", "platform_router"]
