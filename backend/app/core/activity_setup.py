"""First-run activity setup: has the owner told us what kind of shop this is yet?

A new signup starts ``not_started``; the owner then either completes the setup (picks a vertical,
and may ask for that vertical's starting preset) or skips it. A shop that existed before this
module has no row, so ``business.setup_state`` reads its registry default, ``done``, and nobody
already running is ever sent to the setup.

Three rules keep it safe to call twice and safe next to a shop that is already set up:

* Only ``not_started`` can change. A second ``complete`` or ``skip`` (a double tap, a retry, a
  second tab) writes nothing and answers with the state as it stands.
* The preset is applied with ``only_missing``: it fills the switches the owner never touched and
  leaves every switch the owner already set exactly as it is.
* Only the verticals that behave differently (``CHOOSABLE_VERTICALS``) can be chosen. Pharmacy,
  restaurant and the rest are refused, not silently accepted: choosing them would change nothing.

Reading the state needs only a signed-in user; changing it needs ``settings:write``, so a cashier
can see the state but never move it. ``needs_setup`` is the one answer the screen acts on, and the
server computes it (not_started AND the caller may write settings) so no client role check exists.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shop_type import CHOOSABLE_VERTICALS, choose_vertical
from app.core.tenancy import register_signup_choices_hook
from app.modules.errors import ValidationError
from app.platform.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.platform.settings.presets import PRESETS
from app.platform.settings.service import SettingsService

STATE_KEY = "business.setup_state"
TERMS_KEY = "business.terms_accepted_at"
NOT_STARTED = "not_started"
DONE = "done"
SKIPPED = "skipped"

# The preset each vertical offers on its first run. A vertical not listed here offers none, so a
# plain "general" shop can only choose the vertical and nothing else.
VERTICAL_PRESET: dict[str, str] = {"apparel": "apparel_ground_shop"}


#: Core cannot import a module, so modules hand their setup work in here instead.
#: Each hook receives the finished setup's context and may add to its result.
_setup_hooks: list[Callable[..., Any]] = []


def register_setup_completed_hook(hook: Callable[..., Any]) -> None:
    """Let a module act when an activity finishes its setup. Idempotent by identity."""
    if hook not in _setup_hooks:
        _setup_hooks.append(hook)


def _settings(session: AsyncSession, tenant_id: UUID) -> SettingsService:
    return SettingsService(session, tenant_id)


async def read_state(session: AsyncSession, tenant_id: UUID) -> str:
    """``done`` for any shop that never had a row; otherwise what the setup flow last wrote."""
    return str((await _settings(session, tenant_id).resolve(STATE_KEY)).value)


async def mark_not_started(session: AsyncSession, tenant_id: UUID) -> None:
    """Called once, at signup, so the new owner is offered the setup on first login."""
    await _settings(session, tenant_id).set(STATE_KEY, NOT_STARTED, user_id=None)


async def _lock(session: AsyncSession, tenant_id: UUID) -> None:
    # One setup per shop at a time. Without it two taps both read not_started and both apply.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"activity_setup:{tenant_id}"},
    )


async def complete_setup(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    vertical: str,
    apply_preset: bool,
    user_id: UUID | None,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Choose the vertical (and, if asked, its preset) and mark the setup done. Idempotent."""
    if vertical not in CHOOSABLE_VERTICALS:
        raise ValidationError(f"vertical must be one of {sorted(CHOOSABLE_VERTICALS)}")

    async with session.begin_nested():
        await _lock(session, tenant_id)
        state = await read_state(session, tenant_id)
        if state != NOT_STARTED:
            # Already set up or skipped: change nothing, report what is.
            return {"state": state, "changed": False, "vertical": None, "preset_applied": None}

        chosen = await choose_vertical(session, tenant_id, vertical, user_id=user_id)
        preset_name = VERTICAL_PRESET.get(vertical) if apply_preset else None
        applied = 0
        if preset_name is not None:
            rows = await _settings(session, tenant_id).apply_preset(
                preset_name, user_id=user_id, permissions=permissions, only_missing=True
            )
            applied = len(rows)
        await _settings(session, tenant_id).set(STATE_KEY, DONE, user_id=user_id)
    return {
        "state": DONE,
        "changed": True,
        "vertical": chosen["vertical"],
        "categories_created": chosen["categories_created"],
        "preset_applied": preset_name,
        "settings_filled": applied,
    }


