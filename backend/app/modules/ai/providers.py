"""OpenAI-compatible HTTP providers.

Thin transport layer ONLY: build the request, parse the response, raise
``ExternalProviderError`` on anything unexpected. No tenant, DB or business
logic lives here — that is the gateway's and the runtime's job.

``_client`` is injectable so tests can pass an ``httpx.AsyncClient`` wired to
``httpx.MockTransport``; production code lets the provider own its client.

Egress (S6): every transport validates its ``base_url`` through
:func:`assert_provider_base_url` before the request is built — the URL can
arrive from tenant-supplied ``model_configs``, so a non-public target is
refused here rather than becoming an open proxy.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import httpx

from app.core.errors import ExternalProviderError, ValidationError
from app.core.net_guard import assert_public_url as _net_guard_assert_public_url

_TIMEOUT_SECONDS = 120.0  # reasoning models with tool schemas can be slow
_VISION_TIMEOUT_SECONDS = 15.0  # the image tool budget (§19) is 8s; transport headroom


def assert_provider_base_url(url: str) -> str:
    """Egress guard for AI provider base URLs (S6) — net_guard, scoped to this file.

    The base_url can arrive from a tenant-supplied ``model_configs`` row, so
    the AI transports are exactly the open-proxy surface ``app.core.net_guard``
    exists for: without this check a tenant could point us at
    ``http://169.254.169.254`` (cloud metadata), ``http://localhost:8000``
    (our own API, past the edge) or any RFC1918 host and have us POST a
    deployment-scoped bearer key plus the prompt to it. Every external call
    this module makes — chat, embeddings, and both vision transports — passes
    through this function BEFORE the request is built.

    The rules are net_guard's own (same function, one source of truth):
    http/https only, no embedded credentials, no localhost/metadata hostname,
    and no literal or resolved private/loopback/link-local address.

    The ONE documented delta: a hostname that does not resolve AT ALL is
    allowed through — there is no address to smuggle a request to, and the
    HTTP connect that follows immediately fails closed on its own. net_guard's
    DNS-fail-closed rule targets webhook URLs that are STORED and resolved
    later at send time; here the connection happens in the next statement, so
    an unresolvable name can never complete the egress.
    """
    if not url or not isinstance(url, str):
        raise ValidationError("provider base_url is required")
    try:
        return _net_guard_assert_public_url(url)
    except ValidationError as exc:
        if "did not resolve" in str(exc):
            return url
        raise


@dataclass(slots=True)
class ToolCallRequest:
    """A function call the model asked for (OpenAI tool_calls entry)."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    thought_signature: str | None = None  # Gemini 3.x: echo back per call


