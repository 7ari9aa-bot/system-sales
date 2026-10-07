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
    async def submit(
        session: AsyncSession, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> MessageTemplate:
        return await TemplateService._transition(session, tenant_id, template_id, "submitted")

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
        return await TemplateService._transition(
            session, tenant_id, template_id, "rejected", reviewer=reviewer, reason=reason
        )

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
