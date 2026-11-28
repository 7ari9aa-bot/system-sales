"""The socket to GPT-Live, and nothing else.

``GptLiveProvider`` is written against a transport protocol so it can be tested
without a network. This is the real implementation: one websocket to the AI
Gateway, authenticated with the gateway key, carrying JSON frames in both
directions. It holds no business logic — the provider decides what to send.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.platform.voice.runtime.gpt_live import GptLiveConfig, GptLiveUnavailable

#: How long to wait for the gateway's half of the close handshake. A close that
#: hangs must not hang the call's cleanup: the caller has already stopped paying
#: attention, and the socket is ours to drop.
CLOSE_TIMEOUT_SECONDS = 3.0


class WebsocketTransport:
    """A connected Live session over ``websockets``."""

    def __init__(self, connection) -> None:
        self._connection = connection

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._connection.send(json.dumps(payload))

    async def recv_event(self) -> dict[str, Any]:
        raw = await self._connection.recv()
        return json.loads(raw)

    async def close(self) -> None:
        """Close the socket without waiting forever for the peer.

        Measured on a real session: the gateway did not always answer the close
        frame, so ``connection.close()`` blocked until the caller gave up. A call
        that ends must end, so after the timeout the socket is aborted instead.
        """
        try:
            await asyncio.wait_for(self._connection.close(), timeout=CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            transport = getattr(self._connection, "transport", None)
            if transport is not None:
                transport.abort()


async def connect(config: GptLiveConfig) -> WebsocketTransport:
    """Open the gateway socket. Imported lazily so the adapter tests need no socket lib."""
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - uvicorn[standard] provides it
        raise GptLiveUnavailable("the websockets client is not installed") from exc
    try:
        connection = await websockets.connect(
            config.url,
            additional_headers={"Authorization": f"Bearer {config.api_key}"},
            max_size=None,
        )
    except Exception as exc:  # noqa: BLE001 - any connect failure means no call
        raise GptLiveUnavailable("could not reach the voice gateway") from exc
    return WebsocketTransport(connection)


async def transport_factory(config: GptLiveConfig) -> WebsocketTransport:
    """The callable ``GptLiveProvider`` expects."""
    return await connect(config)
