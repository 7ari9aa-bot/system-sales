"""website builder: presentation-truth tables, public read model, admin helpers.

Revision ID: fe2026110505
Revises: fe2026110504
Create Date: 2026-11-05 12:00:00.000000

The website module owns pages / sections / versions / publishing (presentation
truth) and never business truth — commerce entities are referenced by id only.
Five tenant-scoped tables get ENABLE + FORCE + ``tenant_isolation`` from day
one. ``website_published_sites`` deliberately has NO ``tenant_id`` column: it
is the single table the unauthenticated public surface reads, so it needs no
tenant GUC and the Boot Reconciler's every-tenant-table inspection skips it.

Cross-tenant helpers are SECURITY DEFINER functions with a minimal surface,
following the ``resolve_channel_tenant`` precedent:

- ``website_slug_taken(slug)`` — slug uniqueness spans TWO RLS tables
  (``websites`` + ``website_purchases``), which no single per-tenant SELECT can
  answer; paired with a ``pg_advisory_xact_lock`` on the slug at the call site
  this makes the check-then-insert race-safe.
- ``resolve_website_purchase_tenant(purchase_id)`` — lets a platform admin
  confirm or reject a purchase WITHOUT weakening any tenant policy: the
  function returns only the owning tenant id, the route binds that tenant, and
  the actual UPDATE runs under the normal tenant GUC. Whether the purchase is
  still actionable (pending) is a SERVICE decision made after binding — an
  already-activated purchase is a state conflict (409), never a 404.
- ``admin_website_purchases()`` — the owner console's purchase queue (bounded
  to 200 rows); execute is revoked from PUBLIC and granted to sales_app, the
  HTTP layer gates it behind ``require_platform_admin``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "fe2026110505"
down_revision: str | None = "fe2026110504"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TENANT_TABLES = (
    "websites",
    "website_versions",
    "website_pages",
    "website_page_sections",
    "website_purchases",
)


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def _grant_sales_app(statement: str) -> str:
    return f"""DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {statement};
      END IF;
    END
    $$;"""


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "websites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        *_timestamps(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("default_locale", sa.String(8), server_default="ar", nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("theme_tokens", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("navigation", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("published_version_id", sa.Uuid(), nullable=True),
        sa.Column("aggregate_version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("slug", name="uq_websites_slug"),
        sa.CheckConstraint(
            "status IN ('draft','published','suspended','deleted')", name="ck_websites_status"
        ),
    )
    op.create_index("ix_websites_tenant_id", "websites", ["tenant_id"])
    op.create_index(
        "uq_websites_one_live_per_tenant",
        "websites",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    op.create_table(
        "website_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        *_timestamps(),
        sa.Column(
            "website_id",
            sa.Uuid(),
            sa.ForeignKey("websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','published','archived')", name="ck_website_versions_status"
        ),
    )
    op.create_index("ix_website_versions_tenant_id", "website_versions", ["tenant_id"])
    op.create_index("ix_website_versions_website_id", "website_versions", ["website_id"])
    op.create_index(
        "ix_website_versions_website_status", "website_versions", ["website_id", "status"]
    )

    op.create_table(
        "website_pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        *_timestamps(),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("website_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("slug", sa.String(300), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.UniqueConstraint("version_id", "slug", name="uq_website_pages_version_slug"),
    )
    op.create_index("ix_website_pages_tenant_id", "website_pages", ["tenant_id"])
    op.create_index("ix_website_pages_version_id", "website_pages", ["version_id"])

    op.create_table(
        "website_page_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "page_id",
            sa.Uuid(),
            sa.ForeignKey("website_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_type", sa.String(64), nullable=False),
        sa.Column("props", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_index("ix_website_page_sections_tenant_id", "website_page_sections", ["tenant_id"])
    op.create_index("ix_website_page_sections_page_id", "website_page_sections", ["page_id"])

    op.create_table(
        "website_purchases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        *_timestamps(),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending_payment", nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="EGP", nullable=False),
        sa.Column("site_name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("payment_reference", sa.String(200), nullable=True),
        sa.Column(
            "confirmed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "website_id",
            sa.Uuid(),
            sa.ForeignKey("websites.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending_payment','paid','activated','rejected','cancelled')",
            name="ck_website_purchases_status",
        ),
    )
    op.create_index("ix_website_purchases_tenant_id", "website_purchases", ["tenant_id"])
    op.create_index(
        "uq_website_purchases_one_open_per_tenant",
        "website_purchases",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending_payment','paid')"),
    )
    op.create_index(
        "uq_website_purchases_claimed_slug",
        "website_purchases",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending_payment','paid','activated')"),
    )

    # The PUBLIC read model — no tenant_id column by design (see docstring).
    op.create_table(
        "website_published_sites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_timestamps(),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column(
            "website_id",
            sa.Uuid(),
            sa.ForeignKey("websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_locale", sa.String(8), server_default="ar", nullable=False),
        sa.Column("theme_tokens", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("navigation", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("projection", JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_website_published_sites_slug"),
    )
    op.create_index(
        "ix_website_published_sites_website_id", "website_published_sites", ["website_id"]
    )
    op.create_index(
        "uq_website_published_sites_hostname",
        "website_published_sites",
        ["hostname"],
        unique=True,
        postgresql_where=sa.text("hostname IS NOT NULL"),
    )
    op.execute(
        _grant_sales_app(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE website_published_sites TO sales_app"
        )
    )

    for table in _TENANT_TABLES:
        _secure(table)

    # --- cross-tenant SECURITY DEFINER helpers (minimal surfaces) -----------
    op.execute(
        """CREATE OR REPLACE FUNCTION public.website_slug_taken(p_slug text)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS $fn$
          SELECT EXISTS (SELECT 1 FROM public.websites w WHERE w.slug = p_slug)
              OR EXISTS (
                   SELECT 1 FROM public.website_purchases p
                   WHERE p.slug = p_slug
                     AND p.status IN ('pending_payment','paid','activated'))
        $fn$"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.website_slug_taken(text) FROM PUBLIC")
    op.execute(
        _grant_sales_app("GRANT EXECUTE ON FUNCTION public.website_slug_taken(text) TO sales_app")
    )

    op.execute(
        """CREATE OR REPLACE FUNCTION public.resolve_website_purchase_tenant(p_purchase_id uuid)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS $fn$
          SELECT p.tenant_id FROM public.website_purchases p
          WHERE p.id = p_purchase_id
        $fn$"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.resolve_website_purchase_tenant(uuid) FROM PUBLIC")
    op.execute(
        _grant_sales_app(
            "GRANT EXECUTE ON FUNCTION public.resolve_website_purchase_tenant(uuid) TO sales_app"
        )
    )

    op.execute(
        """CREATE OR REPLACE FUNCTION public.admin_website_purchases()
        RETURNS TABLE(
          id uuid, tenant_id uuid, template_id text, status text, price numeric,
          currency text, site_name text, slug text, payment_reference text,
          website_id uuid, created_at timestamptz, confirmed_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS $fn$
          SELECT p.id, p.tenant_id, p.template_id, p.status, p.price, p.currency,
                 p.site_name, p.slug, p.payment_reference, p.website_id,
                 p.created_at, p.confirmed_at
          FROM public.website_purchases p
          ORDER BY p.created_at DESC
          LIMIT 200
        $fn$"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.admin_website_purchases() FROM PUBLIC")
    op.execute(
        _grant_sales_app("GRANT EXECUTE ON FUNCTION public.admin_website_purchases() TO sales_app")
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.admin_website_purchases()")
    op.execute("DROP FUNCTION IF EXISTS public.resolve_website_purchase_tenant(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.website_slug_taken(text)")
    op.drop_table("website_published_sites")
    op.drop_table("website_purchases")
    op.drop_table("website_page_sections")
    op.drop_table("website_pages")
    op.drop_table("website_versions")
    op.drop_table("websites")
