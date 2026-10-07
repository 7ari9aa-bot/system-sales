"""Outbound messaging policy (spec §30-31).

The CHANNEL decides what we are allowed to send, not the composer:

    Outbound message -> Channel Policy -> Conversation Window -> Allowed?
      |-- free-form  -> send
      `-- template required -> approved-template flow

WhatsApp, Messenger and Instagram only permit a free-form reply inside a
24-hour customer-service window that opens on the customer's LAST inbound
message. Outside it, only a pre-approved template may be sent. Telegram,
webchat and email carry no such rule.

This lives in the domain layer on purpose: the SAME decision must govern the
human composer, the AI auto-reply, automation, journeys and campaigns. A check
in the composer protects only one of those five producers — which is exactly
how the two of them drift apart in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.errors import DomainError


class OutboundBlockedError(DomainError):
    """An outbound message was refused by channel policy.

    409 (a state conflict, not a validation error): the request is well-formed,
    the conversation is simply outside the window the provider allows.
    """

    code = "outbound_blocked"
    http_status = 409
    default_message = "Outbound message blocked by channel policy"
    # Waiting does not help unless the customer writes back, so the caller must
    # change approach (send a template) rather than retry blindly.
    retryable = False


@dataclass(frozen=True, slots=True)
class ChannelMessagingPolicy:
    channel: str
    # None => the channel has no customer-service window (free-form always OK).
    window_hours: int | None
    supports_templates: bool
    # The MessageTemplate.provider a template must belong to for this channel.
    template_provider: str | None


# The single source of truth for provider rules. A per-channel conditional
# anywhere else in the codebase is how these rules silently drift apart.
CHANNEL_POLICIES: dict[str, ChannelMessagingPolicy] = {
    "whatsapp": ChannelMessagingPolicy("whatsapp", 24, True, "whatsapp"),
    "messenger": ChannelMessagingPolicy("messenger", 24, True, "messenger"),
    "instagram": ChannelMessagingPolicy("instagram", 24, True, "instagram"),
    "telegram": ChannelMessagingPolicy("telegram", None, False, None),
    "webchat": ChannelMessagingPolicy("webchat", None, False, None),
    "email": ChannelMessagingPolicy("email", None, False, None),
}

# Unknown channels are treated as unregulated rather than blocked: refusing to
# send on a channel we have not modelled would be a silent outage, and the
# provider still enforces its own rule.
_UNKNOWN_POLICY = ChannelMessagingPolicy("unknown", None, False, None)


def policy_for(channel: str | None) -> ChannelMessagingPolicy:
    return CHANNEL_POLICIES.get((channel or "").lower(), _UNKNOWN_POLICY)


@dataclass(frozen=True, slots=True)
class OutboundDecision:
    """The verdict, plus everything the caller needs to explain it."""

    allowed: bool
    reason: str
    requires_template: bool
    window_expires_at: datetime | None
    template_name: str | None = None

    @property
    def window_open(self) -> bool:
        return not self.requires_template


class MessagingPolicyService:
    """Evaluates §30 and answers one question: may we send this, and how?"""

    @staticmethod
    def evaluate(
        conversation,
        *,
        template_name: str | None = None,
        template_approved: bool = False,
        template_provider: str | None = None,
        now: datetime | None = None,
    ) -> OutboundDecision:
        policy = policy_for(getattr(conversation, "channel", None))
        now = now or datetime.now(UTC)

        if policy.window_hours is None:
            return OutboundDecision(
                allowed=True,
                reason="channel has no customer-service window",
                requires_template=False,
                window_expires_at=None,
            )

        anchor = getattr(conversation, "last_customer_message_at", None)
        expires = anchor + timedelta(hours=policy.window_hours) if anchor is not None else None
        if expires is not None and now < expires:
            return OutboundDecision(
                allowed=True,
                reason=f"inside the {policy.window_hours}h customer-service window",
                requires_template=False,
                window_expires_at=expires,
            )

        # Outside the window — or the customer has never written, which is the
        # same situation: only an approved template may reach them.
        if not policy.supports_templates:
            return OutboundDecision(
                allowed=False,
                reason=(
                    "outside the customer-service window and this channel has no template flow"
                ),
                requires_template=True,
                window_expires_at=expires,
            )
        if not template_name:
            return OutboundDecision(
                allowed=False,
                reason=(
                    f"outside the {policy.window_hours}h window: an approved template is required"
                ),
                requires_template=True,
                window_expires_at=expires,
            )
        if not template_approved:
            return OutboundDecision(
                allowed=False,
                reason=f"template {template_name!r} is not approved for sending",
                requires_template=True,
                window_expires_at=expires,
                template_name=template_name,
            )
        if template_provider and template_provider != policy.template_provider:
            return OutboundDecision(
                allowed=False,
                reason=(
                    f"template {template_name!r} belongs to provider "
                    f"{template_provider!r}, not {policy.template_provider!r}"
                ),
                requires_template=True,
                window_expires_at=expires,
                template_name=template_name,
            )
        return OutboundDecision(
            allowed=True,
            reason="approved template, outside the window",
            requires_template=True,
            window_expires_at=expires,
            template_name=template_name,
        )

    @staticmethod
    async def evaluate_for_conversation(
        session,
        tenant_id,
        conversation,
        *,
        template_name: str | None = None,
        language: str = "ar",
        now: datetime | None = None,
    ) -> OutboundDecision:
        """Load the referenced template (if any) and evaluate against it.

        A template that does not exist is NOT "not approved" — it is reported
        as such by evaluate() because `template_approved` stays False, which is
        the safe default for a name the tenant never registered.
        """
        if not template_name:
            return MessagingPolicyService.evaluate(conversation, now=now)

        from sqlalchemy import select

        from app.modules.conversations.models import MessageTemplate

        template = (
            await session.execute(
                select(MessageTemplate).where(
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.name == template_name,
                    MessageTemplate.language == language,
                )
            )
        ).scalar_one_or_none()

        return MessagingPolicyService.evaluate(
            conversation,
            template_name=template_name,
            template_approved=bool(template and template.status == "approved"),
            template_provider=template.provider if template else None,
            now=now,
        )


__all__ = [
    "CHANNEL_POLICIES",
    "ChannelMessagingPolicy",
    "MessagingPolicyService",
    "OutboundBlockedError",
    "OutboundDecision",
    "policy_for",
]
