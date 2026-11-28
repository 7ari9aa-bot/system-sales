"""HTTP client for the ETA eReceipt API (identity + submission + status).

Rules from the authority's Integration Practices / Governance pages, all enforced here:

* Cache the access token (valid ~1h). Fetching one per call is a named anti-pattern the
  authority throttles and may block.
* Submit receipts in batches and treat any 2xx as final: never resubmit an accepted batch (an
  identical payload within 10 minutes is a 422 ``DuplicateSubmission`` anyway).
* 429 -> wait *longer than* ``Retry-After``; 503 -> retry after 1-3 s; 422 duplicate -> wait
  ``Retry-After``. Everything else is a permanent error for that batch.
* Poll a submission via ``GET .../receiptsubmissions/{id}/details`` only; never poll receipts
  one by one.

The client is transport-agnostic: pass an ``httpx.AsyncClient`` (tests pass a ``MockTransport``).
It does no database work and never logs credentials.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.applications.apparel.modules.einvoice.providers.eta.builder import dumps

# Refresh this long before the token really expires, so a call never races the expiry.
_TOKEN_SAFETY_SECONDS = 60
_MAX_ATTEMPTS = 4

ENV_PREPROD = "preprod"
ENV_PROD = "prod"

_ENDPOINTS: dict[str, tuple[str, str, str]] = {
    ENV_PREPROD: (
        "https://id.preprod.eta.gov.eg",
        "https://api.preprod.invoicing.eta.gov.eg",
        "https://preprod.invoicing.eta.gov.eg",
    ),
    ENV_PROD: (
        "https://id.eta.gov.eg",
        "https://api.invoicing.eta.gov.eg",
        "https://invoicing.eta.gov.eg",
    ),
}


# Error codes the identity service (POST /connect/token) can return, per the SDK.
_IDENTITY_ERRORS = frozenset(
    {
        "unauthorized_client",
        "invalid_posserial",
        "invalid_pososversion",
        "invalid_posmodelframework",
        "invalid_presharedkey",
        "unsupported_grant_type",
        "invalid_scope",
        "invalid_request",
        "invalid_clientsecret",
    }
)


class EtaError(Exception):
    """Base class; ``retryable`` tells the caller whether the same batch may be sent again."""

    retryable = False

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class EtaAuthError(EtaError):
    """Credentials were refused. Retrying with the same credentials cannot help."""


class EtaPermanentError(EtaError):
    """The authority refused the request itself (bad structure, wrong submitter, too big)."""


class EtaTransientError(EtaError):
    """Throttled, overloaded, duplicate-window or network trouble: safe to retry later."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float = 0.0, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


@dataclass(frozen=True)
class EtaCredentials:
    client_id: str
    client_secret: str
    pos_serial: str
    pos_os_version: str
    pos_model_framework: str
    preshared_key: str


@dataclass(frozen=True)
class EtaEndpoints:
    identity: str
    api: str
    portal: str

    @classmethod
    def for_environment(cls, environment: str) -> EtaEndpoints:
        try:
            identity, api, portal = _ENDPOINTS[environment]
        except KeyError:
            raise ValueError(f"unknown ETA environment {environment!r}") from None
        return cls(identity, api, portal)


@dataclass(frozen=True)
class AcceptedDocument:
    uuid: str
    long_id: str
    receipt_number: str


