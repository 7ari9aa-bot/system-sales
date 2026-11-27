"""The socket to GPT-Live, and nothing else.

``GptLiveProvider`` is written against a transport protocol so it can be tested
without a network. This is the real implementation: one websocket to the AI
Gateway, authenticated with the gateway key, carrying JSON frames in both
directions. It holds no business logic — the provider decides what to send.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveUnavailable


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
        await self._connection.close()


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
