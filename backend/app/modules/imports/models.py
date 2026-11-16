"""IMPORTS domain models: one session per uploaded file, one row per source row.

A session is the durable handle of a merchant's import (file, column mapping, options,
verdict). ``import_rows`` holds every source row so validation, preview, retry and the error
report all read from the database instead of re-parsing the file, and so a batch that is
retried after a crash can skip what is already ``applied`` (the idempotency key is
``(session_id, sheet, row_number)``).

Enum-like columns are String with the allowed values written inline, never sa.Enum.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import IdMixin, TenantMixin, TimestampMixin

SESSION_STATUSES = (
    "uploaded",
    "analyzed",
    "mapped",
    "validating",
    "validated",
    "running",
    "completed",
    "failed",
    "cancelled",
)
ROW_STATUSES = ("pending", "valid", "error", "applied", "skipped")
SESSION_KINDS = ("products", "stock", "images", "customers")


class ImportSession(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "import_sessions"

    # allowed: products | stock | images | customers
    kind: Mapped[str] = mapped_column(String(15))
    # allowed: uploaded | analyzed | mapped | validating | validated | running | completed
    #          | failed | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="uploaded")
    file_key: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    # sheet -> {source column -> fihrist field}
    mapping: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # duplicate_policy (create_only | update | skip), blank_policy (keep | clear)
    options: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # counters shown by the preview and the final report
    stats: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('products','stock','images','customers')", name="ck_import_sessions_kind"
        ),
        CheckConstraint(
            "status IN ('uploaded','analyzed','mapped','validating','validated','running',"
            "'completed','failed','cancelled')",
            name="ck_import_sessions_status",
        ),
        Index("ix_import_sessions_tenant_created", "tenant_id", "created_at"),
    )


class ImportRow(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "import_rows"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_sessions.id", ondelete="CASCADE")
    )
    sheet: Mapped[str] = mapped_column(String(63))
    row_number: Mapped[int] = mapped_column(Integer)
    # the cells as the merchant wrote them, keyed by the SOURCE column header
    raw: Mapped[dict] = mapped_column(JSONB)
    # allowed: pending | valid | error | applied | skipped
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    # list of {"field": str | None, "code": str, "message": str}
    errors: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # what the row became: {"product_id": ..., "variant_id": ..., "action": "created|updated"}
    applied_ref: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("session_id", "sheet", "row_number", name="uq_import_rows_position"),
        CheckConstraint(
            "status IN ('pending','valid','error','applied','skipped')",
            name="ck_import_rows_status",
        ),
        Index("ix_import_rows_session_status", "session_id", "status"),
    )
