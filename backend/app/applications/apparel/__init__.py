"""FIHRIST Apparel: the first sector application.

The application is a declaration, not a framework. It says which modules it is
made of, which settings domains and permission codes it owns, which routes it
serves, and which events it publishes. A test checks every name here against
the code that actually exists, so the manifest cannot drift into a list of
aspirations (industry-applications §14).
"""

from app.applications.apparel.manifest import APP_MANIFEST, MODULES, ApparelManifest, ApparelModule
from app.applications.apparel.permissions import PERMISSIONS, ApparelPermission
from app.applications.apparel.routes import ROUTES, ApparelRoute
from app.applications.apparel.settings_ownership import (
    APP_LEVEL_SETTINGS_DOMAINS,
    PLATFORM_SETTINGS_DOMAINS,
    owned_settings_domains,
)

__all__ = [
    "APP_LEVEL_SETTINGS_DOMAINS",
    "APP_MANIFEST",
    "MODULES",
    "PERMISSIONS",
    "PLATFORM_SETTINGS_DOMAINS",
    "ROUTES",
    "ApparelManifest",
    "ApparelModule",
    "ApparelPermission",
    "ApparelRoute",
    "owned_settings_domains",
]
