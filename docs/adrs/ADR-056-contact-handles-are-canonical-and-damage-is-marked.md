# ADR-056 — A contact handle is canonicalized on write, and a damaged one is marked, not rewritten

- **Status:** Accepted
- **Date:** 2026-09-24
- **Spec:** §27–29 (identity resolution + merge + Customer 360)
- **Related:** ADR-028 (entity ownership), `docs/COMPLIANCE_MATRIX.md` §27–29

Wave 4 / gaps M2 and M12. Evidence: `backend/app/core/contact_norm.py` (280 lines),
migration `d5a1c7e94b02_m12_contact_backfill.py`, `backend/tests/test_contact_backfill.py` (28),
`backend/tests/test_customer_identity_resolution.py` (25), `backend/tests/test_csv_import.py`;
operator half `backend/tests/test_contact_quarantine_surface.py` (17).
Commits: `7f93bac` (normalizer, candidates, marks) → `e9d60b7` (the CSV intake that writes through
the same rules) → `f4e4866` (the resolve surface). Closes gap M12's data half and its operator half.

## Context

Identity resolution was exact-string. One human typing `+20 100 123 4567`, `00201001234567` and
`01001234567` became three customers, each with its own orders, lifetime value and segment
membership — and `uq_customers_tenant_phone` then refused whichever write came second, for a reason
nobody could explain from the row.

The corrupted variant was worse than duplication. A deleted helper, `normalize_phone_e164`, defaulted
to **Iraq** while this system's stated market is Egypt, so Egyptian digits entered through it were
stored as `+9640…` — a fabricated country code sitting in a uniqueness key. Those rows are not
fixable by rule: `+96401001234567` is probably a mangled Egyptian number and possibly a real Iraqi
one, and the difference is a fact about a person that no longer exists in the data.

## Decisions

### 1. One stdlib-only normalizer owns the rules

`app/core/contact_norm.py` is imported from inside DB transactions, so it must never drag in a
session, SQLAlchemy or FastAPI. Its single app import is `app.core.errors`, which is itself
dependency-free — so the refusal a caller sees is the project's own `ValidationError` (HTTP 400)
rather than a library exception escaping through a route.

`DEFAULT_COUNTRY_CODE = "20"`: Egypt is the only market whose **national** formats are understood
without a country hint. International numbers must already carry `+`. E.164's 15-digit ceiling is
floored at 8 so short junk cannot enter a uniqueness field, and Egyptian national numbers are
accepted at the two lengths that exist (10 mobile, 9 landline).

### 2. A number that cannot be canonicalized is refused, not guessed

The honest limit is written where it will be read: a poisoned identity key is worse than a rejected
row. `normalize_phone` returns `None` for blank (no contact given) and raises
`ContactNormalizationError` for anything unparseable — it never returns a string that merely looks
canonical.

### 3. Matching goes through candidates, so legacy spellings still find their customer

Writes canonicalize; lookups widen. `phone_candidates` / `email_candidates` generate the forms a
stored row could legitimately be in, and `_resolve_live_by_contact`
(`customers/service.py:439-462`) matches against the set, so a customer recorded before this change
is found by a phone typed today. Matching a canonicalized value against a raw column would have
"invented" the duplicate it was meant to prevent.

Tombstoned and merged-away rows are **refused** as match targets (`:82-103`): resolving to a dead
customer writes a live order against an erased identity, which is a §53 privacy failure wearing a
usability costume.

### 4. Reading back stored values is a different question, with its own five states

`classify_stored_phone` answers "what is already in the column, and may I touch it?" — `blank`,
`canonical`, `reversible`, `corrupted`, `unparseable`. The migration and the staff report share this
vocabulary so they cannot disagree about which row is which.

`legacy_fabrication` names the corruption by its silhouette: `+964` immediately followed by `0`. That
specific shape cannot be a dialable Iraqi number — an E.164 subscriber number never carries its
country's trunk prefix — while genuine Iraqi rows (`+9647…`, `+9641…`) stay out of the queue. It
reports `legacy_raw` (a fact about the corruption) and a **suspected** recovery that is never written
over the real column. Only a person can say which number was meant.

### 5. The backfill marks what it cannot safely rewrite

Migration `d5a1c7e94b02` is data-only and conservative by three rules:

* Reversible rewrites are performed, and record their provenance under
  `extra → data_quality → m12_contact_backfill` (`phone_from` / `email_from` / `revision`) so
  `downgrade()` can restore exactly what it changes.
* A row whose fix is a guess gets a **mark** (`phone_status="needs_review"`, `legacy_raw`, optional
  `suspected_phone`) and no column change.
* A pair that would collide on `uq_customers_tenant_phone` is marked on **both** rows
  (`phone_collision = {canonical, peer_customer_ids}`). The migration refuses to pick whose orders
  survive — that is not a data-quality decision.

It leaves `updated_at`, `version` and `customer_identities.external_id` alone: a backfill that bumps
the optimistic-concurrency token invalidates every client reading the row at the moment it decides
it knows better than they do.

### 6. The queue is an operator surface, and it stops short of the merge

`GET /customers/contact-data-issues` (`customers/router.py:85`) reads the marks — from the marks, not
a live re-scan, because a row the backfill merely rewrote carries a mark with nothing to act on —
and excludes tombstones, since resolve refuses them and a queue must not promise what its own action
rejects. `POST /customers/{id}/contact-issue/resolve` (`:129-155`) clears exactly one decided mark,
under the queue's own `customers:write` gate, audited: confirm a normalization, correct a number
through the same strict normalizer every human write uses, or declare a colliding pair genuinely
distinct.

**Merging is refused here.** A merge retargets orders, conversations and ledgers and tombstones a
row; `IdentityMergeService` stays behind the human-gated `POST /customers/merge`, and asking for it
from a mark-clearer answers 400 and names where it lives. The action that clears a mark must not be
able to decide whose history survives.

## Consequences

* §146 applies to a derived column set. The queue carries `legacy_raw`, `suspected_phone` and
  `canonical_phone` in addition to `phone`, and all of them are phone numbers — `PII_FIELDS` alone
  would leave them readable. The set is flattened at the top level of the view, because
  `redact_fields` is shallow by construction.
* Passing `fields_to_redact` makes `redact_fields` redact **unconditionally**, which hid the raw
  numbers from the operators holding `pii:read` to judge them. The branch is explicit now
  (`router.py:103-119`).
* Import and intake paths (`create_from_import`, `customers/service.py:445`) go through the same
  normalizer, so a CSV cannot create the duplicate a form would have refused.

## Rejected

* **A worldwide prefix solver** — guessing a country from an bare digit string is how the `+964`
  fabrication happened. Refuse instead.
* **Rewriting collided pairs to a survivor in migration** — an identity decision dressed as a fix.
* **Storing only the canonical form and dropping the raw** — `legacy_raw` is evidence, and the
  suspected recovery must stay labelled as suspicion.
* **A re-scan instead of marks** — the mark records what the migration actually saw; a re-scan
  reports what a later version of the rule thinks.
