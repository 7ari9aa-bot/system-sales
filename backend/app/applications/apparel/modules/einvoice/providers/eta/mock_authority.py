"""An in-process stand-in for the ETA eReceipt service, for tests and offline development.

It speaks the *documented* wire behaviour: ``/connect/token`` (header + body validation, JWT-ish
token, ``expires_in``), ``/api/v1/receiptsubmissions`` (202 + accepted/rejected, 422 duplicate
within 10 minutes, 429, 503) and the submission details endpoint, and it checks the rules the
authority publishes for the receipt itself (hash chain, UUID shape, totals, mandatory fields).

What it cannot do, and must not be mistaken for:
* It checks the receipt UUID against the CONTENT, with the authority's own rule (verified with
  its published ``ETA.Ereceipt.UUID`` library, see ``uuid_.py``). Pass ``uuid_fn=None`` to
  check only the shape, or your own function to override.
* It does not know which activity/item codes a given taxpayer is entitled to.
* It proves our client and builder agree with the documentation, not with the live service.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from app.applications.apparel.modules.einvoice.providers.eta.validator import check_document_consistency

_DUP_WINDOW_SECONDS = 600


def _authority_uuid(doc: dict[str, Any]) -> str:
    """The authority's UUID of ``doc``. ``doc`` must hold its numbers as ``Decimal`` (as sent)."""
    from app.applications.apparel.modules.einvoice.providers.eta.uuid_ import compute_receipt_uuid

    return compute_receipt_uuid(doc)


