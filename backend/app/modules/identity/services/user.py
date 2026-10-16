"""UserService — profile, activation, token decoding.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import decode_token
from app.modules.identity.models import User


class UserService:
    @staticmethod
    async def get(session, user_id: uuid.UUID) -> User:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundError("user not found")
        return user

    @staticmethod
    async def update_profile(session, user_id: uuid.UUID, *, full_name: str | None = None) -> User:
        user = await UserService.get(session, user_id)
        if full_name is not None:
            user.full_name = full_name
        return user

    @staticmethod
    async def set_active(session, user_id: uuid.UUID, *, is_active: bool) -> User:
        user = await UserService.get(session, user_id)
        user.is_active = is_active
        return user

    @staticmethod
    async def decode_access(token: str) -> dict:
        """Decode + sanity-check an access token (type claim)."""
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        return payload
