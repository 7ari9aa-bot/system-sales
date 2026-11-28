"""Messenger Platform settings that had no lifecycle at all.

The channel could send and receive messages, but the Page's Messenger PROFILE was never
configured: no greeting, no Get Started button, no persistent menu, no ice breakers, no labels.
Meta exposes all of these on `/me/messenger_profile` (and labels on the PSID), and each one has an
exact payload shape that Meta validates strictly — so this module sends exactly those shapes and
lets Meta's own refusal through unchanged.

Payload shapes follow Meta's Messenger Platform reference:
https://developers.facebook.com/docs/messenger-platform/reference/messenger-profile-api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.errors import ExternalProviderError, ValidationError

logger = logging.getLogger(__name__)

_API_VERSION = "v23.0"

#: Locales Meta accepts for the greeting; `default` covers every locale not listed.
DEFAULT_LOCALE = "default"

#: Meta's own limits: 5 call-to-action buttons, 3 ice breakers, 5 menu items.
MAX_MENU_ITEMS = 5
MAX_ICE_BREAKERS = 3
MAX_CALL_TO_ACTIONS = 5
MAX_GREETING_CHARS = 160
MAX_ICEBREAKER_CHARS = 80


def _base(api_version: str) -> str:
    return f"https://graph.facebook.com/{api_version}"


def _error_of(payload: dict) -> str | None:
    err = payload.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("message") or err.get("type") or ""
        return f"code {code}: {message}" if code is not None else str(message or "error")
    return None


class MessengerProfile:
    """The Page's Messenger profile settings, one method per Meta field."""

    def __init__(self, *, api_version: str = _API_VERSION) -> None:
        self._base = _base(api_version)

    async def _call(
        self,
        http: httpx.AsyncClient,
        method: str,
        path: str,
        token: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await http.request(
            method,
            f"{self._base}/{path.lstrip('/')}",
            json=json,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ExternalProviderError(
                f"messenger profile: not JSON ({resp.status_code})"
            ) from exc
        if not isinstance(payload, dict):
            raise ExternalProviderError("messenger profile: unexpected payload")
        message = _error_of(payload)
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ExternalProviderError(
                f"messenger profile: {resp.status_code} {message or ''}".strip()
            )
        if resp.status_code >= 400 or message:
            raise ValidationError(f"ميتا رفضت إعداد ماسنجر: {message or resp.status_code}")
        return payload

    # ---- greeting ----
    async def set_greeting(
        self,
        http: httpx.AsyncClient,
        *,
        token: str,
        text: str,
        locale: str = DEFAULT_LOCALE,
    ) -> dict[str, Any]:
        """The greeting shown in a thread that has no messages yet. Meta caps it at 160 chars."""
        text = (text or "").strip()
        if not text:
            raise ValidationError("نص الترحيب مينفعش يكون فاضي.")
        if len(text) > MAX_GREETING_CHARS:
            raise ValidationError(f"نص الترحيب أطول من {MAX_GREETING_CHARS} حرف.")
        return await self._call(
            http,
            "POST",
            "me/messenger_profile",
            token,
            json={"greeting": [{"locale": locale, "text": text}]},
        )

    # ---- get started ----
    async def set_get_started(
        self, http: httpx.AsyncClient, *, token: str, payload: str = "GET_STARTED"
    ) -> dict[str, Any]:
        """The Get Started button. Its payload comes back as a postback when it is pressed."""
        payload = (payload or "").strip() or "GET_STARTED"
        return await self._call(
            http,
            "POST",
            "me/messenger_profile",
            token,
            json={"get_started": {"payload": payload}},
        )

    # ---- persistent menu ----
    async def set_persistent_menu(
        self,
        http: httpx.AsyncClient,
        *,
        token: str,
        items: list[dict[str, Any]],
        locale: str = DEFAULT_LOCALE,
        composer_input_disabled: bool = False,
    ) -> dict[str, Any]:
        """The menu inside the thread. Meta allows 5 items and refuses a bad item shape."""
        if not items:
            raise ValidationError("القائمة مينفعش تكون فاضية.")
        if len(items) > MAX_MENU_ITEMS:
            raise ValidationError(f"القائمة القصوى {MAX_MENU_ITEMS} عناصر.")
        return await self._call(
            http,
            "POST",
            "me/messenger_profile",
            token,
            json={
                "persistent_menu": [
                    {
                        "locale": locale,
                        "composer_input_disabled": bool(composer_input_disabled),
                        "call_to_actions": items,
                    }
                ]
            },
        )

    # ---- ice breakers ----
    async def set_ice_breakers(
        self,
        http: httpx.AsyncClient,
        *,
        token: str,
        questions: list[dict[str, str]],
        locale: str = DEFAULT_LOCALE,
    ) -> dict[str, Any]:
        """The FAQ-style questions above the composer. Meta allows 3, 80 chars each."""
        if not questions:
            raise ValidationError("الأسئلة مينفعش تكون فاضية.")
        if len(questions) > MAX_ICE_BREAKERS:
            raise ValidationError(f"الأسئلة القصوى {MAX_ICE_BREAKERS}.")
        for q in questions:
            if len(str(q.get("question") or "")) > MAX_ICEBREAKER_CHARS:
                raise ValidationError(f"السؤال أطول من {MAX_ICEBREAKER_CHARS} حرف.")
        return await self._call(
            http,
            "POST",
            "me/messenger_profile",
            token,
            json={"ice_breakers": [{"locale": locale, "call_to_actions": questions}]},
        )

    # ---- reading and removing ----
    async def get_profile(
        self, http: httpx.AsyncClient, *, token: str, fields: list[str] | None = None
    ) -> dict[str, Any]:
        """What the Page's Messenger profile currently holds, so a screen shows the truth."""
        params = {"fields": ",".join(fields)} if fields else None
        return await self._call(http, "GET", "me/messenger_profile", token, params=params)

    async def delete_fields(
        self, http: httpx.AsyncClient, *, token: str, fields: list[str]
    ) -> dict[str, Any]:
        """Remove settings Meta has no separate delete endpoint for: it takes a field list."""
        if not fields:
            raise ValidationError("حدد الحقول اللي عايز تشيلها.")
        return await self._call(
            http,
            "DELETE",
            "me/messenger_profile",
            token,
            params={"fields": fields},
        )

    # ---- labels ----
    async def add_labels(
        self, http: httpx.AsyncClient, *, token: str, psid: str, labels: list[str]
    ) -> dict[str, Any]:
        """Attach labels to ONE customer's conversation (Meta's per-PSID custom labels)."""
        if not labels:
            raise ValidationError("مفيش تسميات.")
        return await self._call(
            http, "POST", f"{psid}/custom_labels", token, json={"custom_labels": labels}
        )

    async def remove_labels(
        self, http: httpx.AsyncClient, *, token: str, psid: str, labels: list[str]
    ) -> dict[str, Any]:
        """Remove labels from one conversation: Meta takes them in `fields` on DELETE."""
        if not labels:
            raise ValidationError("مفيش تسميات.")
        return await self._call(
            http,
            "DELETE",
            f"{psid}/custom_labels",
            token,
            params={"fields": labels},
        )


messenger_profile = MessengerProfile()
