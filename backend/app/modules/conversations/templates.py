"""Message template lifecycle (spec §31).

A template is a first-class, tenant-owned, channel-scoped artefact that must be
APPROVED before it can reach a customer. The send path enforces that
(ConversationService.add_message -> MessagingPolicyService); this service is the
only way a template becomes sendable.

State machine — every transition is validated, never assigned directly:

    draft ──submit──> submitted ──approve──> approved ──pause──> paused
      ^                   │                     │                  │
      │                   └──reject──> rejected │                  │
      └──────────── edit ──────────────────────┘                  │
                        resume <───────────────────────────────────┘
    (anything) ──archive──> archived   [terminal]

Why the rules are strict:
- Content may only change while the template is draft/rejected. Editing an
  APPROVED template in place would silently change what a provider already
  vetted — the customer would receive text nobody approved.
- Every submit/approve/reject writes a TemplateApproval row, so the audit trail
  survives independently of the template row's current status.
- `provider` is the channel namespace the template belongs to; the policy
  engine refuses to send a whatsapp template over messenger.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.conversations.gateway import whatsapp_templates as wa
from app.modules.conversations.models import MessageTemplate, TemplateApproval
from app.modules.conversations.policy import CHANNEL_POLICIES

# Template providers we know how to validate against.
KNOWN_PROVIDERS = frozenset(
    name for name, policy in CHANNEL_POLICIES.items() if policy.supports_templates
)

EDITABLE_STATUSES = frozenset({"draft", "rejected"})

# current status -> statuses it may move to
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "archived"}),
    "submitted": frozenset({"approved", "rejected", "archived"}),
    "approved": frozenset({"paused", "archived"}),
    "rejected": frozenset({"submitted", "archived"}),
    "paused": frozenset({"approved", "archived"}),
    "archived": frozenset(),
}

MAX_VARIABLES = 20


@dataclass(frozen=True, slots=True)
class TemplateInput:
    name: str
    body_text: str
    language: str = "ar"
    provider: str = "whatsapp"
    variables: tuple[str, ...] = ()
    # WhatsApp only. Left empty, a template is "just the body", as it always was.
    category: str | None = None
    header_text: str | None = None
    footer: str | None = None
    buttons: tuple[dict, ...] = ()
    body_examples: tuple[str, ...] = ()
    header_examples: tuple[str, ...] = ()


def _validate(data: TemplateInput) -> None:
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("template name is required")
    if len(name) > 127:
        raise ValidationError("template name is too long")
    if not (data.body_text or "").strip():
        raise ValidationError("template body is required")
    if data.provider not in KNOWN_PROVIDERS:
        raise ValidationError(f"provider must be one of: {', '.join(sorted(KNOWN_PROVIDERS))}")
    if len(data.variables) > MAX_VARIABLES:
        raise ValidationError(f"a template may declare at most {MAX_VARIABLES} variables")
    for var in data.variables:
        if not var or not var.replace("_", "").isalnum():
            raise ValidationError(f"invalid template variable name: {var!r}")
    if data.provider == "whatsapp" and data.category:
        # Fail while the owner is still editing, not after a round trip to Meta.
        wa.check_name(data.name)
        _components_for(data)


def _components_for(data: TemplateInput) -> list[dict]:
    return wa.build_components(
        body=data.body_text,
        header_text=data.header_text,
        footer=data.footer,
        buttons=list(data.buttons) or None,
        body_examples=list(data.body_examples) or None,
        header_examples=list(data.header_examples) or None,
    )


class TemplateService:
    @staticmethod
    async def list_templates(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[MessageTemplate]:
        stmt = select(MessageTemplate).where(MessageTemplate.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(MessageTemplate.status == status)
        if provider:
            stmt = stmt.where(MessageTemplate.provider == provider)
        rows = (
            (await session.execute(stmt.order_by(MessageTemplate.created_at.desc()).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> MessageTemplate:
        row = (
            await session.execute(
                select(MessageTemplate).where(
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.id == template_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("template not found")
        return row

    @staticmethod
    async def create(
        session: AsyncSession, tenant_id: uuid.UUID, data: TemplateInput
    ) -> MessageTemplate:
        """Create a DRAFT template. Nothing created here is sendable yet."""
        _validate(data)
        existing = (
            await session.execute(
                select(MessageTemplate).where(
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.name == data.name.strip(),
                    MessageTemplate.language == data.language,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("a template with this name and language already exists")
        template = MessageTemplate(
            tenant_id=tenant_id,
            name=data.name.strip(),
            language=data.language,
            body_text=data.body_text,
            variables=list(data.variables),
            provider=data.provider,
            status="draft",
            category=(data.category or "").upper() or None,
            components=(
                _components_for(data) if data.provider == "whatsapp" and data.category else []
            ),
        )
        session.add(template)
        await session.flush()
        return template

    @staticmethod
    async def update(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        data: TemplateInput,
    ) -> MessageTemplate:
        template = await TemplateService.get(session, tenant_id, template_id)
        if template.status not in EDITABLE_STATUSES:
            # An approved template was already vetted by the provider; editing
            # it in place would change what the customer receives.
            raise ConflictError(
                f"a {template.status} template cannot be edited — "
                "create a new version or archive it"
            )
        _validate(data)
        template.name = data.name.strip()
        template.body_text = data.body_text
        template.language = data.language
        template.provider = data.provider
        template.variables = list(data.variables)
        template.category = (data.category or "").upper() or None
        template.components = (
            _components_for(data) if data.provider == "whatsapp" and data.category else []
        )
        template.rejection_reason = None
        await session.flush()
        return template

    @staticmethod
    async def _transition(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        target: str,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> MessageTemplate:
        template = await TemplateService.get(session, tenant_id, template_id)
        allowed = ALLOWED_TRANSITIONS.get(template.status, frozenset())
        if target not in allowed:
            if allowed:
                hint = f" (allowed: {', '.join(sorted(allowed))})"
            else:
                hint = " - archived is terminal"
            raise ConflictError(f"cannot move a {template.status} template to {target}{hint}")
        template.status = target
        # The audit row is written for every review step, so history survives
        # later status changes.
        if target in ("submitted", "approved", "rejected"):
            session.add(
                TemplateApproval(
                    tenant_id=tenant_id,
                    template_id=template.id,
                    status=target,
                    reviewer=reviewer,
                    rejection_reason=reason,
                )
            )
        await session.flush()
        return template

    @staticmethod
    def is_meta_managed(template: MessageTemplate) -> bool:
        """A WhatsApp template with a category lives on Meta; its review is Meta's, not ours."""
        return template.provider == "whatsapp" and bool(template.category)

    @staticmethod
    async def submit(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        *,
        credentials: dict | None = None,
        _client=None,
    ) -> MessageTemplate:
        """Send the template for review.

        A Meta-managed template is created on the WhatsApp business account FIRST and only then
        marked submitted, so a refusal (bad name, taken name, Meta down) leaves it a draft the
        owner can fix, never a "submitted" row Meta has never heard of.
        """
        template = await TemplateService.get(session, tenant_id, template_id)
        if not TemplateService.is_meta_managed(template):
            return await TemplateService._transition(session, tenant_id, template_id, "submitted")
        if template.status not in ("draft", "rejected"):
            raise ConflictError(f"a {template.status} template cannot be submitted")
        if not credentials:
            raise ConflictError("WhatsApp is not connected")
        created = await wa.whatsapp_template_client.create(
            credentials,
            name=template.name,
            language=template.language,
            category=template.category or "",
            components=list(template.components or [])
            or wa.build_components(body=template.body_text),
            _client=_client,
        )
        template.provider_template_id = str(created["id"])
        template.rejection_reason = None
        # Meta can answer APPROVED at once (e.g. a re-used text); trust its word, not ours.
        reported = wa.our_status(created.get("status")) or "submitted"
        return await TemplateService.apply_provider_status(
            session, tenant_id, template.id, reported, reviewer="meta"
        )

    @staticmethod
    async def apply_provider_status(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        status: str,
        *,
        reason: str | None = None,
        reviewer: str = "meta",
    ) -> MessageTemplate:
        """Record the status the PROVIDER reported. The only way a Meta template becomes approved.

        Idempotent (Meta repeats and reorders webhooks): the same status again is a no-op, and a
        status the state machine cannot reach from here is skipped rather than forced, so a late
        "pending" never demotes a template Meta has already approved.
        """
        template = await TemplateService.get(session, tenant_id, template_id)
        if template.status == status or template.status == "archived":
            return template
        if status == "rejected":
            template.rejection_reason = (reason or "").strip()[:2000] or None
        if status not in ALLOWED_TRANSITIONS.get(template.status, frozenset()):
            # draft -> approved/rejected is not a legal hop, but it is what Meta reports for a
            # template we just created; walk through "submitted" so the audit trail is whole.
            if template.status == "draft" and status in ("approved", "rejected", "paused"):
                template.status = "submitted"
                session.add(
                    TemplateApproval(
                        tenant_id=tenant_id,
                        template_id=template.id,
                        status="submitted",
                        reviewer=reviewer,
                    )
                )
            else:
                return template
        template.status = status
        if status in ("submitted", "approved", "rejected"):
            session.add(
                TemplateApproval(
                    tenant_id=tenant_id,
                    template_id=template.id,
                    status=status,
                    reviewer=reviewer,
                    rejection_reason=template.rejection_reason if status == "rejected" else None,
                )
            )
        await session.flush()
        return template

    @staticmethod
    async def approve(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        *,
        reviewer: str | None = None,
        provider_template_id: str | None = None,
    ) -> MessageTemplate:
        """Approve a template, making it sendable outside the window.

        `provider_template_id` records the id the provider assigned when it
        vetted the content (e.g. Meta's HSM id) — required for the send path to
        reference the approved template rather than our local copy.
        """
        existing = await TemplateService.get(session, tenant_id, template_id)
        if TemplateService.is_meta_managed(existing):
            raise ConflictError(
                "a WhatsApp template is approved by Meta, not by hand; "
                "submit it and wait for Meta's review (or press sync)"
            )
        template = await TemplateService._transition(
            session, tenant_id, template_id, "approved", reviewer=reviewer
        )
        if provider_template_id:
            template.provider_template_id = provider_template_id
            await session.flush()
        return template

    @staticmethod
    async def reject(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        *,
        reason: str,
        reviewer: str | None = None,
    ) -> MessageTemplate:
        if not (reason or "").strip():
            raise ValidationError("a rejection reason is required")
        existing = await TemplateService.get(session, tenant_id, template_id)
        if TemplateService.is_meta_managed(existing):
            raise ConflictError("a WhatsApp template is reviewed by Meta, not rejected by hand")
        return await TemplateService._transition(
            session, tenant_id, template_id, "rejected", reviewer=reviewer, reason=reason
        )

    @staticmethod
    async def sync_from_meta(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        credentials: dict,
        _client=None,
    ) -> dict:
        """Pull every template's review state from Meta and apply it to ours.

        Only templates we already know are touched, matched by Meta's id (falling back to
        name + language for one created before the id was kept): this never creates a template
        the owner did not write, and an unknown status from Meta changes nothing. Meta is the
        source of truth for the review, so this is what turns "submitted" into "approved".
        """
        remote = await wa.whatsapp_template_client.list(credentials, _client=_client)
        mine = [
            t
            for t in await TemplateService.list_templates(
                session, tenant_id, provider="whatsapp", limit=500
            )
            if TemplateService.is_meta_managed(t)
        ]
        by_id = {str(r.get("id")): r for r in remote if r.get("id")}
        by_key = {(r.get("name"), r.get("language")): r for r in remote}
        changed: list[str] = []
        missing: list[str] = []
        for template in mine:
            if template.status == "archived":
                continue
            found = by_id.get(str(template.provider_template_id)) or by_key.get(
                (template.name, template.language)
            )
            if found is None:
                # Only a template we sent can be "missing"; a draft was never there to begin with.
                if template.status != "draft":
                    missing.append(template.name)
                continue
            if not template.provider_template_id and found.get("id"):
                template.provider_template_id = str(found["id"])
            status = wa.our_status(found.get("status"))
            if status is None or status == template.status:
                continue
            reason = found.get("rejected_reason")
            await TemplateService.apply_provider_status(
                session,
                tenant_id,
                template.id,
                status,
                reason=None if reason in (None, "", "NONE") else str(reason),
            )
            changed.append(template.name)
        return {"checked": len(mine), "changed": changed, "missing_on_meta": missing}

    @staticmethod
    async def remove(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        *,
        credentials: dict | None = None,
        _client=None,
    ) -> MessageTemplate:
        """Archive a template; a Meta one is deleted on Meta first so the name can be reused."""
        template = await TemplateService.get(session, tenant_id, template_id)
        if TemplateService.is_meta_managed(template) and template.status != "draft":
            if not credentials:
                raise ConflictError("WhatsApp is not connected")
            await wa.whatsapp_template_client.delete(
                credentials, name=template.name, _client=_client
            )
        return await TemplateService._transition(session, tenant_id, template_id, "archived")

    @staticmethod
    async def pause(
        session: AsyncSession, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> MessageTemplate:
        """Stop using an approved template without losing its approval."""
        return await TemplateService._transition(session, tenant_id, template_id, "paused")

    @staticmethod
    async def resume(
        session: AsyncSession, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> MessageTemplate:
        existing = await TemplateService.get(session, tenant_id, template_id)
        if TemplateService.is_meta_managed(existing):
            # Meta pauses a template whose quality dropped; only Meta lifts that (sync shows it).
            raise ConflictError(
                "a WhatsApp template paused by Meta is resumed by Meta; press sync to refresh it"
            )
        return await TemplateService._transition(session, tenant_id, template_id, "approved")

    @staticmethod
    async def archive(
        session: AsyncSession, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> MessageTemplate:
        return await TemplateService._transition(session, tenant_id, template_id, "archived")


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EDITABLE_STATUSES",
    "KNOWN_PROVIDERS",
    "TemplateInput",
    "TemplateService",
]