@dataclass(frozen=True)
class RejectedDocument:
    receipt_number: str
    uuid: str
    message: str
    details: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SubmissionResponse:
    submission_uuid: str
    accepted: tuple[AcceptedDocument, ...] = ()
    rejected: tuple[RejectedDocument, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def _retry_after(resp: httpx.Response) -> float:
    try:
        return max(0.0, float(resp.headers.get("Retry-After", "0")))
    except ValueError:
        return 0.0


def _body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


class EtaClient:
    """One client per (environment, device). Not shared across tenants."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        endpoints: EtaEndpoints,
        credentials: EtaCredentials,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._ep = endpoints
        self._cred = credentials
        self._clock = clock
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._login_lock = asyncio.Lock()

    @property
    def portal_base_url(self) -> str:
        return self._ep.portal

    # ---- authentication -----------------------------------------------------------
    async def access_token(self, *, force_refresh: bool = False) -> str:
        async with self._login_lock:
            if not force_refresh and self._token and self._clock() < self._token_expires_at:
                return self._token
            return await self._login()

    async def _login(self) -> str:
        c = self._cred
        resp = await self._request(
            "POST",
            f"{self._ep.identity}/connect/token",
            headers={
                "posserial": c.pos_serial,
                "pososversion": c.pos_os_version,
                "posmodelframework": c.pos_model_framework,
                "presharedkey": c.preshared_key,
            },
            data={
                "grant_type": "client_credentials",
                "client_id": c.client_id,
                "client_secret": c.client_secret,
            },
            auth=False,
        )
        payload = _body(resp)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise EtaAuthError("identity service returned no access_token", status=resp.status_code)
        ttl = float(payload.get("expires_in", 3600))
        self._token = token
        self._token_expires_at = self._clock() + max(0.0, ttl - _TOKEN_SAFETY_SECONDS)
        return token

    # ---- submission ---------------------------------------------------------------
    async def submit_receipts(
        self, receipts: list[dict[str, Any]], *, signatures: list[dict[str, str]] | None = None
    ) -> SubmissionResponse:
        """POST one batch of already-built receipt dicts (see ``builder.build_receipt``).

        The body is produced by ``builder.dumps`` so the numbers on the wire are exactly the
        five-decimal values the UUID was computed over. Letting ``httpx`` serialise a dict
        here would go through float and could change them.
        """
        body: dict[str, Any] = {"receipts": receipts}
        if signatures:
            body["signatures"] = signatures
        return await self.submit_raw(dumps(body).encode("utf-8"))

    async def submit_raw(self, body: bytes) -> SubmissionResponse:
        """POST an already-serialised batch *byte for byte*.

        This is the path real issuing uses: the stored receipt text is the single source of
        truth, so what the authority hashes is exactly what was stored and printed. Re-parsing
        and re-serialising a stored receipt could reorder keys or reformat numbers and silently
        invalidate its UUID.
        """
        resp = await self._request(
            "POST",
            f"{self._ep.api}/api/v1/receiptsubmissions",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        data = _body(resp)
        if not isinstance(data, dict):
            raise EtaPermanentError("unexpected submission response", status=resp.status_code)
        return SubmissionResponse(
            submission_uuid=str(data.get("submissionUUID", "")),
            accepted=tuple(
                AcceptedDocument(
                    uuid=str(d.get("uuid", "")),
                    long_id=str(d.get("longId", "")),
                    receipt_number=str(d.get("receiptNumber", "")),
                )
                for d in data.get("acceptedDocuments") or []
            ),
            rejected=tuple(_rejected(d) for d in data.get("rejectedDocuments") or []),
            raw=data,
        )

    async def get_submission(self, submission_uuid: str, *, page_size: int = 100) -> dict[str, Any]:
        """Status of one submission (the supported way to follow up; never poll per receipt)."""
        resp = await self._request(
            "GET",
            f"{self._ep.api}/api/v1/receiptsubmissions/{submission_uuid}/details",
            params={"PageNo": 1, "PageSize": page_size},
        )
        data = _body(resp)
        return data if isinstance(data, dict) else {"raw": data}

    # ---- plumbing -----------------------------------------------------------------
    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> httpx.Response:
        last: EtaError | None = None
        refreshed = False
        for attempt in range(_MAX_ATTEMPTS):
            hdrs = dict(headers or {})
            if auth:
                hdrs["Authorization"] = f"Bearer {await self.access_token()}"
            try:
                resp = await self._http.request(
                    method, url, headers=hdrs, data=data, content=content, params=params
                )
            except httpx.TransportError as exc:
                last = EtaTransientError(f"network error: {type(exc).__name__}")
                await self._sleep(min(2.0 * (attempt + 1), 8.0))
                continue

            if resp.status_code < 300:
                return resp
            err = self._classify(resp)
            if resp.status_code == 401 and auth and not refreshed:
                refreshed = True  # token revoked early: log in once more, then give up
                self._token = None
                last = err
                continue
            if not isinstance(err, EtaTransientError):
                raise err
            last = err
            if attempt < _MAX_ATTEMPTS - 1:
                # 429: wait LONGER than Retry-After (the authority's instruction); 503: 1-3 s.
                wait = err.retry_after + 1.0 if err.retry_after else min(1.0 + attempt, 3.0)
                await self._sleep(wait)
        assert last is not None
        raise last

    @staticmethod
    def _classify(resp: httpx.Response) -> EtaError:
        status, body = resp.status_code, _body(resp)
        text = f"HTTP {status}: {body if isinstance(body, str) else body.get('error') or body}"
        code = str(body.get("error", "")) if isinstance(body, dict) else ""
        # Only the identity service's own error vocabulary means "credentials refused". A 400
        # from the submission API (BadStructure, MaximumSizeExceeded, ...) is about the payload.
        if code in _IDENTITY_ERRORS or status == 401:
            return EtaAuthError(text, status=status, body=body)
        if status in (429, 503):
            return EtaTransientError(text, retry_after=_retry_after(resp), status=status, body=body)
        if status == 422 and "Duplicate" in str(body):
            return EtaTransientError(text, retry_after=_retry_after(resp), status=status, body=body)
        if status >= 500:
            return EtaTransientError(text, status=status, body=body)
        return EtaPermanentError(text, status=status, body=body)


def _rejected(d: dict[str, Any]) -> RejectedDocument:
    err = d.get("error") or {}
    return RejectedDocument(
        receipt_number=str(d.get("receiptNumber", "")),
        uuid=str(d.get("uuid", "")),
        message=str(err.get("message", "")),
        details=tuple(err.get("details") or ()),
    )
