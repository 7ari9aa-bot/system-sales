"""The person's own preferences: closed sets, a real clock, and a safe landing page.

These five values used to live in localStorage, which meant they followed the
browser rather than the account. Moving them onto the row makes the server the
source of truth, and that brings three obligations the browser never had: a value
the screen does not offer must be refused, a timezone must be one the runtime can
actually resolve, and the stored landing page must be a route the API is willing
to redirect to — a free-form path in a database row is a redirect primitive.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.platform.identity.models import User
from app.platform.identity.routers.users import users_router
from app.platform.identity.services.user import (
    DATE_FORMATS,
    DEFAULT_PAGES,
    LOCALES,
    THEMES,
    UserService,
)


async def _reload(db: AsyncSession, user_id: uuid.UUID) -> User:
    await db.flush()
    return (await db.execute(sa.select(User).where(User.id == user_id))).scalar_one()


# ------------------------------------------------------------------ storing --


async def test_each_control_can_be_saved_on_its_own(db: AsyncSession, tenant_ctx) -> None:
    """One control at a time is the contract: None leaves the others untouched."""
    await UserService.update_preferences(db, tenant_ctx.user.id, theme="dark")
    await UserService.update_preferences(db, tenant_ctx.user.id, locale="en")

    user = await _reload(db, tenant_ctx.user.id)
    assert user.theme == "dark"
    assert user.locale == "en"
    assert user.timezone is None


async def test_an_empty_string_clears_back_to_the_default(db: AsyncSession, tenant_ctx) -> None:
    await UserService.update_preferences(
        db, tenant_ctx.user.id, timezone="Africa/Cairo", default_page="/inbox"
    )
    await UserService.update_preferences(db, tenant_ctx.user.id, timezone="", default_page="")

    user = await _reload(db, tenant_ctx.user.id)
    assert user.timezone is None
    assert user.default_page is None


async def test_the_persons_zone_is_not_the_shops_zone(db: AsyncSession, tenant_ctx) -> None:
    """Moving a branch must never move the person's clock."""
    await UserService.update_preferences(db, tenant_ctx.user.id, timezone="Europe/London")

    user = await _reload(db, tenant_ctx.user.id)
    assert user.timezone == "Europe/London"
    tenant_zone = (
        await db.execute(sa.select(sa.column("timezone")).select_from(sa.table("tenants")))
    ).first()
    assert tenant_zone is None or tenant_zone[0] != "Europe/London"


# --------------------------------------------------------------- refusing ----


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("locale", "fr"),
        ("theme", "neon"),
        ("date_format", "iso"),
        ("default_page", "https://evil.example"),
        ("default_page", "/admin/anything"),
        ("timezone", "Mars/Olympus"),
    ],
)
async def test_a_value_the_screen_does_not_offer_is_refused(
    db: AsyncSession, tenant_ctx, field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        await UserService.update_preferences(db, tenant_ctx.user.id, **{field: value})

    user = await _reload(db, tenant_ctx.user.id)
    assert getattr(user, field) is None


async def test_a_refusal_leaves_the_previous_value_intact(db: AsyncSession, tenant_ctx) -> None:
    await UserService.update_preferences(db, tenant_ctx.user.id, theme="dark")
    with pytest.raises(ValidationError):
        await UserService.update_preferences(db, tenant_ctx.user.id, theme="neon")

    assert (await _reload(db, tenant_ctx.user.id)).theme == "dark"


async def test_case_is_folded_rather_than_rejected(db: AsyncSession, tenant_ctx) -> None:
    """'AR' from a form is the same choice as 'ar'; refusing it would be pedantry."""
    await UserService.update_preferences(db, tenant_ctx.user.id, locale="AR", theme="DARK")

    user = await _reload(db, tenant_ctx.user.id)
    assert user.locale == "ar"
    assert user.theme == "dark"


def test_the_offered_sets_are_the_ones_the_screen_draws() -> None:
    assert LOCALES == ("ar", "en")
    assert THEMES == ("system", "light", "dark")
    assert DATE_FORMATS == ("dmy", "mdy", "ymd")
    # a landing page is a redirect target, so the list is explicit and short
    assert "/dashboard" in DEFAULT_PAGES
    assert all(page.startswith("/") and "//" not in page for page in DEFAULT_PAGES)


def test_the_preferences_routes_exist_on_the_users_router() -> None:
    routes = {
        (method, route.path)
        for route in users_router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("GET", "/users/me/preferences") in routes
    assert ("PATCH", "/users/me/preferences") in routes
