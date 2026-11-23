"""WhatsApp features Meta gates: what FIHRIST can ask for, and what Meta alone decides.

Four things a WhatsApp channel screen tends to show as buttons, and that a store can rarely just
turn on:

* **Coexistence** — running the WhatsApp Business app on a number AND the Cloud API on the same
  number. Meta decides per number whether that is allowed, and the signup flow finishes with the
  ``FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`` step. Refusing that step, or treating it as an error,
  is a bug: it is the customer choosing coexistence, not a failed connection.
* **Calls** — the Calling API. Region-gated, and the number must have calling enabled.
* **Groups** — Meta's Groups API. Eligibility-gated per business account.
* **Marketing Messages** — paid, opt-in, and only for businesses Meta has approved.

None of these is a programming error when Meta says no, and none of them may be a dead button
either. Each is declared here with the state it is in, the evidence for that state, and what the
owner would have to do. A screen reads this instead of guessing.
"""

from __future__ import annotations

from typing import Any

# The state words are the vocabulary capability_states defines. They are repeated as literals here
# rather than imported, because capability_states reads this registry while it is being defined:
# importing back would be circular, and a shared vocabulary of nine strings is not worth one.
ACCOUNT_INELIGIBLE = "account_ineligible"
AVAILABLE = "available"
NEEDS_APP_REVIEW = "needs_app_review"
NOT_IMPLEMENTED = "not_implemented"
REGION_RESTRICTED = "region_restricted"

#: One entry per gated WhatsApp feature. `state` is what a screen shows when nothing has been
#: measured yet; `eligibility` says who decides, and `evidence` is why this entry exists at all.
ROADMAP: dict[str, dict[str, Any]] = {
    "coexistence": {
        "title": "تشغيل تطبيق واتساب بزنس مع Cloud API على نفس الرقم",
        "state": ACCOUNT_INELIGIBLE,
        "eligibility": "Meta decides per number; the signup finishes with "
        "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        "evidence": "Meta, 'WhatsApp Business app coexistence' — available per number, not per app",
        "action": "أكمل التسجيل واختار التطبيق؛ لو ميتا رفضت الرقم، سببها هو اللي هيظهر",
        "built": True,
    },
    "calls": {
        "title": "مكالمات واتساب",
        "state": REGION_RESTRICTED,
        "eligibility": "the number must have calling enabled, and the country must be supported",
        "evidence": "Meta, 'Calling API' — region and number gated",
        "action": "فعّل المكالمات من إعدادات الرقم في مدير أعمال ميتا",
        "built": False,
    },
    "groups": {
        "title": "جروبات واتساب",
        "state": ACCOUNT_INELIGIBLE,
        "eligibility": "the business account must be approved for the Groups API",
        "evidence": "Meta, 'Groups API' — eligibility per business account",
        "action": "اطلب الأهلية من ميتا؛ مفيش إعداد في فِهرست يفتحها",
        "built": False,
    },
    "marketing_messages": {
        "title": "رسائل تسويقية مدفوعة",
        "state": NEEDS_APP_REVIEW,
        "eligibility": "opt-in per customer and approval per business",
        "evidence": "Meta, 'Marketing Messages' — paid, opt-in, approved businesses only",
        "action": "لازم موافقة العميل + موافقة ميتا على الحساب",
        "built": False,
    },
}

#: States a gated feature may legitimately report, so a UI badge never shows an unknown word.
ROADMAP_STATES = frozenset(
    {AVAILABLE, ACCOUNT_INELIGIBLE, REGION_RESTRICTED, NEEDS_APP_REVIEW, NOT_IMPLEMENTED}
)


def roadmap() -> list[dict[str, Any]]:
    """Every gated WhatsApp feature with its state, who decides, and what the owner can do."""
    return [{"key": key, **spec} for key, spec in ROADMAP.items()]


def state_for(key: str, *, measured: str | None = None) -> dict[str, Any]:
    """One feature's entry, with a measured state when the caller has one.

    A measured state only replaces the declared one when it is a state this registry knows: a
    typo must not become a badge the UI has never seen.
    """
    spec = ROADMAP.get(key)
    if spec is None:
        raise KeyError(key)
    out = {"key": key, **spec}
    if measured in ROADMAP_STATES:
        out["state"] = measured
        out["measured"] = True
    return out
