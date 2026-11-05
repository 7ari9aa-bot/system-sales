"""Slug rules for website subdomains.

A website slug BECOMES a subdomain label once wildcard DNS is enabled, so the
rules are stricter than a page path: ASCII lowercase letters/digits/hyphens,
3-80 chars, no leading/trailing hyphen, and never a reserved name (``www``,
``api``, ``admin``, ...). Arabic site names are slugified by dropping
non-ASCII (transliteration is a later slice, same deferral as the spec's
seo.py) — the merchant can always type the slug explicitly.
"""

from __future__ import annotations

import re
import unicodedata

from app.modules.website.errors import SlugReservedError, WebsiteDomainError

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?$")
SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 80

# Names that must never become a customer site: infrastructure labels on the
# apex domain and the obvious support/abuse traps. Kept as a frozenset so the
# membership check is a hash lookup on every purchase.
RESERVED_SLUGS = frozenset(
    {
        "www",
        "api",
        "app",
        "admin",
        "owner",
        "console",
        "dashboard",
        "mail",
        "webmail",
        "smtp",
        "ftp",
        "ns1",
        "ns2",
        "blog",
        "shop",
        "store",
        "sites",
        "static",
        "cdn",
        "assets",
        "media",
        "help",
        "support",
        "status",
        "billing",
        "docs",
        "auth",
        "login",
        "signup",
        "register",
        "payments",
        "pay",
        "security",
        "privacy",
        "terms",
        "about",
        "contact",
    }
)


def slugify(raw: str) -> str:
    """Normalise text into a subdomain-safe slug ('' when nothing survives)."""
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:SLUG_MAX_LENGTH].strip("-")


def validate_slug(slug: str) -> None:
    """Fail closed on a slug that must not become a subdomain label."""
    if not SLUG_RE.match(slug):
        raise WebsiteDomainError(
            "site address must be 3-80 lowercase letters, digits or hyphens, "
            "starting and ending with a letter or digit",
            details={"slug": slug},
        )
    if len(slug) < SLUG_MIN_LENGTH:
        raise WebsiteDomainError(
            "site address must be at least 3 characters", details={"slug": slug}
        )
    if slug in RESERVED_SLUGS:
        raise SlugReservedError(details={"slug": slug})
