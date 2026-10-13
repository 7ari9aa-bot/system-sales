# ADR: customer media egress to vision providers waits for a scanner decision (D17)

Status: amended (2026-10-10) — the strict half recorded below as a pending
owner decision is now DECIDED and ENFORCED on the real path; see the
Amendment section at the end. The original proposed status is preserved
verbatim underneath for the record.

Status (original, 2026-10-11): proposed — the enforcement half is SHIPPED,
the strict half is a product decision pending an owner ADR accept/amend.

## Context

Plan 6.2 (external audit) demands that no customer attachment reaches an
external vision provider unless it passed a malware scan
(`attachments.scan_status = 'scanned'`) and finished media processing
(`attachments.processing_status = 'ready'`).

The system's actual vocabulary and flow:

* `scan_status`: `pending` (default) → `stored` (durably written) or
  `failed`. **There is no scanner integrated** — media.py documents the
  literal string `stored`, "never `scanned`, for a scanner that does not
  exist". `scanned` and `quarantined` are unreachable values today.
* `processing_status`: `pending` (default) → `processed` (gateway ingest) or
  `failed`. There is no `ready` value — the audit's demanded literal does not
  exist in the vocabulary either.

Enforcing the audit's literals verbatim would therefore reject EVERY
customer image: `scanned` is unreachable, and `ready` is not a value. The
vision feature (customer photo → matching catalog products) would be dead
on arrival — a feature kill, not a hardening.

What IS enforced today (runtime.py `_resolve_turn_media`), with the reasoning
documented inline: the gate admits `scan_status ∈ {stored, scanned}` (a
failed scan leaves the row refused — MediaService refuses such rows itself)
and `processing_status != 'failed'`. Rows that were never durably stored are
excluded; a scan failure excludes the row; unknown/unscanned-pending values
are excluded.

## Risk being accepted (interim, pending the scanner)

* Unscanned customer-uploaded images are sent to the external vision
  provider. Bounded by: images only (mime `image/%`), one newest inbound
  message per turn, tenant-scoped rows, objects that ARE durably stored, and
  the provider sees the image the customer themselves uploaded — no other
  tenant's or customer's data is reachable through this path.
* No malware amplification surface beyond what the messaging channel already
  delivered to the merchant's own inbox.

## Decision

1. **Now (shipped):** the gate stays as documented above — it refuses failed
   scans and never signs a URL for an object that is not durably stored. The
   strict literals the audit demanded are recorded here as unreachable
   rather than silently reimplemented as no-ops.
2. **Required follow-up (owner decision):** integrate a scanner (ClamAV
   worker, or a managed scanning service) that advances
   `scan_status: pending → scanned | quarantined` on ingest; THEN tighten
   the runtime gate to `scan_status == 'scanned' AND
   processing_status = 'processed'` with the quarantine path refusing egress
   and requesting a re-upload. Tests for the strict gate land with the
   scanner (the four cases: scanned-ok, pending-refused, quarantined-refused,
   failed-refused).
3. **Reconciliation note:** the plan's `processing_status = 'ready'` literal
   must map to the real vocabulary value `processed` when the gate is
   tightened.

## Consequences

* Vision works today with the documented interim risk, instead of being
  disabled by an unreachable literal.
* The strict gate has a written path: scanner → vocabulary values exist →
  tighten gate + tests. Nothing needs to be rewritten.
* The audit finding stays open until the scanner ships; it is NOT closed by
  this ADR.

## Amendment (2026-10-10): the strict gate is now ENFORCED on the real path

The owner directed the fail-closed half of this decision. A real scanner is
integrated and the vision gate admits ONLY scanned images. What shipped:

* **Scanner** — `app/core/media_scanner.py` is a minimal asyncio client for
  clamd's `INSTREAM` protocol (ClamAV over TCP; no shared filesystem, no
  subprocess). It parses the documented reply grammar — `stream: OK`
  (clean), `stream: <signature> FOUND` (infected, signature kept for the
  quarantine log) — and maps EVERY transport or malformed-reply failure to
  "no verdict", never to clean.
* **Pipeline wiring** — `conversations/media.py` scans every durably stored
  IMAGE at ingest, on the in-memory bytes, and advances `scan_status`:
  `pending → scanned` (clean), `pending → quarantined` (infected), and
  stays `pending` on a scanner outage (retryable) — never `scanned` without
  a verdict. Non-image media keeps the durable `stored` mark: no egress
  gate exists for audio/video/documents on this path, so scanning them is
  out of this wave's scope.
* **Gate enforcement** — the runtime's media selection (`runtime.py`
  `_conversation_context`, the region the plan called `_resolve_turn_media`)
  now demands `scan_status == 'scanned'`; `pending`, `quarantined` and
  `failed` are ALL refused and the turn proceeds without vision. The auto-
  reply hook (`hooks.py`) applies the same predicate before minting the
  provider URL for the coordinator's vision pass, so both egress doors
  share one rule.
* **Fail-closed default** — with no scanner configured
  (`MEDIA_SCANNER_HOST`/`MEDIA_SCANNER_PORT` empty) boot is NOT refused:
  every durable image stays `pending`, the gate refuses all of them, and
  customer-image vision egress is therefore DISABLED until the owner
  configures ClamAV. The settings validator logs this state loudly at
  startup; ingest logs each skipped scan.
* **Tests** — the four strict-gate cases of Decision 2 plus the
  unconfigured and scanner-error cases, against a fake clamd TCP server:
  `tests/test_vision_egress_gate.py`, `tests/test_media_pipeline.py`,
  `tests/test_ai_hooks_media.py`.

### Decision 2's `processing_status` half — recorded as a gap, NOT faked

Decision 2 (and the audit's `processing_status = 'ready'`) demanded the
processing half of the gate as well, with `ready` mapping to the real value
`processed` (Decision 3). Verified against the code: NOTHING advances an
inbound Attachment's `processing_status` past `pending` — media.py sets
`pending` on a durable store and `failed` on a non-durable one, and the
gateway ingest's `processed` write belongs to `webhook_events`, not to
`attachments`. No transcoder exists. Enforcing
`processing_status = 'processed'` would therefore reject EVERY customer
image — the feature kill this ADR was written to avoid. The gate is
consequently **scan-only** (`scan_status == 'scanned'`), and the gap is
recorded here explicitly: when the §33-34 transcoder lands and actually
advances inbound images to `processed` BEFORE their turn runs, the gate
must be re-tightened to demand both halves.

### Consequences of the amendment

* Customer-image vision egress is secure by default: unscanned and infected
  bytes can never reach the external vision provider, on either egress door.
* Vision is dead until an operator configures a clamd endpoint. That is the
  owner's explicit direction — availability is bought with a scanner, not
  with risk.
* Legacy rows at `scan_status="stored"` (ingested before the scanner) no
  longer egress; they are not retroactively scanned.
* The audit finding's strict half is closed on the egress path; the
  processing half stays open with the transcoder.
