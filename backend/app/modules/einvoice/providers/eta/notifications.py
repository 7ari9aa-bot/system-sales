"""Handling the notifications the authority pushes to us (``PUT /notifications/...``).

Per the SDK (ERP - Receive Receipt / General Notifications): the authority calls an HTTPS
endpoint we expose, authenticated by a pre-shared key sent in ``Authorization: ApiKey <key>``;
the same delivery can arrive more than once, so handling must be idempotent (``deliveryId``);
we must answer 200 or it retries.

This module is pure: it parses a payload into typed events and decides what each one means.
Persisting them and the HTTP route live elsewhere, so the rules are testable without either.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ReceiptEventType(StrEnum):
    VALIDATED = "Validated"
    RECEIVED = "Received"
    CANCELLED = "Cancelled"


class DeviceEventType(StrEnum):
    CREDENTIAL_EXPIRATION = "PosCredentialExpiration"
    DEVICE_UNUSED = "PosDeviceUnused"
    ISSUE_RECEIVED = "IssueReceived"
    DEACTIVATED = "PosDeactivated"
    DATES_EXPIRATION = "PosDatesExpiration"


# What the document row's ``status`` becomes after a receipt event (see provider constants).
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_CANCELLED = "cancelled"
STATUS_RECEIVED = "received"


class NotificationError(ValueError):
    """The payload is not something the authority documents; answer 400, do not retry."""


@dataclass(frozen=True)
class ReceiptEvent:
    delivery_id: str
    type: ReceiptEventType
    uuid: str
    submission_uuid: str
    long_id: str
    internal_id: str
    authority_status: str  # "Valid" | "Invalid" | "Cancelled" (as sent)

    @property
    def new_status(self) -> str:
        if self.type is ReceiptEventType.CANCELLED:
            return STATUS_CANCELLED
        if self.type is ReceiptEventType.RECEIVED:
            return STATUS_RECEIVED
        return STATUS_VALID if self.authority_status.lower() == "valid" else STATUS_INVALID


@dataclass(frozen=True)
class DeviceEvent:
    type: DeviceEventType
    device_serial: str
    message: dict[str, Any]

    @property
    def blocks_issuing(self) -> bool:
        """A deactivated POS is refused by the authority: stop sending until it is reactivated."""
        return self.type is DeviceEventType.DEACTIVATED

    @property
    def needs_merchant_attention(self) -> bool:
        return self.type is not DeviceEventType.DEVICE_UNUSED


def api_key_matches(authorization_header: str | None, expected_key: str) -> bool:
    """Constant-time check of ``Authorization: ApiKey <key>`` (no timing side channel)."""
    if not authorization_header or not expected_key:
        return False
    scheme, _, supplied = authorization_header.partition(" ")
    if scheme.lower() != "apikey":
        return False
    return hmac.compare_digest(supplied.strip().encode(), expected_key.encode())


def key_hash(key: str) -> str:
    """The stored form of a callback key: SHA-256 hex. The plain key is never persisted."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_hash_from_header(authorization_header: str | None) -> str | None:
    """Hash of the key in ``Authorization: ApiKey <key>``, or None when the header is unusable.

    The callback arrives before any store is known, so the hash is the lookup handle; the store
    is then found with ``resolve_eta_notification_device``. A missing or malformed header yields
    None so the caller answers 401 without touching the database.
    """
    if not authorization_header:
        return None
    scheme, _, supplied = authorization_header.partition(" ")
    supplied = supplied.strip()
    if scheme.lower() != "apikey" or not supplied:
        return None
    return key_hash(supplied)


def parse_receipt_notification(body: Any) -> list[ReceiptEvent]:
    """Parse the batched receipt notification into one event per receipt."""
    if not isinstance(body, dict) or not isinstance(body.get("message"), list):
        raise NotificationError("receipt notification needs a 'message' list")
    delivery_id = str(body.get("deliveryId", "")).strip()
    if not delivery_id:
        raise NotificationError("receipt notification needs a deliveryId")
    events: list[ReceiptEvent] = []
    for item in body["message"]:
        if not isinstance(item, dict):
            raise NotificationError("each message must be an object")
        try:
            kind = ReceiptEventType(item.get("type"))
        except ValueError:
            raise NotificationError(
                f"unknown receipt notification type {item.get('type')!r}"
            ) from None
        uuid = str(item.get("uuid", "")).strip()
        if not uuid:
            raise NotificationError("receipt message without a uuid")
        events.append(
            ReceiptEvent(
                delivery_id=delivery_id,
                type=kind,
                uuid=uuid,
                submission_uuid=str(item.get("submissionUUID", "")),
                long_id=str(item.get("longId", "")),
                internal_id=str(item.get("internalId", "")),
                authority_status=str(item.get("status", "")),
            )
        )
    return events


def parse_general_notification(body: Any) -> DeviceEvent:
    """Parse a device/general notification."""
    if not isinstance(body, dict):
        raise NotificationError("general notification must be an object")
    raw_type = body.get("Type", body.get("type"))
    try:
        kind = DeviceEventType(raw_type)
    except ValueError:
        raise NotificationError(f"unknown general notification type {raw_type!r}") from None
    serial = str(body.get("Id", body.get("id", ""))).strip()
    if not serial:
        raise NotificationError("general notification needs the POS serial in 'Id'")
    message = body.get("Message", body.get("message")) or {}
    if not isinstance(message, dict):
        raise NotificationError("general notification 'Message' must be an object")
    return DeviceEvent(type=kind, device_serial=serial, message=message)


# What the authority-facing words become in ``einvoice_documents.status`` (a CHECK-constrained
# column shared with the other countries). One table, so the stored word never drifts from the
# logic that decides it.
STORED_STATUS: dict[str, str] = {
    "pending": "signed",  # built, signed/stored, not yet delivered
    "submitted": "submitted",  # the authority answered 202
    "valid": "reported",  # the authority validated it
    "invalid": "rejected",  # the authority refused it
    "rejected": "rejected",
    "failed": "failed",  # delivery trouble, safe to retry
    "cancelled": "cancelled",
    "received": "reported",  # a buyer-side event on an already valid receipt
}


def stored_status(authority_word: str) -> str:
    """The value to write to ``einvoice_documents.status``; unknown words are a bug, not a guess."""
    try:
        return STORED_STATUS[authority_word]
    except KeyError:
        raise ValueError(f"no stored status for ETA state {authority_word!r}") from None
