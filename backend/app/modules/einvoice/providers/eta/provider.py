"""Egyptian Tax Authority (ETA) eReceipt provider.

Adapts the shared ``EInvoiceProvider`` contract (shaped by ZATCA) onto the ETA-specific core:
``context.to_eta_input`` -> ``builder.build_receipt`` -> ``validator`` -> ``client``.

How the shared contract maps onto ETA:

* ``generate_document``: builds and *locally validates* the receipt. A receipt that the
  authority would reject is refused here, at the till, with ``EtaValidationError``.
* ``sign_document``: ETA chains receipts by ``previousUUID`` instead of ZATCA's ICV/PIH. The
  receipt's own UUID becomes ``invoice_hash`` and ``pih``/``last_pih`` hold the *previous
  receipt's UUID*, so the service's existing device-row lock + chain bookkeeping keeps working
  without a schema change. ``icv`` is just a local sequence number. ``signature`` is empty:
  CAdES-BES signing needs the taxpayer's certificate and is NOT implemented yet (see
  ``signer.py``).
* ``submit``: sends to the authority only when the device is configured for it
  (``credentials['eta']`` present). Otherwise the receipt is stored as ``pending`` and nothing
  is claimed to have been reported. The old code returned "reported" without any network call.
* ``check_status``: reads the real submission status; it never invents ``VALID``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from app.modules.einvoice.ports import (
    EInvoiceContext,
    EInvoiceProvider,
    GeneratedPayload,
    SignedPayload,
    SubmissionResult,
)
from app.modules.einvoice.providers.eta.builder import build_receipt, dumps
from app.modules.einvoice.providers.eta.calc import q5
from app.modules.einvoice.providers.eta.client import (
    EtaAuthError,
    EtaClient,
    EtaCredentials,
    EtaEndpoints,
    EtaError,
    EtaTransientError,
)
from app.modules.einvoice.providers.eta.context import device_profile, to_eta_input
from app.modules.einvoice.providers.eta.notifications import stored_status
from app.modules.einvoice.providers.eta.qr import build_qr_payload
from app.modules.einvoice.providers.eta.validator import (
    Issue,
    check_document_consistency,
    validate_receipt,
)

if TYPE_CHECKING:
    from app.modules.einvoice.models import EInvoiceDevice

# Words this provider reports for a submission. ``stored_status`` maps them onto the values the
# documents table accepts (pending is stored as "signed", for instance).
STATUS_PENDING = "pending"  # built + stored, not (yet) accepted by the authority
STATUS_SUBMITTED = "submitted"  # authority returned 202 and accepted the document
STATUS_REJECTED = "rejected"  # authority returned the document as rejected
STATUS_FAILED = "failed"  # could not reach / be authenticated; safe to retry later


class EtaValidationError(ValueError):
    """The receipt would be rejected by the authority; ``issues`` says why."""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("; ".join(f"{i.code} {i.path}: {i.message}" for i in issues))
        self.issues = issues


class EtaEInvoiceProvider(EInvoiceProvider):
    """ETA (Egypt) eReceipt provider."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._sleep = sleep  # injectable so tests never really wait out a back-off
        self._http = http  # injectable for tests; created per call otherwise
        self._clock = clock  # "now" for the not-in-the-future rule; injectable so tests are stable

    @property
    def provider_type(self) -> str:
        return "eta"

    # ------------------------------------------------------------------------------
    async def generate_document(self, context: EInvoiceContext) -> GeneratedPayload:
        """Build the receipt. Needs the device profile, supplied via ``context.extras``."""
        device = context.extras.get("_device")
        if device is None:
            raise EtaValidationError(
                [Issue("ETA-L-000", "device", "ETA issuing needs the device (extras['_device'])")]
            )
        receipt_in = to_eta_input(context, device, previous_uuid=device.last_pih or "")
        issues = validate_receipt(receipt_in, now=self._clock())
        if issues:
            raise EtaValidationError(issues)
        doc = build_receipt(receipt_in)
        problems = check_document_consistency(doc)
        if problems:  # a builder bug, never user error: fail loudly rather than submit it
            raise EtaValidationError(problems)
        raw = dumps(doc)
        return GeneratedPayload(
            raw_content=raw,
            content_type="application/json",
            digest_hash=doc["header"]["uuid"],
        )

    async def sign_document(
        self,
        context: EInvoiceContext,
        payload: GeneratedPayload,
        device: EInvoiceDevice,
    ) -> SignedPayload:
        doc = json.loads(payload.raw_content)
        receipt_uuid = doc["header"]["uuid"]
        profile = device_profile(device, (context.extras or {}).get("store_profile"))
        portal = EtaEndpoints.for_environment(profile.environment or "preprod").portal
        qr = build_qr_payload(
            portal_base_url=portal,
            receipt_uuid=receipt_uuid,
            issued_at=context.issued_at,
            total_amount=q5(context.grand_total),
            issuer_rin=doc["seller"]["rin"],
        )
        return SignedPayload(
            raw_content=payload.raw_content,
            content_type="application/json",
            invoice_hash=receipt_uuid,
            pih=doc["header"]["previousUUID"],
            icv=(device.icv_counter or 0) + 1,
            signature="",  # CAdES-BES needs the taxpayer certificate: not implemented
            qr_code=qr,
        )

    async def submit(self, signed: SignedPayload, device: EInvoiceDevice) -> SubmissionResult:
        cfg = (device.credentials or {}).get("eta")
        if not cfg:
            # Not onboarded with the authority: keep the receipt, claim nothing.
            return SubmissionResult(
                success=False,
                status=stored_status(STATUS_PENDING),
                authority_uuid=None,
                warnings=["ETA credentials are not configured; receipt stored, not submitted"],
                raw_response={},
            )
        doc = json.loads(signed.raw_content)
        try:
            # The stored text goes out byte for byte (see EtaClient.submit_raw).
            body = ('{"receipts":[' + signed.raw_content + "]}").encode("utf-8")
            resp = await self._client(device, cfg).submit_raw(body)
        except (EtaAuthError, EtaTransientError) as exc:
            return SubmissionResult(
                success=False,
                status=stored_status(STATUS_FAILED),
                errors=[str(exc)],
                raw_response={},
            )
        except EtaError as exc:
            return SubmissionResult(
                success=False,
                status=stored_status(STATUS_REJECTED),
                errors=[str(exc)],
                raw_response={},
            )
        if resp.rejected:
            errs = [
                f"{r.message}: {d.get('code')} {d.get('message')}"
                for r in resp.rejected
                for d in (r.details or ({},))
            ]
            return SubmissionResult(
                success=False,
                status=stored_status(STATUS_REJECTED),
                authority_uuid=doc["header"]["uuid"],
                errors=errs,
                raw_response=resp.raw,
            )
        return SubmissionResult(
            success=True,
            status=stored_status(STATUS_SUBMITTED),
            authority_uuid=doc["header"]["uuid"],
            raw_response=resp.raw,
        )

    async def check_status(self, authority_uuid: str, device: EInvoiceDevice) -> SubmissionResult:
        # Real status arrives via the authority's callback (see ``notifications``). Asking per
        # receipt is forbidden by the authority's integration practices, so there is nothing
        # honest to return here without a submission id.
        return SubmissionResult(
            success=False,
            status=stored_status(STATUS_PENDING),
            authority_uuid=authority_uuid,
            warnings=["status is delivered by callback; query by submission id instead"],
        )

    # ------------------------------------------------------------------------------
    def _client(self, device: EInvoiceDevice, cfg: dict[str, Any]) -> EtaClient:
        profile = device_profile(device)
        creds = EtaCredentials(
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            pos_serial=device.device_serial,
            pos_os_version=cfg.get("pos_os_version", "linux"),
            pos_model_framework=cfg.get("pos_model_framework", "1"),
            preshared_key=cfg["preshared_key"],
        )
        http = self._http or httpx.AsyncClient(timeout=30.0)
        extra = {"sleep": self._sleep} if self._sleep else {}
        return EtaClient(http, EtaEndpoints.for_environment(profile.environment), creds, **extra)