def _hex64(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


@dataclass
class MockAuthority:
    """Mutable fake service. ``handler`` plugs into ``httpx.MockTransport``."""

    client_id: str = "mock-client"
    client_secret: str = "mock-secret"
    pos_serial: str = "POS-MOCK-1"
    preshared_key: str = "mock-psk"
    rin: str = "674859545"
    token_ttl: int = 3600
    uuid_fn: Callable[[dict[str, Any]], str] | None = _authority_uuid
    now: float = 0.0  # injectable clock for the duplicate window
    # Failure injection: popped front-to-back, one per submission call.
    fail_next: list[int] = field(default_factory=list)
    retry_after: int = 2

    # observable state
    token_requests: int = 0
    submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_uuid_by_pos: dict[str, str] = field(default_factory=dict)
    rejected_uuids: set[str] = field(default_factory=set)
    valid_uuids: set[str] = field(default_factory=set)
    # a rejected receipt's uuid -> the chain position its correction took over
    amended_from: dict[str, str] = field(default_factory=dict)
    _seen_payloads: dict[str, float] = field(default_factory=dict)
    _issued_tokens: set[str] = field(default_factory=set)
    _seq: int = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    # ---------------------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/connect/token":
            return self._token(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self._issued_tokens:
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/api/v1/receiptsubmissions" and request.method == "POST":
            return self._submit(request)
        if path.startswith("/api/v1/receiptsubmissions/") and path.endswith("/details"):
            sid = path.split("/")[4]
            sub = self.submissions.get(sid)
            if sub is None:
                return httpx.Response(404, json={"error": "NotFound"})
            return httpx.Response(200, json=sub)
        return httpx.Response(404, json={"error": "NotFound"})

    def _token(self, request: httpx.Request) -> httpx.Response:
        self.token_requests += 1
        h = request.headers
        form = dict(p.split("=", 1) for p in request.content.decode().split("&") if "=" in p)
        if form.get("grant_type") != "client_credentials":
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        if form.get("client_id") != self.client_id:
            return httpx.Response(400, json={"error": "unauthorized_client"})
        if form.get("client_secret") != self.client_secret:
            return httpx.Response(400, json={"error": "invalid_clientsecret"})
        if h.get("posserial") != self.pos_serial:
            return httpx.Response(400, json={"error": "invalid_posserial"})
        if h.get("presharedkey") != self.preshared_key:
            return httpx.Response(400, json={"error": "invalid_presharedkey"})
        token = hashlib.sha256(f"{self.token_requests}".encode()).hexdigest()
        self._issued_tokens.add(token)
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": self.token_ttl,
                "scope": "InvoicingAPI",
            },
        )

    def _submit(self, request: httpx.Request) -> httpx.Response:
        if self.fail_next:
            code = self.fail_next.pop(0)
            headers = {"Retry-After": str(self.retry_after)} if code in (429, 422) else {}
            body = {"error": "DuplicateSubmission"} if code == 422 else {"error": "Too many"}
            return httpx.Response(code, json=body, headers=headers)

        raw = request.content
        digest = hashlib.sha256(raw).hexdigest()
        seen = self._seen_payloads.get(digest)
        if seen is not None and self.now - seen < _DUP_WINDOW_SECONDS:
            return httpx.Response(
                422,
                json={"error": "DuplicateSubmission", "code": "DuplicateSubmission"},
                headers={"Retry-After": str(self.retry_after)},
            )
        self._seen_payloads[digest] = self.now

        try:
            body = json.loads(raw)
            receipts = body["receipts"]
            assert isinstance(receipts, list) and receipts
        except (ValueError, KeyError, AssertionError):
            return httpx.Response(400, json={"code": "BadStructure", "error": "BadStructure"})

        # The UUID is a hash of the text as written ("1.50000", not 1.5), so check it on a second
        # parse that keeps every number exactly as it was sent.
        exact = json.loads(raw, parse_float=Decimal, parse_int=Decimal)["receipts"]
        accepted, rejected = [], []
        chain_tip = dict(self.last_uuid_by_pos)
        for doc, exact_doc in zip(receipts, exact, strict=True):
            errors = self._validate(doc, chain_tip, exact_doc)
            uuid = doc.get("header", {}).get("uuid", "")
            number = doc.get("header", {}).get("receiptNumber", "")
            if errors:
                self.rejected_uuids.add(uuid)
                rejected.append(
                    {
                        "receiptNumber": number,
                        "uuid": uuid,
                        "error": {
                            "message": "Validation Error",
                            "target": uuid,
                            "details": errors,
                        },
                    }
                )
            else:
                self.valid_uuids.add(uuid)
                old_ref = doc["header"].get("referenceOldUUID", "")
                if old_ref:
                    # the correction takes the place of the rejected receipt in the chain
                    self.amended_from[uuid] = old_ref
                chain_tip[doc["seller"]["deviceSerialNumber"]] = old_ref or uuid
                self._seq += 1
                accepted.append(
                    {"uuid": uuid, "longId": f"LONG{self._seq:08d}", "receiptNumber": number}
                )
        # The chain only advances for the receipts that were accepted.
        self.last_uuid_by_pos = chain_tip

        sid = f"SUB{self._seq + len(rejected):022d}"
        self.submissions[sid] = {
            "submissionUuid": sid,
            "receiptsCount": len(receipts),
            "invalidReceiptCount": len(rejected),
            "status": "In Progress",
            "accepted": accepted,
            "rejected": rejected,
        }
        return httpx.Response(
            202,
            json={
                "submissionUUID": sid,
                "acceptedDocuments": accepted,
                "rejectedDocuments": rejected,
            },
        )

    # ---------------------------------------------------------------------------------
    def _validate(
        self, doc: dict[str, Any], chain_tip: dict[str, str], exact: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        errs: list[dict[str, str]] = []

        def err(code: str, path: str, msg: str) -> None:
            errs.append({"code": code, "message": msg, "target": path, "propertyPath": path})

        h = doc.get("header", {})
        seller = doc.get("seller", {})
        if seller.get("rin") != self.rin:
            err("CF301", "seller.rin", "issuer is not the authenticated taxpayer")
        pos = seller.get("deviceSerialNumber", "")
        if pos != self.pos_serial:
            err("CF302", "seller.deviceSerialNumber", "POS is not the authenticated device")
        if not _hex64(h.get("uuid")):
            err("CF310", "header.uuid", "uuid must be a 64-char SHA256 hex string")
        elif self.uuid_fn is not None:
            blank = json.loads(json.dumps(exact if exact is not None else doc, default=str))
            blank["header"]["uuid"] = ""
            if self.uuid_fn(blank) != h["uuid"]:
                err("CF311", "header.uuid", "uuid is not a valid hash of the receipt content")
        prev = h.get("previousUUID", "")
        old_ref = h.get("referenceOldUUID", "")
        tip = chain_tip.get(pos, "")
        # Authority rule (Receipt Issuance FAQ): a correction keeps the rejected receipt's
        # previousUUID and sets referenceOldUUID to it; the receipt after it keeps pointing at
        # the ORIGINAL rejected uuid, so a chain position may be "held" by a rejected uuid.
        # NOTE: this encodes the FAQ's single worked example (R3 points at the original R2, not
        # at R2*). The text states no general rule, so treat it as example-derived behaviour and
        # confirm against PreProd before relying on it.
        position_ok = prev == tip
        if old_ref:
            if old_ref in self.valid_uuids:
                err(
                    "CF322", "header.referenceOldUUID", "references a receipt that is already valid"
                )
            elif old_ref not in self.rejected_uuids:
                err("CF323", "header.referenceOldUUID", "references no previously invalid receipt")
        elif tip == "" and prev != "":
            err(
                "CF320",
                "header.previousUUID",
                "first receipt of a POS must have empty previousUUID",
            )
        elif not position_ok:
            err("CF321", "header.previousUUID", "previousUUID does not match the last receipt")
        rtype = doc.get("documentType", {}).get("receiptType")
        if rtype == "RR" and not _hex64(h.get("referenceUUID")):
            err("CF330", "header.referenceUUID", "a return receipt must reference a sale")
        if rtype == "SR" and h.get("referenceUUID"):
            err("CF331", "header.referenceUUID", "a sale receipt cannot carry referenceUUID")
        if rtype == "RWR":
            # Official page "Return Receipt Without Reference v1.2": the reason (I or B) and the
            # sale's own date are mandatory; the reference is optional but, when sent, is a
            # 64-character id (so an empty one is a defect, not "no reference").
            if h.get("documentUseReason") not in ("I", "B"):
                err("CF332", "header.documentUseReason", "must be I or B")
            if not h.get("salesIssuedDateTime"):
                err("CF333", "header.salesIssuedDateTime", "the sale's issue time is required")
            if "referenceUUID" in h and not _hex64(h.get("referenceUUID")):
                err("CF334", "header.referenceUUID", "when present it must be a 64-character id")
        elif "documentUseReason" in h or "salesIssuedDateTime" in h:
            err("CF335", "header.documentUseReason", "only a return without reference carries it")
        if not doc.get("paymentMethod"):
            err("CF340", "paymentMethod", "paymentMethod is required")
        if not h.get("currency"):
            err("CF341", "header.currency", "currency is required")
        for i in check_document_consistency(doc):
            err("CF350", i.path, i.message)
        # numbers must be real JSON numbers, never strings
        for key in ("totalAmount", "netAmount", "totalSales"):
            if not isinstance(doc.get(key), (int, float, Decimal)):
                err("CF351", key, f"{key} must be a number")
        return errs
