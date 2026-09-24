"""§67 write paths: a security event must LAND, and must not carry PII.

`record_security_event` (``app/modules/platform/security_events.py``) exists
because the §67 trail was silently empty: the auth failures raise immediately
after recording, so a row added to the REQUEST transaction was rolled back with
the 401. Its module docstring also states the redaction rule — coarse proxy,
never a full email.

These two writers were left behind by that fix, and the read surface added in
``test_security_events_read_surface.py`` made them worth finding: a query over a
trail that drops rows and stores emails is not an audit trail.

* ``TenantService.accept_invitation`` still builds ``SecurityEvent(...)`` and
  ``session.add``s it on the request transaction, then raises ``ValidationError``
  — the expired-invitation event can never be read back.
* ``AuthService.login`` writes ``details={"email": user.email}`` for a disabled
  account, while the sibling ``login_failure`` two lines above it correctly
  writes ``{"email_domain": ...}``.

Both are tested without a database: the spy captures what the code ASKS the
canonical writer to persist, which is exactly the contract the transaction and
the redaction rule live on.
"""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import PermissionDeniedError, ValidationError
from app.core.security import hash_password
from app.modules.identity import service
from app.modules.identity.models import User
from app.modules.identity.service import AuthService, TenantService
from app.modules.platform.models import SecurityEvent


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RecordingSession:
    """The minimum AsyncSession surface these two paths touch, plus what it adds."""

    def __init__(self, value) -> None:
        self._value = value
        self.added: list = []

    async def execute(self, *_args, **_kwargs):
        return _Result(self._value)

    def add(self, obj) -> None:
        self.added.append(obj)


@pytest.fixture
def recorded(monkeypatch):
    """Capture what a service asks the canonical §67 writer to persist."""
    calls: list[dict] = []

    async def _spy(
        event_type: str,
        *,
        details: dict | None = None,
        ip: str | None = None,
        tenant_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        calls.append(
            {
                "event_type": event_type,
                "details": details,
                "ip": ip,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
            }
        )

    monkeypatch.setattr(service, "_record_security_event", _spy)
    return calls


# ------------------------------------------------ expired invitations ----


def _expired_invitation():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="someone@acme.test",
        token="tok-expired",
        status="pending",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )


async def test_an_expired_invitation_is_not_also_added_to_the_request_session(
    recorded,
) -> None:
    """The row the caller raises past must not live on the caller's transaction.

    ``session.add`` here is the bug: the ``ValidationError`` below rolls it back,
    so the event is written and then un-written and the §67 trail stays empty.
    """
    invitation = _expired_invitation()
    db = _RecordingSession(invitation)

    with pytest.raises(ValidationError):
        await TenantService.accept_invitation(
            db, token=invitation.token, password="P-verify-me", full_name="Someone"
        )

    assert not [row for row in db.added if isinstance(row, SecurityEvent)], (
        "invitation_expired was added to the request transaction — it rolls back "
        "with the ValidationError and never reaches security_events"
    )


async def test_an_expired_invitation_lands_on_the_canonical_writer(recorded) -> None:
    invitation = _expired_invitation()
    db = _RecordingSession(invitation)

    with pytest.raises(ValidationError):
        await TenantService.accept_invitation(
            db, token=invitation.token, password="P-verify-me", full_name="Someone"
        )

    events = [c for c in recorded if c["event_type"] == "invitation_expired"]
    assert len(events) == 1, f"expected one invitation_expired event, got {recorded}"
    # The canonical writer binds the tenant GUC on its own transaction; without
    # a tenant_id on a FORCE-RLS table the row is refused and vanishes silently.
    assert events[0]["tenant_id"] == invitation.tenant_id
    # Same redaction rule as the disabled-account event beside it.
    details = events[0]["details"] or {}
    assert "someone@acme.test" not in repr(details)
    assert details.get("email_domain") == "acme.test"
    assert details.get("invitation_id") == str(invitation.id)


# ------------------------------------------------------ disabled accounts ----


async def test_a_disabled_account_login_records_no_full_email(recorded) -> None:
    user = User(
        id=uuid.uuid4(),
        email="person@acme.test",
        full_name="Person",
        password_hash=hash_password("P-password"),
        is_active=False,
    )
    db = _RecordingSession(user)

    with pytest.raises(PermissionDeniedError):
        await AuthService.login(db, email="person@acme.test", password="P-password")

    events = [c for c in recorded if c["event_type"] == "account_disabled_login"]
    assert len(events) == 1, f"expected one event, got {recorded}"
    details = events[0]["details"] or {}
    assert "person@acme.test" not in repr(details), (
        "the §67 trail carries a full email address; the writer's own rule is a "
        "coarse proxy (domain), as `login_failure` beside it already does"
    )
    assert details.get("email_domain") == "acme.test"
