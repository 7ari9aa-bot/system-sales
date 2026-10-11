"""ClamAV clamd client — the malware scan behind the ADR-062 egress gate.

ADR-062 (as amended) makes a malware scan the gate on customer-image egress:
an attachment may reach an external vision provider ONLY at
``scan_status="scanned"``. This module is the scanner that ADR-062 was
waiting for — a minimal asyncio client for clamd's ``INSTREAM`` command, the
streaming protocol ClamAV documents for piping an in-memory object to a
running daemon over TCP (a ``clamav/clamav`` container is enough; no shared
filesystem, no subprocess, no bundled engine).

Protocol contract
-----------------
1. Connect TCP to ``host:port``.
2. Send ``zINSTREAM\\0`` (the NUL-terminated command — the portable form).
3. Stream the object as ``<4-byte big-endian length><chunk>`` frames, then a
   zero-length frame to end the stream. (Length prefixes are what the clamd
   socket protocol expects — raw bytes alone would be read as one giant
   command.)
4. Read the single reply line before the daemon closes the socket:

   * ``stream: OK`` — clean;
   * ``stream: <signature> FOUND`` — infected, and the signature name is
     kept for the quarantine log;
   * anything else (``INSTREAM size limit exceeded``, an empty reply, a
     truncated read) is a MALFORMED response, not a verdict.

Failure policy — a scanner problem is never a verdict
-----------------------------------------------------
A connection refused, a timeout, or an unparseable reply raises
:class:`MediaScannerError`. The caller (``media.py``) leaves the attachment
at ``scan_status="pending"`` — a scanner outage must look like "not yet
scanned" (retryable, egress refused), never like "scanned clean". The
infected verdict is the only answer that closes the question.

Unconfigured scanner
--------------------
``configured()`` reports whether ``MEDIA_SCANNER_HOST``/``_PORT`` are set.
An empty host is a deliberate deployment state (boot is never refused):
media ingest skips the scan, rows stay ``pending``, and the runtime gate
refuses every image — vision egress disabled, loudly logged at startup by
the settings validator.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

from app.core.config import Settings, get_settings

# Bounded like the media fetch (media.py documents why ingest must not hang
# the caller's transaction): a hung clamd is a scanner error after this long,
# which leaves the attachment pending instead of stalling message ingest.
SCAN_TIMEOUT_SECONDS = 30.0
# clamd's INSTREAM frame is a 4-byte big-endian length prefix per chunk; the
# daemon's own StreamMaxLength (commonly 25MB) rejects larger streams. Our
# media port caps objects at MAX_MEDIA_BYTES = 25MB, so chunk well under that
# and let a daemon-side limit surface as the malformed-response error path.
_CHUNK_SIZE = 64 * 1024
_READ_SIZE = 4096


class MediaScannerError(Exception):
    """The scanner could not produce a verdict (transport or reply failure).

    Deliberately NOT carrying a clean/infected verdict: callers must treat
    this as "no answer", which the egress gate reads as refused.
    """


@dataclass(frozen=True)
class ScanResult:
    """One completed scan: a verdict plus the signature when infected."""

    status: str  # "clean" | "infected"
    signature: str | None = None  # the ClamAV signature name when infected


def configured(settings: Settings | None = None) -> bool:
    """Whether a clamd endpoint is configured (empty host = scanning off)."""
    return (settings or get_settings()).media_scanner_configured


async def scan(
    data: bytes,
    *,
    host: str,
    port: int,
    timeout: float = SCAN_TIMEOUT_SECONDS,
) -> ScanResult:
    """Stream ``data`` to clamd's INSTREAM and return its verdict.

    Raises :class:`MediaScannerError` for every no-verdict outcome: connection
    failure, timeout, or a reply that is neither ``OK`` nor ``<sig> FOUND``.
    """
    try:
        async with asyncio.timeout(timeout):
            return await _scan_exchange(data, host=host, port=port)
    except MediaScannerError:
        raise
    except (TimeoutError, OSError, asyncio.IncompleteReadError) as exc:
        # Timeout, connection refused/reset, DNS failure, the socket dying
        # mid-reply — every transport failure is "no verdict", never "clean".
        raise MediaScannerError(f"clamd scan failed: {exc}") from exc


async def _scan_exchange(data: bytes, *, host: str, port: int) -> ScanResult:
    """One INSTREAM exchange on a fresh connection (session-less by design)."""
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(data), _CHUNK_SIZE):
            chunk = data[offset : offset + _CHUNK_SIZE]
            writer.write(struct.pack("!I", len(chunk)))
            writer.write(chunk)
        writer.write(struct.pack("!I", 0))  # zero-length frame: end of stream
        await writer.drain()

        reply = bytearray()
        while True:
            block = await reader.read(_READ_SIZE)
            if not block:
                break
            reply.extend(block)
            if b"\n" in reply:
                break
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):  # the daemon may already be gone
            pass

    return _parse_reply(bytes(reply))


def _parse_reply(reply: bytes) -> ScanResult:
    """Clamd's reply grammar: ``stream: OK`` or ``stream: <signature> FOUND``.

    The ``stream:`` prefix is stripped when present (older daemons and some
    proxies reply without it), whitespace is trimmed, and anything else —
    including the INSTREAM size-limit error — is malformed: no verdict.
    """
    text = reply.decode("utf-8", errors="replace").strip()
    if text.startswith("stream:"):
        text = text[len("stream:") :].strip()
    if text == "OK":
        return ScanResult(status="clean")
    if text.endswith("FOUND"):
        signature = text[: -len("FOUND")].strip()
        if signature:
            return ScanResult(status="infected", signature=signature)
    raise MediaScannerError(f"malformed clamd reply: {text[:200]!r}")


__all__ = [
    "MediaScannerError",
    "ScanResult",
    "SCAN_TIMEOUT_SECONDS",
    "configured",
    "scan",
]
