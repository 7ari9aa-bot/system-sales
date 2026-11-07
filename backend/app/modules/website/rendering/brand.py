"""The published site's merchant identity, readable from anywhere in rendering.

A dependency-free module (imports nothing from the package) so the verbatim
templates can import it at their top without a cycle with the renderer, which
registers templates during its own load.

The merchant's own identity (whatsapp, logo, socials) is set per render by
``renderer.render_website``. Templates read it through ``site_brand()`` and
fall back to their own constants when a key is absent — verbatim markup stays
untouched.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_SITE_BRAND: ContextVar[dict[str, Any] | None] = ContextVar("site_brand", default=None)


def set_site_brand(identity: dict[str, Any]) -> object:
    """Bind the render's identity; returns the token for ``reset``."""
    return _SITE_BRAND.set(dict(identity))


def reset_site_brand(token: object) -> None:
    _SITE_BRAND.reset(token)  # type: ignore[arg-type]


def site_brand(key: str) -> Any:
    """The published site's identity value for ``key``, or ``None``.

    Previews have no identity, so every key resolves to ``None`` there and
    the template's own constant wins.
    """
    current = _SITE_BRAND.get() or {}
    return current.get(key)
