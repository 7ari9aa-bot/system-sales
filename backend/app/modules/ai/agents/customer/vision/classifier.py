"""Image-kind gating (spec §11/§12.5).

The model PROPOSES image_kind; this module DECIDES what that kind may do.
Only product photos run the retrieval pipeline — a payment receipt or a
damage photo goes to a human, always, and no confirmation of payment can
ever come from an image (spec rule 07).
"""

from __future__ import annotations

from app.modules.ai.agents.customer.vision.schemas import ImageKind

# Kinds the retrieval pipeline accepts.
PIPELINE_KINDS: frozenset[ImageKind] = frozenset({ImageKind.PRODUCT})

# Kinds that must reach a human instead — the reason string names it so the
# model can hand over with the right context without inventing one.
HANDOFF_KINDS: dict[ImageKind, str] = {
    ImageKind.PAYMENT_PROOF: "payment_proof_requires_human",
    ImageKind.COMPLAINT: "complaint_requires_human",
}


def classify(kind: ImageKind) -> tuple[bool, str | None]:
    """(pipeline_allowed, handoff_reason). An allowed kind carries None."""
    if kind in PIPELINE_KINDS:
        return True, None
    if kind in HANDOFF_KINDS:
        return False, HANDOFF_KINDS[kind]
    return False, "not_a_product_image"
