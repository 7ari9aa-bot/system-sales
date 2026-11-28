"""The decision that says whether a workspace may use an application.

The audit's formula, in one place and in order:

    allowed = tenant operational
              AND user has workspace access
              AND workspace active
              AND application exists
              AND industry compatible
              AND subscription entitled
              AND installation active
              AND dependencies active
              AND required capabilities satisfied

Everything here is pure: it takes facts and returns a verdict with a reason. The
caller supplies the facts (today: the tests; later: a repository). Keeping the
order and the reasons in one function is what makes "why is this screen missing"
answerable instead of guessed.

Two rules that matter more than the rest:

- Unknown application denies. A typo must never read as "no restriction".
- A reason is always returned, because an operator debugging a paid product needs
  the specific gate that closed, not a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.applications.manifests import REGISTRY, get_manifest


@dataclass(frozen=True, slots=True)
class AccessFacts:
    """What the caller knows about this workspace and this user right now."""

    application_key: str
    tenant_operational: bool = True
    workspace_active: bool = True
    user_has_workspace_access: bool = True
    industry: str | None = None
    #: Applications the subscription actually entitles, installation ignored.
    entitled_applications: frozenset[str] = field(default_factory=frozenset)
    #: Applications installed in this workspace, with their installation state.
    installation_states: dict[str, str] = field(default_factory=dict)
    enabled_capabilities: frozenset[str] = field(default_factory=frozenset)


#: Installation states that mean "usable". ``setup_required`` is deliberately
#: excluded: the customer paid, but the workspace has not finished configuring it.
ACTIVE_INSTALLATION_STATES = frozenset({"active"})


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def decide_access(facts: AccessFacts) -> AccessDecision:
    """Apply every gate in order and stop at the first one that closes."""
    key = facts.application_key
    if key not in REGISTRY:
        return AccessDecision(False, f"unknown_application:{key}")
    manifest = get_manifest(key)

    if not facts.tenant_operational:
        return AccessDecision(False, "tenant_not_operational")
    if not facts.workspace_active:
        return AccessDecision(False, "workspace_inactive")
    if not facts.user_has_workspace_access:
        return AccessDecision(False, "no_workspace_access")

    if facts.industry and "*" not in manifest.supported_industries:
        if facts.industry not in manifest.supported_industries:
            return AccessDecision(False, f"industry_not_supported:{facts.industry}")

    if key not in facts.entitled_applications:
        return AccessDecision(False, "not_entitled")

    state = facts.installation_states.get(key)
    if state is None:
        return AccessDecision(False, "not_installed")
    if state not in ACTIVE_INSTALLATION_STATES:
        return AccessDecision(False, f"installation_{state}")

    for dependency in manifest.dependencies:
        if facts.installation_states.get(dependency) not in ACTIVE_INSTALLATION_STATES:
            return AccessDecision(False, f"dependency_inactive:{dependency}")
        if dependency not in facts.entitled_applications:
            return AccessDecision(False, f"dependency_not_entitled:{dependency}")

    for capability in manifest.requires_capabilities:
        if capability not in facts.enabled_capabilities:
            return AccessDecision(False, f"capability_missing:{capability}")

    return AccessDecision(True, "allowed")


def describe(facts_without_key: dict) -> tuple[dict[str, object], ...]:
    """Every application, and whether this workspace may use it, in registry order.

    A screen that lists products has to say "you did not buy this" and "you have
    not finished setting this up" differently, so each row carries the gate that
    closed rather than a bare boolean.
    """
    rows: list[dict[str, object]] = []
    for key in REGISTRY:
        manifest = get_manifest(key)
        decision = decide_access(AccessFacts(application_key=key, **facts_without_key))
        rows.append(
            {
                "key": key,
                "title_ar": manifest.title_ar,
                "title_en": manifest.title_en,
                "allowed": decision.allowed,
                "reason": decision.reason,
            }
        )
    return tuple(rows)
