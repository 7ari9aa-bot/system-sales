"""Helpers every customer tool group shares.

Split out of the former single-file ``customer/tools.py``; the code is unchanged.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.core.errors import DomainError


def sellable_product_statuses() -> frozenset[str]:
    """The checkout gate's sellable vocabulary, for in-module readers.

    ONE lazy import site: the catalog's tables are read as parameter-bound
    read models, and the vision verifier plus every tool here read the
    vocabulary through this function so they can never drift from checkout.
    """
    from app.modules.orders.service import SELLABLE_PRODUCT_STATUSES

    return SELLABLE_PRODUCT_STATUSES


def _parse_bound_id(raw: object) -> uuid.UUID | None:
    """Parse a server-side id from the context; malformed is a tool error."""
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise DomainError("bound id is not a valid uuid") from exc


def _money(value) -> str | None:
    """Money is Decimal(Numeric(14,2)) — serialized exactly, never as float."""
    return None if value is None else str(value)


class _StrictArgs(BaseModel):
    """Base of every customer tool's arguments.

    An argument the tool does not declare is an error, not something to drop:
    the model cannot slip `visibility` or an id past a handler that never asked
    for it, and the generated JSON schema carries `additionalProperties: false`
    without depending on a provider's `strict` mode (the base_url is a
    per-tenant OpenAI-compatible endpoint, so that mode is not guaranteed).
    """

    model_config = ConfigDict(extra="forbid")
