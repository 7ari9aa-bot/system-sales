"""What may leave the building as audio, and what may not.

The existing AI provider policy in this codebase treats "no policy record" as permission on some
paths. That is defensible for text where the worst case is a paragraph; it is not defensible for
audio, where a recording carries a phone number, an address and a voice that identifies a person,
and where the payload is handed to a third party that will keep it for as long as its own terms
say.

So this module inverts the default: a provider with no recorded policy cannot carry anything
above PUBLIC, and every refusal names why. The decision is a value, not a log line, so a caller
cannot proceed by ignoring a warning (invariant 12).

Data classes are deliberately few and coarse. A finer taxonomy invites a mapping table nobody
maintains; these five are enough to separate "the catalogue" from "a customer's voice".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


class DataClass(enum.StrEnum):
    """How much harm a payload could do if the provider mishandled it."""

    PUBLIC = "public"  # published catalogue, opening hours, store policies
    INTERNAL = "internal"  # aggregate shop metrics, staff names, order counts
    CONFIDENTIAL = "confidential"  # per-customer order detail, supplier prices, expenses
    PII = "pii"  # a customer's name, phone, address, or the audio that contains them
    PAYMENT = "payment"  # anything card-shaped; never sent to a speech provider at all


class EgressDecision(enum.StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class EgressVerdict:
    decision: EgressDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is EgressDecision.ALLOW


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """One provider's recorded answer to "may you carry this class of data?"."""

    provider: str
    allowed_classes: frozenset[DataClass]
    regions: frozenset[str]
    model_allowlist: frozenset[str]
    requires_dpa: bool = True
    dpa_signed: bool = False
    notes: str = ""


# The one provider the merchant assistant actually speaks through: GPT-Live behind the Vercel AI
# Gateway, reached from the EU project.
#
# What is allowed is deliberately narrow and it is a REVIEWED decision, not a default:
#   * PUBLIC — catalogue, hours, policies. Nothing to protect.
#   * INTERNAL — the shop's own aggregate metrics (net sales, order counts, low stock). The
#     merchant assistant cannot answer a single sales question without this, and these are the
#     tenant's own numbers, not a customer's record.
#   * CONFIDENTIAL / PII stay denied: per-customer order detail and any name, phone, address or
#     the audio that contains them must not reach a speech provider until a DPA is recorded here
#     (`requires_dpa` flips on with that signature) and the owner widens `allowed_classes`.
#   * PAYMENT is refused before this table is even consulted.
# A model that is not on the allowlist is refused too, so a settings change cannot quietly point
# the voice at a different vendor.
PROVIDER_POLICIES: Final[MappingProxyType[str, ProviderPolicy]] = MappingProxyType(
    {
        "gpt_live": ProviderPolicy(
            provider="gpt_live",
            allowed_classes=frozenset({DataClass.PUBLIC, DataClass.INTERNAL}),
            regions=frozenset({"eu", "us"}),
            model_allowlist=frozenset({"openai/gpt-live-1.1"}),
            requires_dpa=False,
            dpa_signed=False,
            notes=(
                "merchant assistant only; tenant-owned aggregate metrics, no customer records. "
                "Widening to confidential/pii requires a signed DPA recorded in this table."
            ),
        )
    }
)

# Classes that must never reach a speech provider regardless of any policy, because a payment
# card read aloud is a card captured in a third party's logs.
_NEVER_EGRESS: Final[frozenset[DataClass]] = frozenset({DataClass.PAYMENT})


def decide(
    *,
    provider: str,
    data_class: DataClass,
    region: str | None = None,
    model: str | None = None,
    policies: MappingProxyType[str, ProviderPolicy] | dict[str, ProviderPolicy] = PROVIDER_POLICIES,
) -> EgressVerdict:
    """May this provider carry this class of data? Deny unless the record says yes.

    Every argument that could widen the answer is checked against the record: the data class must
    be listed, the region must be one the provider is allowed to serve from, the model must be on
    the allowlist, and a required DPA must actually be signed.
    """
    if data_class in _NEVER_EGRESS:
        return EgressVerdict(
            EgressDecision.DENY,
            f"{data_class.value} data is never sent to a speech provider",
        )

    policy = policies.get(provider)
    if policy is None:
        return EgressVerdict(
            EgressDecision.DENY,
            f"no recorded policy for provider {provider!r}; nothing above public may leave",
        )

    if data_class not in policy.allowed_classes:
        return EgressVerdict(
            EgressDecision.DENY,
            f"{provider!r} is not approved for {data_class.value} data",
        )

    if region is not None and region not in policy.regions:
        return EgressVerdict(
            EgressDecision.DENY,
            f"{provider!r} may not serve region {region!r}",
        )

    if model is not None and policy.model_allowlist and model not in policy.model_allowlist:
        return EgressVerdict(
            EgressDecision.DENY,
            f"model {model!r} is not on {provider!r}'s allowlist",
        )

    if policy.requires_dpa and not policy.dpa_signed:
        return EgressVerdict(
            EgressDecision.DENY,
            f"{provider!r} requires a signed data-processing agreement first",
        )

    return EgressVerdict(
        EgressDecision.ALLOW,
        f"{provider!r} may carry {data_class.value} data",
    )


def require_egress(**kwargs: object) -> EgressVerdict:
    """``decide`` for callers that must not continue on a refusal.

    Returns the verdict when allowed so the caller can log the reason; raises ``EgressDenied``
    otherwise, which the session layer turns into a refused session rather than a silent downgrade.
    """
    verdict = decide(**kwargs)  # type: ignore[arg-type]
    if not verdict.allowed:
        raise EgressDenied(verdict.reason)
    return verdict


class EgressDenied(Exception):
    """Audio may not leave to this provider for this data class, and the reason is recorded."""