async def skip_setup(
    session: AsyncSession, tenant_id: UUID, *, user_id: UUID | None
) -> dict[str, Any]:
    """Leave the shop as it is and stop asking. Idempotent; never touches settings or categories."""
    async with session.begin_nested():
        await _lock(session, tenant_id)
        state = await read_state(session, tenant_id)
        if state != NOT_STARTED:
            return {"state": state, "changed": False}
        await _settings(session, tenant_id).set(STATE_KEY, SKIPPED, user_id=user_id)
    return {"state": SKIPPED, "changed": True}


async def reopen_setup(
    session: AsyncSession, tenant_id: UUID, *, user_id: UUID | None
) -> dict[str, Any]:
    """Ask the owner again. Only a shop that answered or skipped can be reopened.

    This changes one thing, the marker. It plants nothing and sets nothing, and when the owner
    then confirms, the preset fills only the switches they never touched (``only_missing``), so
    reopening can never overwrite what they built since. Idempotent: reopening a shop that is
    already waiting changes nothing.
    """
    async with session.begin_nested():
        await _lock(session, tenant_id)
        state = await read_state(session, tenant_id)
        if state == NOT_STARTED:
            return {"state": state, "changed": False}
        await _settings(session, tenant_id).set(STATE_KEY, NOT_STARTED, user_id=user_id)
    return {"state": NOT_STARTED, "changed": True}


async def record_signup_choices(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, choices: dict[str, Any]
) -> None:
    """Write what the signup form told us. Nothing is written when it told us nothing.

    ``offer_activity_setup`` is set only by the form signup: a person who typed an email and a
    password is a new owner who should be asked what kind of shop this is. Google sign-in and every
    older caller never dispatch this, so their shop reads ``done`` and is never interrupted.
    """
    if choices.get("offer_activity_setup") is True:
        await mark_not_started(session, tenant_id)
    if choices.get("terms_accepted") is True:
        await _settings(session, tenant_id).set(
            TERMS_KEY, datetime.now(UTC).isoformat(timespec="seconds"), user_id=user_id
        )


register_signup_choices_hook(record_signup_choices)


# ── The routes ─────────────────────────────────────────────────────────────────────────────────

router = APIRouter()
SetupWriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


class CompleteSetupBody(BaseModel):
    vertical: str = Field(min_length=1, max_length=32)
    # False by default: the preset is something the owner asks for, never something done to them.
    apply_preset: bool = False


@router.get("/activity-setup")
async def get_activity_setup(ctx: TenantCtxDep) -> dict[str, Any]:
    """The state, what may be chosen, and whether THIS caller should be shown the setup."""
    state = await read_state(ctx.session, ctx.tenant_id)
    may_write = "settings:write" in ctx.permission_codes
    return {
        "state": state,
        "needs_setup": state == NOT_STARTED and may_write,
        "choices": list(CHOOSABLE_VERTICALS),
        "presets": dict(VERTICAL_PRESET),
        "preset_keys": {v: sorted(PRESETS[p]) for v, p in VERTICAL_PRESET.items() if p in PRESETS},
    }


@router.post("/activity-setup/complete")
async def complete_activity_setup(body: CompleteSetupBody, ctx: SetupWriteCtx) -> dict[str, Any]:
    result = await complete_setup(
        ctx.session,
        ctx.tenant_id,
        vertical=body.vertical,
        apply_preset=body.apply_preset,
        user_id=ctx.user.id,
        permissions=ctx.permission_codes,
    )
    if result.get("changed"):
        for hook in _setup_hooks:
            await hook(ctx, result)
    return result


@router.post("/activity-setup/reopen")
async def reopen_activity_setup(ctx: SetupWriteCtx) -> dict[str, Any]:
    return await reopen_setup(ctx.session, ctx.tenant_id, user_id=ctx.user.id)


@router.post("/activity-setup/skip")
async def skip_activity_setup(ctx: SetupWriteCtx) -> dict[str, Any]:
    return await skip_setup(ctx.session, ctx.tenant_id, user_id=ctx.user.id)
