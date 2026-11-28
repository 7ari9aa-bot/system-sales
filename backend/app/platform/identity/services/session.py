"""Signed-in devices — what the account can see about its own sessions.

A "session" here is a refresh-token chain, not a row: rotation revokes the old
row and writes a new one, so exactly one live row exists per signed-in device
and the newest row IS the device's current state. Nothing new is stored, and no
auth flow changes shape — this module only reads what login already writes, and
revokes what logout already knows how to revoke.

`describe_device` is deliberately a pure function: a browser string is data, not
truth, and the label it produces is the only part of this feature that can be
tested without a database.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.platform.identity.models import RefreshToken
from app.platform.identity.services._common import _now

# Ordered: the FIRST matching needle wins, so the specific browsers sit above
# the engines they embed (Edge is Chrome-shaped, Chrome is Safari-shaped).
_BROWSERS: tuple[tuple[str, str], ...] = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("opera", "Opera"),
    ("firefox", "Firefox"),
    ("chrome", "Chrome"),
    ("crios", "Chrome"),
    ("safari", "Safari"),
)

_SYSTEMS: tuple[tuple[str, str], ...] = (
    ("iphone", "iPhone"),
    ("ipad", "iPad"),
    ("android", "Android"),
    ("windows", "Windows"),
    ("mac os", "macOS"),
    ("macintosh", "macOS"),
    ("linux", "Linux"),
)

# The desktop build is a Tauri shell: it presents the platform's webview UA, so
# the only honest way to name it is the token Tauri adds.
_DESKTOP_NEEDLES = ("fihrist", "tauri")


def describe_device(user_agent: str | None) -> str:
    """A short, honest label for a browser string.

    An empty or unrecognised string is named as unknown rather than guessed —
    the screen shows "Unknown device" beside the IP, which is still actionable.
    """
    if not user_agent:
        return "Unknown device"
    haystack = user_agent.lower()
    if any(needle in haystack for needle in _DESKTOP_NEEDLES):
        return "FIHRIST desktop"
    browser = next((name for needle, name in _BROWSERS if needle in haystack), None)
    system = next((name for needle, name in _SYSTEMS if needle in haystack), None)
    if browser and system:
        return f"{browser} · {system}"
    return browser or system or "Unknown device"


def _device_key(user_agent: str | None, ip: str | None) -> tuple[str, str]:
    return ((user_agent or "").strip().lower(), (ip or "").strip())


class SignedInDeviceService:
    """Read and revoke the refresh-token chains that belong to one account."""

    @staticmethod
    async def list_devices(
        session, user_id: uuid.UUID, *, current_token_hash: str | None = None
    ) -> list[dict]:
        """Every live chain, newest first, with the caller's own one marked.

        Live means: not revoked and not expired. Rotation leaves one live row per
        device, so a device appears once even though it has refreshed many times.
        """
        now = _now()
        rows = (
            (
                await session.execute(
                    select(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > now,
                    )
                    .order_by(RefreshToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        seen: set[tuple[str, str]] = set()
        devices: list[dict] = []
        for row in rows:
            key = _device_key(row.user_agent, row.ip)
            if key in seen:
                continue
            seen.add(key)
            devices.append(
                {
                    "id": row.id,
                    "device": describe_device(row.user_agent),
                    "user_agent": row.user_agent,
                    "ip": row.ip,
                    "signed_in_at": row.created_at,
                    "last_used_at": row.created_at,
                    "expires_at": row.expires_at,
                    "current": bool(current_token_hash) and row.token_hash == current_token_hash,
                }
            )
        return devices

    @staticmethod
    async def revoke_others(
        session, user_id: uuid.UUID, *, current_token_hash: str | None = None
    ) -> int:
        """Sign out everywhere else, keeping the device that asked."""
        now = _now()
        conditions = [
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        ]
        if current_token_hash:
            conditions.append(RefreshToken.token_hash != current_token_hash)
        result = await session.execute(
            sa.update(RefreshToken).where(*conditions).values(revoked_at=now)
        )
        return int(result.rowcount or 0)

    @staticmethod
    async def revoke_all(session, user_id: uuid.UUID) -> int:
        """Sign out every device, the caller's included."""
        result = await session.execute(
            sa.update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        return int(result.rowcount or 0)

    @staticmethod
    async def revoke_one(session, user_id: uuid.UUID, device_id: uuid.UUID) -> None:
        """Revoke one chain. A chain that is not this account's is a 404, not a 403:
        the answer must not confirm that someone else's session exists."""
        now = _now()
        row = (
            await session.execute(
                select(RefreshToken)
                .where(
                    RefreshToken.id == device_id,
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that session is not signed in")
        row.revoked_at = now
