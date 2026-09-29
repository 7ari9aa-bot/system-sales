"""Vision pipeline data contracts (spec §12).

Business-level only: the agent never sees cosine distances, reranker scores
or provider ids (§12.3) — a prompt-injected customer cannot fish internals,
and thresholds can move without touching the reply surface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class ImageKind(StrEnum):
    """§12.5 — the classifier's vocabulary. The model proposes it; the
    Gateway enforces what each kind may do (only PRODUCT runs the pipeline)."""

    PRODUCT = "product"
    PAYMENT_PROOF = "payment_proof"
    COMPLAINT = "complaint"
    SIZE_CHART = "size_chart"
    OTHER = "other"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True)
class Candidate:
    """One product-level candidate from retrieval (best image wins per product)."""

    product_id: uuid.UUID
    product_title: str
    image_id: uuid.UUID
    image_url: str
    retrieval_rank: int


@dataclass(slots=True)
class MatchResult:
    """§12.3 — what the agent (and through it, the customer) may learn."""

    confidence: Confidence
    # business-level dicts: {product_id, title, verified, available_variants}
    candidates: list[dict] = field(default_factory=list)
    reason: str | None = None
    as_of: str | None = None
