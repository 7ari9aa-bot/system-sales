"""Where the platform stops and an application's settings begin.

The settings registry holds every key in one table, and it stays that way: one
validator, one history, one resolver. What it must not become is a place where a
platform screen can read a shop's trading rules, because that is how the platform
starts needing to know what a sector is.

Two sets, one rule:

* the domains the platform owns are listed here, in platform code;
* every other domain belongs to whichever application claimed it in
  ``app.core.sector_registry``.

An unclaimed domain is refused rather than allowed: a domain nobody owns is a
question nobody answered, and guessing "platform" is how a sector rule leaks.
"""

from __future__ import annotations

from app.core import sector_registry
from app.core.errors import PermissionDeniedError

#: Settings the platform itself owns: the account, its people, its security, its
#: bill. None of them describes how a shop trades, so no sector application may
#: claim them and every platform screen may read them without knowing the sector.
PLATFORM_DOMAINS: frozenset[str] = frozenset(
    {
        "organization",
        "team",
        "security",
        "billing",
    }
)


def owner_of(domain: str) -> str | None:
    """``"platform"``, an application key, or ``None`` when unclaimed."""
    if domain in PLATFORM_DOMAINS:
        return "platform"
    return sector_registry.owner(sector_registry.SETTINGS_DOMAIN, domain)


def is_platform_domain(domain: str) -> bool:
    return domain in PLATFORM_DOMAINS


def assert_platform_may_read(domain: str) -> None:
    """Allow a platform surface to read ``domain``, or refuse with the reason.

    Call this from any platform-level settings reader that is not already scoped
    to one of ``PLATFORM_DOMAINS``. An application's own screens read their
    domains through their own context, not through this function.
    """
    owner = owner_of(domain)
    if owner == "platform":
        return
    if owner is None:
        raise PermissionDeniedError(f"settings domain {domain!r} has no owner")
    raise PermissionDeniedError(
        f"settings domain {domain!r} belongs to application {owner!r}, "
        "not to the platform layer"
    )


def assert_application_may_read(domain: str, application: str) -> None:
    """Allow ``application`` to read its own domain, and nothing else."""
    owner = owner_of(domain)
    if owner == application:
        return
    if owner is None:
        raise PermissionDeniedError(f"settings domain {domain!r} has no owner")
    raise PermissionDeniedError(
        f"settings domain {domain!r} belongs to {owner!r}, not to {application!r}"
    )
