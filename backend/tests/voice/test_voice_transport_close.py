"""Closing a call must not hang on a gateway that never answers the close frame.

Measured on a real session (live_u1_Eor17p3oMtrTCXJLX4DUvaM5v1U1ZF2H): the model
spoke our answer, then ``connection.close()`` blocked until the probe's own
timeout fired. Cleanup that hangs is cleanup that never runs, so the transport
bounds the handshake and drops the socket instead.
"""

from __future__ import annotations

import asyncio

import pytest

from app.platform.voice.runtime import gpt_live_transport
from app.platform.voice.runtime.gpt_live_transport import WebsocketTransport


class HangingConnection:
    """A peer that accepts the close frame and then says nothing."""

    def __init__(self) -> None:
        self.closed = False
        self.aborted = False
        self.transport = self

    async def close(self) -> None:
        self.closed = True
        await asyncio.sleep(30)

    def abort(self) -> None:
        self.aborted = True

    async def send(self, _payload: str) -> None:  # pragma: no cover - not used here
        raise AssertionError("no frame should be sent by close()")


class PoliteConnection(HangingConnection):
    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_a_hanging_close_is_aborted_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(gpt_live_transport, "CLOSE_TIMEOUT_SECONDS", 0.05)
    connection = HangingConnection()
    transport = WebsocketTransport(connection)

    await asyncio.wait_for(transport.close(), timeout=2)

    assert connection.closed is True
    assert connection.aborted is True


@pytest.mark.asyncio
async def test_a_normal_close_is_not_aborted(monkeypatch):
    monkeypatch.setattr(gpt_live_transport, "CLOSE_TIMEOUT_SECONDS", 0.05)
    connection = PoliteConnection()
    transport = WebsocketTransport(connection)

    await transport.close()

    assert connection.closed is True
    assert connection.aborted is False
