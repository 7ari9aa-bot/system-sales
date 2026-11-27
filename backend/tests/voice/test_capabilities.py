"""Opening a voice session: the entry scope versus the data scopes."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import PermissionDeniedError
from app.modules.voice.security.capabilities import (
    ENTRY_SCOPE,
    AuthenticationLevel,
    ChannelType,
    PrincipalType,
    resolve_capability,
)

def test_entering_a_voice_session_needs_no_shop_read_scope():
    """«assistant:use» opens the call; reading data still needs a read scope.

    Before this, opening a voice session demanded a data scope such as orders:read — the exact
    coupling the architecture decision forbids. The session now opens on the entry scope alone,
    and its capability carries nothing else, so every tool still refuses.
    """
    capability = resolve_capability(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=None,
        held_scopes=frozenset({ENTRY_SCOPE}),
        channel=ChannelType.WEB_VOICE,
    )

    assert capability.scopes == frozenset({ENTRY_SCOPE})
    assert capability.authentication_level is AuthenticationLevel.VERIFIED


def test_a_user_holding_nothing_is_still_refused_a_voice_session():
    with pytest.raises(PermissionDeniedError):
        resolve_capability(
            principal_type=PrincipalType.MERCHANT_USER,
            principal_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            workspace_id=None,
            held_scopes=frozenset({"billing:write"}),
            channel=ChannelType.WEB_VOICE,
        )
