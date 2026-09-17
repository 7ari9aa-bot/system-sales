"""OpenAI-compatible HTTP providers.

Thin transport layer ONLY: build the request, parse the response, raise
``ExternalProviderError`` on anything unexpected. No tenant, DB or business
logic lives here — that is the gateway's and the runtime's job.

``_client`` is injectable so tests can pass an ``httpx.AsyncClient`` wired to
``httpx.MockTransport``; production code lets the provider own its client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from app.core.errors import ExternalProviderError

_TIMEOUT_SECONDS = 60.0


@dataclass(slots=True)
class ToolCallRequest:
    """A function call the model asked for (OpenAI tool_calls entry)."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(slots=True)
class ChatCompletionResult:
    content: str | None
    tool_calls: list[ToolCallRequest]
    tokens_in: int
    tokens_out: int
    raw_model: str


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _acquire_client(_client: httpx.AsyncClient | None) -> tuple[httpx.AsyncClient, bool]:
    """Return (client, owned) — owned clients must be closed by the caller."""
    if _client is not None:
        return _client, False
    return httpx.AsyncClient(timeout=_TIMEOUT_SECONDS), True


class AIProvider:
    """POST {base_url}/chat/completions (OpenAI chat-completions schema)."""

    async def chat(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> ChatCompletionResult:
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload: dict = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        client, owned = _acquire_client(_client)
        try:
            try:
                response = await client.post(url, json=payload, headers=_auth_headers(api_key))
            except httpx.HTTPError as exc:
                raise ExternalProviderError(f"chat request failed: {exc}") from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            raise ExternalProviderError(
                f"chat completion failed with HTTP {response.status_code}",
                details={"status_code": response.status_code},
            )

        try:
            body = response.json()
            message = body["choices"][0]["message"]
            raw_calls = message.get("tool_calls") or []
            tool_calls = [
                ToolCallRequest(
                    id=str(entry["id"]),
                    name=str(entry["function"]["name"]),
                    arguments=json.loads(entry["function"].get("arguments") or "{}"),
                )
                for entry in raw_calls
            ]
            usage = body.get("usage") or {}
            return ChatCompletionResult(
                content=message.get("content"),
                tool_calls=tool_calls,
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                raw_model=str(body.get("model") or model),
            )
        except ExternalProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalProviderError(f"malformed chat completion response: {exc}") from exc


class EmbeddingProvider:
    """POST {base_url}/embeddings — returns one vector per input text."""

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        texts: list[str],
        _client: httpx.AsyncClient | None = None,
    ) -> list[list[float]]:
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": texts}

        client, owned = _acquire_client(_client)
        try:
            try:
                response = await client.post(url, json=payload, headers=_auth_headers(api_key))
            except httpx.HTTPError as exc:
                raise ExternalProviderError(f"embedding request failed: {exc}") from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            raise ExternalProviderError(
                f"embedding failed with HTTP {response.status_code}",
                details={"status_code": response.status_code},
            )

        try:
            body = response.json()
            data = body["data"]
            ordered = sorted(data, key=lambda entry: int(entry.get("index") or 0))
            vectors = [[float(x) for x in entry["embedding"]] for entry in ordered]
            if len(vectors) != len(texts):
                raise ValueError(f"expected {len(texts)} vectors, got {len(vectors)}")
            return vectors
        except ExternalProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalProviderError(f"malformed embedding response: {exc}") from exc
