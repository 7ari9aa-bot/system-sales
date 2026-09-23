"""M12, data half — canonicalize stored contacts, quarantine the unrecoverable.

``app/core/contact_norm`` (revision chain up to here) fixed every WRITE. The
rows the old code produced are still wrong, and no lookup rule can fix them
silently. Two cases, deliberately treated differently:

* REVERSIBLE — the column holds a legal-but-local spelling of a number whose
  digits are all still there (``01001234567``, ``+20 100 123 4567``,
  ``00201001234567``), or an email with stray case/padding. Rewritten in place
  through the same functions the application uses, so migration and runtime can
  never drift. The previous value is kept in
  ``customers.extra -> 'data_quality' -> 'm12_contact_backfill'`` so
  ``downgrade()`` can put it back.
* IRREVERSIBLE — the deleted ``normalize_phone_e164`` defaulted to Iraq, so
  ``00201001234567`` became ``+9640201001234567``. That string is a *legal*
  E.164 shape and may also be a genuine Iraqi number, so it is NOT rewritten.
  It is marked ``phone_status = 'needs_review'`` next to the digit string the
  old code wrapped — a fact about the corruption, not a guess about the person.

Collisions are neither rewritten nor merged. ``uq_customers_tenant_phone`` means
the second of two rows landing on one canonical value would abort the upgrade,
and the safe alternative — ``IdentityMergeService.merge`` — decides whose orders,
conversations and lifetime value get tombstoned. That is a business decision, so
both rows keep their value and carry ``phone_collision`` for a human, readable
through ``GET /customers/contact-data-issues``.

Notes on what this migration does NOT do:

* ``updated_at`` / ``version`` are untouched. Bumping ``version`` would 412 every
  drawer a staff member had open, against a change their next write re-applies
  anyway (the runtime layer canonicalizes too).
* ``customer_identities.external_id`` is untouched: that is a provider handle
  echoed back by WhatsApp/Telegram, which still speaks the raw spelling, and the
  service matches it exactly. It is not a contact key.
* Re-running is a no-op: a row whose mark already says everything this run
  observed is not written again. When a later run learns something NEW — a human
  resolved a clash, so the surviving row can finally move — the mark is merged
  additively and keeps its original ``revision``, which leaves a stale
  ``phone_collision`` note until ``downgrade()``. ``contact_data_quality_report``
  returns the live ``phone_state`` alongside it, so a resolved row reads as
  resolved.
* ``downgrade()`` restores the previous spellings. If something has since taken
  a freed slot, the unique constraint aborts the downgrade loudly — which is the
  correct answer, not a silent overwrite.

Revision ID: d5a1c7e94b02
Revises: c4f7a9b1d3e5
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.contact_norm import (
    STATE_CANONICAL,
    STATE_CORRUPTED,
    STATE_REVERSIBLE,
    classify_stored_email,
    classify_stored_phone,
    find_canonical_collisions,
    legacy_fabrication,
    normalize_email,
    normalize_phone,
)

revision: str = "d5a1c7e94b02"
down_revision: str | None = "c4f7a9b1d3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FLAG_KEY = "m12_contact_backfill"
_FLAG_PATH = "'{data_quality,m12_contact_backfill}'"

# Typed as the model types them, so the JSONB/UUID bind processors that every
# production write of customers.extra already goes through are the same ones
# used here — a raw jsonb parameter would instead depend on how the driver
# happens to choose to encode a string.
_CUSTOMERS = sa.table(
    "customers",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("phone", sa.String(31)),
    sa.column("email", sa.String(320)),
    sa.column("extra", postgresql.JSONB(astext_type=sa.Text())),
)

_SELECT_ROWS = sa.text(
    "SELECT id, tenant_id, phone, email, extra FROM customers ORDER BY tenant_id, id"
)
_SELECT_FLAGGED = sa.text(
    f"SELECT id, extra #> {_FLAG_PATH} AS flag FROM customers "
    f"WHERE extra #> {_FLAG_PATH} IS NOT NULL ORDER BY tenant_id, id"
)
# Emptying `data_quality` removes that key too, so downgrade leaves no residue.
_RESTORE = sa.text(
    "UPDATE customers SET "
    "  phone = coalesce(CAST(:phone_from AS varchar), phone), "
    "  email = coalesce(CAST(:email_from AS varchar), email), "
    "  extra = CASE "
    f"    WHEN (extra #- {_FLAG_PATH}) -> 'data_quality' = CAST('{{}}' AS jsonb) "
    f"    THEN (extra #- {_FLAG_PATH}) - 'data_quality' "
    f"    ELSE extra #- {_FLAG_PATH} END "
    "WHERE id = :id"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        # tests/test_migrations.py swaps `op` for a recording stub that has no
        # bind; there is nothing to rewrite while it is parsing SQL statically.
        return

    rows = list(bind.execute(_SELECT_ROWS).mappings().all())
    # Computed from the pre-write snapshot: a clash has to be seen before the
    # first of the pair moves, or the second one hits the unique constraint.
    clashes: dict[tuple[str, str], list[Any]] = {
        (str(g["tenant_id"]), g["canonical"]): g["row_ids"]
        for g in find_canonical_collisions((r["tenant_id"], r["id"], r["phone"]) for r in rows)
    }

    for row in rows:
        flag: dict[str, Any] = {}
        phone = row["phone"]
        new_phone = phone
        phone_state = classify_stored_phone(phone)
        if phone_state in (STATE_REVERSIBLE, STATE_CANONICAL):
            canonical = (
                normalize_phone(phone) if phone_state == STATE_REVERSIBLE else str(phone)
            )
            peers = clashes.get((str(row["tenant_id"]), canonical))
            if peers is not None:
                # Both sides marked, neither moved: which customer's orders and
                # conversations survive is a human decision, not a migration's.
                flag["phone_collision"] = {
                    "canonical": canonical,
                    "peer_customer_ids": [str(p) for p in peers if p != row["id"]],
                }
            elif phone_state == STATE_REVERSIBLE:
                new_phone = canonical
                flag["phone_from"] = phone
        elif phone_state == STATE_CORRUPTED:
            detail = legacy_fabrication(phone)
            flag["phone_status"] = "needs_review"
            flag["legacy_raw"] = detail.legacy_raw if detail else phone
            if detail and detail.suspected_phone:
                flag["suspected_phone"] = detail.suspected_phone

        email = row["email"]
        new_email = email
        if classify_stored_email(email) == STATE_REVERSIBLE:
            new_email = normalize_email(email)
            flag["email_from"] = email

        values: dict[str, Any] = {}
        if new_phone != phone:
            values["phone"] = new_phone
        if new_email != email:
            values["email"] = new_email

        extra = row["extra"] or {}
        quality = dict(extra.get("data_quality") or {})
        existing = quality.get(_FLAG_KEY)
        existing = existing if isinstance(existing, dict) else None
        if flag:
            # Additive, and `revision` only on the first pass. A row marked by an
            # earlier run can gain a NEW fact later — its clash partner was
            # resolved, so this run moves it and must record `phone_from`, or
            # downgrade() would have nothing to restore.
            if existing is None:
                flag["revision"] = revision
            merged = {**flag, **(existing or {})}
            # Equal means this run observed exactly what it already recorded:
            # re-writing would churn a row and restamp nothing.
            if merged != (existing or {}):
                quality[_FLAG_KEY] = merged
                values["extra"] = {**extra, "data_quality": quality}
        if values:
            bind.execute(
                sa.update(_CUSTOMERS).values(**values).where(_CUSTOMERS.c.id == row["id"])
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return

    for row in bind.execute(_SELECT_FLAGGED).mappings().all():
        flag = row["flag"] or {}
        bind.execute(
            _RESTORE,
            {
                "id": row["id"],
                "phone_from": flag.get("phone_from"),
                "email_from": flag.get("email_from"),
            },
        )
