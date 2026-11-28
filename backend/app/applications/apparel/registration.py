"""What FIHRIST Apparel claims, in the platform's registry.

Kept separate from the manifest so the claim and the definition can be read
apart: the manifest says what the application is, this says what the platform
must stop answering for.
"""

from __future__ import annotations

from app.applications.apparel import consumers, events
from app.applications.apparel.manifest import APP_MANIFEST
from app.applications.apparel.permissions import NAMESPACE
from app.applications.apparel.routes import PREFIX
from app.applications.apparel.settings_ownership import owned_settings_domains
from app.core import sector_registry


def register() -> None:
    """Claim the apparel application's names. Idempotent: startup may retry."""
    sector_registry.register(
        APP_MANIFEST.key,
        settings_domains=tuple(sorted(owned_settings_domains())),
        permission_namespaces=(NAMESPACE,),
        route_prefixes=(PREFIX,),
    )
    # Event types the outbox must be able to deserialize (§17). Registered by
    # the application, so the platform's closed set never names a sector.
    events.register()
    # Consumers for the events this release actually acts on (§17).
    consumers.register()
