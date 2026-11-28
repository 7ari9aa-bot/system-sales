"""Register every sector application the release ships.

The composition root calls this once at startup. It is the only place that
knows the list of applications: platform code asks
``app.core.sector_registry`` instead, so adding a sector is a change here and in
its own package, never in the platform.
"""

from __future__ import annotations


def register_all() -> tuple[str, ...]:
    """Register every shipped application; return their keys."""
    from app.applications.apparel.registration import register as register_apparel
    from app.core import sector_registry

    register_apparel()
    return sector_registry.applications()