@dataclass(slots=True)
class ChatCompletionResult:
    content: str | None
    tool_calls: list[ToolCallRequest]
    tokens_in: int
    tokens_out: int
    raw_model: str
    # Gemini 3.x: must be echoed back on the assistant tool-call message,
    # otherwise the next turn fails with 400 (missing thought_signature).
    thought_signature: str | None = None


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _acquire_client(
    _client: httpx.AsyncClient | None,
    timeout: float = _TIMEOUT_SECONDS,
) -> tuple[httpx.AsyncClient, bool]:
    """Return (client, owned) — owned clients must be closed by the caller."""
    if _client is not None:
        return _client, False
    return httpx.AsyncClient(timeout=timeout), True


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
        # S6 egress guard FIRST: the URL is built from it, so a blocked host
        # never even reaches a constructed request string.
        url = f"{assert_provider_base_url(base_url).rstrip('/')}/chat/completions"
        payload: dict = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        client, owned = _acquire_client(_client)
        try:
            response = None
            for attempt in range(2):  # one retry for transient provider load
                try:
                    response = await client.post(url, json=payload, headers=_auth_headers(api_key))
                except httpx.HTTPError as exc:
                    if attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    raise ExternalProviderError(f"chat request failed: {exc}") from exc
                if response.status_code in (429, 502, 503) and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                break
            assert response is not None
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            raise ExternalProviderError(
                f"chat completion failed with HTTP {response.status_code}: {response.text[:300]}",
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
                    thought_signature=(entry.get("extra_content") or {})
                    .get("google", {})
                    .get("thought_signature"),
                )
                for entry in raw_calls
            ]
            usage = body.get("usage") or {}
            google_extra = (message.get("extra_content") or {}).get("google") or {}
            return ChatCompletionResult(
                content=message.get("content"),
                tool_calls=tool_calls,
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                raw_model=str(body.get("model") or model),
                thought_signature=google_extra.get("thought_signature"),
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
        dimensions: int | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> list[list[float]]:
        # S6 egress guard — embeddings carry customer text too.
        url = f"{assert_provider_base_url(base_url).rstrip('/')}/embeddings"
        payload: dict = {"model": model, "input": texts}
        if dimensions is not None:
            payload["dimensions"] = dimensions

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


# --------------------------------------------------------------------------
# Vision-stack transports (Customer Agent §12). These two are NOT
# OpenAI-compatible: the vision embedding speaks DashScope's native schema and
# the reranker speaks Jina's. Same discipline as above — build request, parse
# response, raise ExternalProviderError — the vision pipeline's decision logic
# lives in the agent package, never here.


@dataclass(slots=True)
class MultimodalContent:
    """One embedding input item: text, image, or both together.

    ``image`` is an https URL or a data URL — the provider fetches both, so
    nothing here ever carries a local path or tenant storage credentials.
    """

    text: str | None = None
    image: str | None = None

    def payload(self) -> dict[str, str]:
        item: dict[str, str] = {}
        if self.text is not None:
            item["text"] = self.text
        if self.image is not None:
            item["image"] = self.image
        if not item:
            raise ValueError("MultimodalContent needs a text or an image")
        return item


class MultimodalEmbeddingProvider:
    """POST {base_url}/services/embeddings/multimodal-embedding/multimodal-embedding.

    DashScope Model Studio native schema. ``tongyi-embedding-vision-flash``
    answers text-only, image-only and image+text items alike with a fixed-width
    vector (768 for this model) — one vector per input item, so a product image
    and its caption can land in ONE vector space.
    """

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        contents: list[MultimodalContent],
        expected_dimensions: int | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> list[list[float]]:
        if not contents:
            raise ValueError("contents must not be empty")
        # S6 egress guard — the vision embedding ships images and captions.
        url = (
            f"{assert_provider_base_url(base_url).rstrip('/')}"
            "/services/embeddings/multimodal-embedding/multimodal-embedding"
        )
        payload = {
            "model": model,
            "input": {"contents": [item.payload() for item in contents]},
        }

        client, owned = _acquire_client(_client, _VISION_TIMEOUT_SECONDS)
        try:
            try:
                response = await client.post(url, json=payload, headers=_auth_headers(api_key))
            except httpx.HTTPError as exc:
                raise ExternalProviderError(f"vision embedding request failed: {exc}") from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            # DashScope native errors carry {"code", "message"} — surface the
            # message, "Model not exist." beats a bare status code.
            try:
                detail = response.json().get("message") or response.text[:200]
            except ValueError:
                detail = response.text[:200]
            raise ExternalProviderError(
                f"vision embedding failed with HTTP {response.status_code}: {detail}",
                details={"status_code": response.status_code},
            )

        try:
            body = response.json()
            entries = body["output"]["embeddings"]
            ordered = sorted(entries, key=lambda entry: int(entry.get("index") or 0))
            vectors = [[float(x) for x in entry["embedding"]] for entry in ordered]
            if len(vectors) != len(contents):
                raise ValueError(f"expected {len(contents)} vectors, got {len(vectors)}")
            if expected_dimensions is not None:
                dims = {len(v) for v in vectors}
                if dims != {expected_dimensions}:
                    raise ValueError(
                        f"expected {expected_dimensions}-dim vectors, got {sorted(dims)}"
                    )
            return vectors
        except ExternalProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalProviderError(f"malformed vision embedding response: {exc}") from exc


@dataclass(slots=True)
class RerankResult:
    """One scored document — ``index`` points into the CALLER's input order."""

    index: int
    score: float


class RerankerProvider:
    """POST {base_url}/rerank (Jina schema).

    Query and documents may each be text or an image (https/data URL), so the
    vision pipeline reranks the customer's photo against candidate product
    photos directly — no OCR round-trip in between. Results come back scored
    descending with their ORIGINAL input indexes preserved, because the caller
    maps indexes back to product ids it fetched itself.
    """

    async def rerank(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        query: str,
        documents: list[dict[str, str]],
        top_n: int | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> list[RerankResult]:
        if not documents:
            raise ValueError("documents must not be empty")
        # S6 egress guard — the reranker ships candidate images and text.
        url = f"{assert_provider_base_url(base_url).rstrip('/')}/rerank"
        payload: dict = {"model": model, "query": query, "documents": documents}
        if top_n is not None:
            payload["top_n"] = top_n

        client, owned = _acquire_client(_client, _VISION_TIMEOUT_SECONDS)
        try:
            try:
                response = await client.post(url, json=payload, headers=_auth_headers(api_key))
            except httpx.HTTPError as exc:
                raise ExternalProviderError(f"rerank request failed: {exc}") from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            raise ExternalProviderError(
                f"rerank failed with HTTP {response.status_code}: {response.text[:200]}",
                details={"status_code": response.status_code},
            )

        try:
            body = response.json()
            results = [
                RerankResult(index=int(entry["index"]), score=float(entry["relevance_score"]))
                for entry in body["results"]
            ]
            # The decision engine reads the ABSOLUTE score of rank 1 and the gap
            # to rank 2, so the ordering contract is enforced here, not hoped
            # for — and scores outside [0, 1] would silently invalidate every
            # threshold, so they fail loudly instead.
            results.sort(key=lambda r: r.score, reverse=True)
            if any(r.score < 0.0 or r.score > 1.0 for r in results):
                raise ValueError("relevance_score outside [0, 1]")
            return results
        except ExternalProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalProviderError(f"malformed rerank response: {exc}") from exc
