"""IdentityMergeService — §27-28 duplicate customer resolution."""

from __future__ import annotations

from app.modules.errors import ConflictError, NotFoundError


class IdentityMergeService:
    """Spec §27-28: resolve duplicate customers into one canonical record.

    Human-approved (AI only creates candidates). Preserves all history by
    remapping identities/conversations/orders/notes/tags/events/consents to
    the canonical customer, tombstones the loser with merged_into redirect,
    writes an IdentityMergeEvent + audit + customer.merged outbox event.
    """

    _REMAP_TABLES = [
        # (table, fk_column) — all tenant-scoped child tables of customers
        ("customer_identities", "customer_id"),
        ("addresses", "customer_id"),
        ("conversations", "customer_id"),
        ("orders", "customer_id"),
        ("notes", "customer_id"),
        ("customer_events", "customer_id"),
        ("leads", "customer_id"),
        ("consents", "customer_id"),
        ("touchpoints", "customer_id"),
        ("conversions", "customer_id"),
        ("memories", "customer_id"),
    ]

    @staticmethod
    async def _merge_open_conversations(
        session, tenant_id, canonical_customer_id, merged_away_customer_id
    ) -> None:
        """Resolve open-conversation conflicts BEFORE the generic FK remap.

        The partial unique index uq_conversations_open_tenant_customer_channel
        (tenant, customer, channel WHERE status <> 'closed') forbids two open
        conversations for one customer on one channel. A blind remap of
        conversations.customer_id violates it whenever both customers already
        talk to us on the same channel. Open conflicts are folded here: the
        merged conversation's messages move into the canonical conversation and
        the merged conversation is closed, after which the generic remap can
        re-point it safely.
        """
        from sqlalchemy import text

        merged_open = (
            (
                await session.execute(
                    text(
                        "SELECT id, channel FROM conversations "
                        "WHERE tenant_id = :t AND customer_id = :mid AND status <> 'closed' "
                        "FOR UPDATE"
                    ),
                    {"t": tenant_id, "mid": merged_away_customer_id},
                )
            )
            .mappings()
            .all()
        )

        for row in merged_open:
            canonical_open = (
                await session.execute(
                    text(
                        "SELECT id FROM conversations "
                        "WHERE tenant_id = :t AND customer_id = :canonical "
                        "AND channel = :channel AND status <> 'closed' "
                        "LIMIT 1"
                    ),
                    {
                        "t": tenant_id,
                        "canonical": canonical_customer_id,
                        "channel": row["channel"],
                    },
                )
            ).scalar_one_or_none()

            if canonical_open is None:
                # No conflict: re-point now so the conversation stays open
                # under the canonical customer.
                await session.execute(
                    text(
                        "UPDATE conversations SET customer_id = :canonical "
                        "WHERE tenant_id = :t AND id = :cid"
                    ),
                    {
                        "t": tenant_id,
                        "canonical": canonical_customer_id,
                        "cid": row["id"],
                    },
                )
                continue

            # Both customers had an open conversation on this channel: fold the
            # merged one into the canonical one, then close the merged one
            # (mirrors ConversationService.close: status + unread_count reset).
            await session.execute(
                text(
                    "UPDATE messages SET conversation_id = :canonical_conv "
                    "WHERE tenant_id = :t AND conversation_id = :merged_conv"
                ),
                {
                    "t": tenant_id,
                    "canonical_conv": canonical_open,
                    "merged_conv": row["id"],
                },
            )
            await session.execute(
                text(
                    "UPDATE conversations SET status = 'closed', unread_count = 0 "
                    "WHERE tenant_id = :t AND id = :cid"
                ),
                {"t": tenant_id, "cid": row["id"]},
            )

    @staticmethod
    async def merge(
        session,
        tenant_id,
        *,
        canonical_customer_id,
        merged_away_customer_id,
        performed_by_user_id=None,
        source: str = "human",
    ):
        from datetime import UTC, datetime

        from sqlalchemy import text

        from app.core.audit import write_audit_row
        from app.core.errors import ConflictError, NotFoundError
        from app.core.events.writer import add_outbox_event
        from app.modules.customers.models import IdentityMergeEvent

        if canonical_customer_id == merged_away_customer_id:
            raise ConflictError("cannot merge a customer into itself")

        canonical = (
            await session.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id = :t "
                    "AND id = :cid AND merged_into_customer_id IS NULL "
                    "AND deleted_at IS NULL FOR UPDATE"
                ),
                {"t": tenant_id, "cid": canonical_customer_id},
            )
        ).scalar_one_or_none()
        if canonical is None:
            raise NotFoundError("canonical customer not found")

        merged_away = (
            await session.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id = :t "
                    "AND id = :mid AND merged_into_customer_id IS NULL "
                    "AND deleted_at IS NULL FOR UPDATE"
                ),
                {"t": tenant_id, "mid": merged_away_customer_id},
            )
        ).scalar_one_or_none()
        if merged_away is None:
            raise NotFoundError("customer to merge away not found")

        # Merge open conversations FIRST: the generic remap below is a blind
        # UPDATE of conversations.customer_id, which violates the partial
        # unique index uq_conversations_open_tenant_customer_channel whenever
        # both customers already have an open conversation on the same
        # channel. Fold those conflicts here, then the remap is safe.
        await IdentityMergeService._merge_open_conversations(
            session, tenant_id, canonical_customer_id, merged_away_customer_id
        )

        # Remap every child table to the canonical customer.
        for table, fk in IdentityMergeService._REMAP_TABLES:
            await session.execute(
                text(f"UPDATE {table} SET {fk} = :canonical WHERE tenant_id = :t AND {fk} = :mid"),
                {
                    "canonical": canonical_customer_id,
                    "t": tenant_id,
                    "mid": merged_away_customer_id,
                },
            )

        # Tombstone the merged-away customer with a redirect.
        await session.execute(
            text(
                "UPDATE customers SET merged_into_customer_id = :canonical, "
                "merged_at = :now, updated_at = now() "
                "WHERE tenant_id = :t AND id = :mid"
            ),
            {
                "canonical": canonical_customer_id,
                "now": datetime.now(UTC),
                "t": tenant_id,
                "mid": merged_away_customer_id,
            },
        )

        # Consolidated lifetime value on the canonical record. Both sides are
        # DERIVED figures (the order money path rewrites them from the ledger
        # rows, §M6) and the remap above moved those rows to the canonical
        # customer, so the sum is what a restripe of that row would derive.
        await session.execute(
            text(
                "UPDATE customers c1 SET lifetime_value = c1.lifetime_value + c2.lifetime_value "
                "FROM customers c2 WHERE c1.id = :canonical AND c2.id = :mid"
            ),
            {"canonical": canonical_customer_id, "mid": merged_away_customer_id},
        )

        session.add(
            IdentityMergeEvent(
                tenant_id=tenant_id,
                canonical_customer_id=canonical_customer_id,
                merged_away_customer_id=merged_away_customer_id,
                performed_by_user_id=performed_by_user_id,
                source=source,
                details={},
            )
        )
        await write_audit_row(
            session,
            tenant_id,
            performed_by_user_id,
            action="customer.merged",
            resource_type="customer",
            resource_id=str(canonical_customer_id),
            after={"merged_away": str(merged_away_customer_id), "source": source},
        )
        # §153: the canonical row's REAL version (Customer carries
        # VersionMixin). The merge's raw SQL above does not bump it, so read
        # the post-merge value from the row instead of hardcoding a literal.
        canonical_version = (
            await session.execute(
                text("SELECT version FROM customers WHERE tenant_id = :t AND id = :cid"),
                {"t": tenant_id, "cid": canonical_customer_id},
            )
        ).scalar_one()
        await add_outbox_event(
            session,
            aggregate_type="customer",
            aggregate_id=canonical_customer_id,
            event_type="customer.merged",
            tenant_id=tenant_id,
            payload={
                "canonical_customer_id": str(canonical_customer_id),
                "merged_away_customer_id": str(merged_away_customer_id),
            },
            aggregate_version=canonical_version,
        )
        await session.flush()
        return canonical_customer_id

    @staticmethod
    async def create_merge_candidate(
        session,
        tenant_id,
        *,
        customer_a_id,
        customer_b_id,
        match_type="ai_suggested",
        confidence=0.5,
        evidence=None,
    ):

        from app.modules.customers.models import IdentityMergeCandidate

        if customer_a_id == customer_b_id:
            raise ConflictError("candidate must be two different customers")
        candidate = IdentityMergeCandidate(
            tenant_id=tenant_id,
            customer_a_id=customer_a_id,
            customer_b_id=customer_b_id,
            match_type=match_type,
            confidence=confidence,
            evidence=evidence or {},
            status="pending",
        )
        session.add(candidate)
        await session.flush()
        return candidate

    @staticmethod
    async def resolve_merge_candidate(
        session,
        tenant_id,
        *,
        candidate_id,
        decision: str,  # merged | rejected | dismissed
        decided_by_user_id=None,
    ):
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.core.errors import ValidationError
        from app.modules.customers.models import IdentityMergeCandidate

        candidate = (
            await session.execute(
                select(IdentityMergeCandidate).where(
                    IdentityMergeCandidate.tenant_id == tenant_id,
                    IdentityMergeCandidate.id == candidate_id,
                )
            )
        ).scalar_one_or_none()
        if candidate is None:
            raise NotFoundError("merge candidate not found")
        if decision not in ("merged", "rejected", "dismissed"):
            raise ValidationError(f"invalid decision: {decision}")

        if decision == "merged":
            # Deterministic side wins as canonical unless AI flagged otherwise.
            canonical, away = candidate.customer_a_id, candidate.customer_b_id
            await IdentityMergeService.merge(
                session,
                tenant_id,
                canonical_customer_id=canonical,
                merged_away_customer_id=away,
                performed_by_user_id=decided_by_user_id,
                source="candidate",
            )

        candidate.status = decision
        candidate.decided_by_user_id = decided_by_user_id
        candidate.decided_at = datetime.now(UTC)
        await session.flush()
        return candidate
