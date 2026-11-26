"""UserService — profile, activation, token decoding.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import decode_token
from app.modules.identity.models import User
from app.modules.identity.services.settings import timezone_refusal

#: The closed sets the preferences screen offers. They are duplicated in the
#: migration's CHECK constraints on purpose: the database refuses a value that a
#: future code path forgot to validate, and this module refuses it with a message
#: a person can read instead of a 500 from the constraint.
LOCALES = ("ar", "en")
THEMES = ("system", "light", "dark")
DATE_FORMATS = ("dmy", "mdy", "ymd")
#: Where "/" may land. A stored route is a redirect target, so the API whitelists
#: it: an arbitrary path here would be a redirect primitive with a database row.
DEFAULT_PAGES = ("/dashboard", "/inbox", "/cashier", "/customers", "/settings")


class UserService:
    @staticmethod
    async def get(session, user_id: uuid.UUID) -> User:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundError("user not found")
        return user

    @staticmethod
    async def names(session, user_ids) -> dict[uuid.UUID, str | None]:
        """full_name per user id, in ONE query. A removed user is simply absent."""
        ids = set(user_ids)
        if not ids:
            return {}
        rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
        return {row.id: row.full_name for row in rows}

    @staticmethod
    async def update_profile(
        session,
        user_id: uuid.UUID,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        job_title: str | None = None,
    ) -> User:
        """Rewrite the account's own display name, phone and job title.

        The name is shown to colleagues, on the POS receipt header and beside
        every audit row this person writes, so the stored value is the cleaned
        one: surrounding and repeated whitespace collapses to single spaces and
        a name that is only whitespace is refused (400) rather than saved as an
        invisible identity. ``None`` means "leave it alone", which is what keeps
        this usable as a partial update.

        The phone and the job title are optional facts, so an EMPTY string is a
        real instruction: it clears the field. A non-empty phone is reduced to
        the digits and one leading ``+`` (people write "+20 100 123 4567"), and
        a value that is not a phone number after that is refused instead of
        stored as decoration.
        """
        user = await UserService.get(session, user_id)
        changed = False
        if full_name is not None:
            cleaned = " ".join(full_name.split())
            if not cleaned:
                raise ValidationError("a profile name cannot be empty")
            if cleaned != user.full_name:
                user.full_name = cleaned
                changed = True
        if phone is not None:
            cleaned_phone = UserService._clean_phone(phone)
            if cleaned_phone != user.phone:
                user.phone = cleaned_phone
                changed = True
        if job_title is not None:
            cleaned_title = " ".join(job_title.split()) or None
            if cleaned_title != user.job_title:
                user.job_title = cleaned_title
                changed = True
        if changed:
            await session.flush()
        return user

    @staticmethod
    async def update_preferences(
        session,
        user_id: uuid.UUID,
        *,
        locale: str | None = None,
        theme: str | None = None,
        timezone: str | None = None,
        date_format: str | None = None,
        default_page: str | None = None,
    ) -> User:
        """Rewrite the caller's own presentation preferences.

        Same contract as ``update_profile``: ``None`` means "leave it alone", so the
        screen can save one control at a time, and an EMPTY string is a real
        instruction — it clears the field back to the default. Every value is
        checked against the set the screen offers, and the timezone is resolved with
        ``zoneinfo`` rather than merely shape-checked: a stored zone that Python
        cannot resolve would silently bucket a Cairo account in UTC.
        """
        user = await UserService.get(session, user_id)
        changed = False

        def _one_of(value: str, allowed: tuple[str, ...], label: str) -> str | None:
            cleaned = (value or "").strip().lower()
            if not cleaned:
                return None
            if cleaned not in allowed:
                raise ValidationError(f"'{cleaned}' is not a valid {label}")
            return cleaned

        if locale is not None:
            cleaned = _one_of(locale, LOCALES, "language")
            if cleaned != user.locale:
                user.locale = cleaned
                changed = True
        if theme is not None:
            cleaned = _one_of(theme, THEMES, "appearance")
            if cleaned != user.theme:
                user.theme = cleaned
                changed = True
        if date_format is not None:
            cleaned = _one_of(date_format, DATE_FORMATS, "date format")
            if cleaned != user.date_format:
                user.date_format = cleaned
                changed = True
        if timezone is not None:
            raw = (timezone or "").strip()
            if not raw:
                cleaned_tz = None
            else:
                refusal = timezone_refusal(raw)
                if refusal is not None:
                    raise ValidationError(refusal)
                cleaned_tz = raw
            if cleaned_tz != user.timezone:
                user.timezone = cleaned_tz
                changed = True
        if default_page is not None:
            raw = (default_page or "").strip()
            if not raw:
                cleaned_page = None
            elif raw not in DEFAULT_PAGES:
                raise ValidationError(f"'{raw}' is not a page this account may land on")
            else:
                cleaned_page = raw
            if cleaned_page != user.default_page:
                user.default_page = cleaned_page
                changed = True

        if changed:
            await session.flush()
        return user

    #: Digits with an optional leading "+", the only shape a stored phone takes.
    _PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")

    @staticmethod
    def _clean_phone(value: str) -> str | None:
        """Reduce a typed phone number to its digits, or clear it.

        Anything that still is not a phone after stripping the punctuation
        people type (spaces, dashes, brackets) is refused: a stored value that
        cannot be dialled is worse than an empty field.
        """
        raw = (value or "").strip()
        if not raw:
            return None
        stripped = re.sub(r"[^0-9+]", "", raw)
        if stripped.startswith("+"):
            stripped = "+" + stripped[1:].replace("+", "")
        else:
            stripped = stripped.replace("+", "")
        if not UserService._PHONE_RE.match(stripped):
            raise ValidationError("a phone number must be 7 to 15 digits")
        return stripped

    @staticmethod
    async def set_avatar_url(session, user_id: uuid.UUID, value: str | None) -> User:
        """Point the account at its picture, or clear it. No commit here."""
        user = await UserService.get(session, user_id)
        user.avatar_url = value
        await session.flush()
        return user

    @staticmethod
    async def clear_avatar_url(session, user_id: uuid.UUID) -> User:
        return await UserService.set_avatar_url(session, user_id, None)

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
