# ADR: customer media egress to vision providers waits for a scanner decision (D17)

Status: proposed (2026-10-11) — the enforcement half is SHIPPED, the strict
half is a product decision pending an owner ADR accept/amend.

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
