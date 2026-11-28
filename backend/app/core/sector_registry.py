"""Where sector applications declare what they own.

The platform must never import an application, so it cannot hold a list of
sector names either: the day it does, adding a sector means editing platform
code. This registry is the neutral seam. An application registers its claims at
startup; platform code asks the registry and learns only "someone owns this",
never who that someone's business rules are.

Claims are namespaced by kind so one table answers every ownership question the
architecture asks: settings domains, permission namespaces, route prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass

SETTINGS_DOMAIN = "settings_domain"
PERMISSION_NAMESPACE = "permission_namespace"
ROUTE_PREFIX = "route_prefix"

KINDS = frozenset({SETTINGS_DOMAIN, PERMISSION_NAMESPACE, ROUTE_PREFIX})


@dataclass(frozen=True, slots=True)
class Claim:
    """One name, owned by one application."""

    kind: str
    name: str
    application: str


_CLAIMS: dict[tuple[str, str], Claim] = {}


def register(
    application: str,
    *,
    settings_domains: tuple[str, ...] = (),
    permission_namespaces: tuple[str, ...] = (),
    route_prefixes: tuple[str, ...] = (),
) -> None:
    """Record what ``application`` owns.

    A name claimed twice is an error, not a merge: two applications answering to
    the same settings domain or permission namespace is how an access check ends
    up with two owners and no answer.
    """
    if not application:
        raise ValueError("an application must have a key")

    for kind, names in (
        (SETTINGS_DOMAIN, settings_domains),
        (PERMISSION_NAMESPACE, permission_namespaces),
        (ROUTE_PREFIX, route_prefixes),
    ):
        for name in names:
            if not name:
                raise ValueError(f"{application}: empty {kind} name")
            existing = _CLAIMS.get((kind, name))
            if existing is not None and existing.application != application:
                raise ValueError(
                    f"{kind} {name!r} is already claimed by {existing.application!r}, "
                    f"cannot also belong to {application!r}"
                )
            _CLAIMS[(kind, name)] = Claim(kind=kind, name=name, application=application)


def owner(kind: str, name: str) -> str | None:
    """The application owning ``name``, or ``None`` when nobody claimed it."""
    claim = _CLAIMS.get((kind, name))
    return claim.application if claim else None


def claims(kind: str) -> dict[str, str]:
    """Every claimed name of ``kind`` mapped to its application."""
    if kind not in KINDS:
        raise ValueError(f"unknown claim kind: {kind!r}")
    return {name: claim.application for (claim_kind, name), claim in _CLAIMS.items() if claim_kind == kind}


def applications() -> tuple[str, ...]:
    return tuple(sorted({claim.application for claim in _CLAIMS.values()}))


def clear() -> None:
    """Drop every claim. Tests only: production registers once, at startup."""
    _CLAIMS.clear()
