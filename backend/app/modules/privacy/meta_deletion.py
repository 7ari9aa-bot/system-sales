"""Meta's "data deletion request callback": verify the signed request, file a deletion request.

Meta posts `signed_request=<sig>.<payload>` (form-encoded) when a person removes the app from their
Facebook or Instagram settings. `sig` is the base64url HMAC-SHA256 of the payload under the app
secret; the payload is base64url JSON carrying the person's app-scoped `user_id`.

Two decisions worth keeping:

* The callback only OPENS a `delete` data-subject request. It never runs the (irreversible)
  deletion itself: a signature check is the only thing between the open internet and a customer's
  erasure, so the merchant executes the request from the existing privacy screen. Meta only needs
  a status URL and a confirmation code, and both are served from the request row.
* An id that matches no customer, or more than one, files nothing but still answers with a code,
  so the callback cannot be used to learn whether a person is a customer.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InvalidSignedRequest(ValueError):
    """The request is malformed or was not signed with our app secret."""


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InvalidSignedRequest("not base64url") from exc


def parse_signed_request(signed_request: str, app_secret: str) -> dict:
    """The payload of a Meta signed request, or raise when it cannot be trusted."""
    if not app_secret:
        # Fail closed: without a secret nothing can be verified, so nothing is believed.
        raise InvalidSignedRequest("no app secret configured")
    sig_part, dot, payload_part = (signed_request or "").partition(".")
    if not dot or not sig_part or not payload_part:
        raise InvalidSignedRequest("malformed signed_request")
    expected = hmac.new(app_secret.encode(), payload_part.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(sig_part), expected):
        raise InvalidSignedRequest("bad signature")
    try:
        data = json.loads(_b64url_decode(payload_part))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSignedRequest("payload is not JSON") from exc
    if not isinstance(data, dict):
        raise InvalidSignedRequest("payload is not an object")
    if str(data.get("algorithm", "")).upper() != "HMAC-SHA256":
        raise InvalidSignedRequest("unsupported algorithm")
    return data


@dataclass(frozen=True)
class FiledDeletion:
    confirmation_code: str
    filed: bool


async def file_deletion_request(session: AsyncSession, meta_user_id: str) -> FiledDeletion:
    """Open a pending `delete` request for the one customer behind `meta_user_id`, if any."""
    from app.core.db import bind_tenant
    from app.modules.privacy.service import DataRequestService

    row = (
        await session.execute(
            text("SELECT tenant_id, customer_id FROM public.resolve_meta_user_customer(:u)"),
            {"u": meta_user_id},
        )
    ).first()
    if row is None:
        return FiledDeletion(confirmation_code=uuid.uuid4().hex, filed=False)
    await bind_tenant(session, row.tenant_id)
    request = await DataRequestService.create(
        session, row.tenant_id, customer_id=row.customer_id, request_type="delete"
    )
    request.payload_scope = {"source": "meta_data_deletion_callback"}
    await session.flush()
    return FiledDeletion(confirmation_code=request.id.hex, filed=True)


async def deletion_status(session: AsyncSession, confirmation_code: str) -> str:
    """`completed` / `pending` / `unknown` for a code we handed out. Reveals nothing else."""
    try:
        request_id = uuid.UUID(confirmation_code)
    except ValueError:
        return "unknown"
    row = (
        await session.execute(
            text("SELECT status FROM public.meta_deletion_status(:i)"), {"i": request_id}
        )
    ).first()
    if row is None:
        return "unknown"
    return "completed" if row.status == "completed" else "pending"
