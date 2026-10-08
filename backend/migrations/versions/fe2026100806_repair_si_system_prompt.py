"""Replace the Sales Intelligence agent's stub system prompt with its definition.

Revision ID: fe2026100806
Revises: fe2026100805
Create Date: 2026-10-09 12:30:00.000000

`identity/bootstrap.seed_tenant_defaults` used to create the canonical agents from
its own hardcoded copy of every field, running BEFORE the AgentDefinition registry
hook — which only fills gaps. The two copies had drifted for the Sales
Intelligence agent: the definition's prompt carries the rule that every figure in
an answer must come from a tool result, while the seeder's copy was a one-line
English stub. So every tenant registered before this wave holds the stub in
`agents.system_prompt`.

It was invisible in production because `run_sales_analysis` passed
`SI_SYSTEM_PROMPT` as an override, and `_resolve_system_prompt` ranks an override
ABOVE the agent row. That override is removed in this same change, so the stored
prompt now governs — which is why the stored prompt has to be repaired here
FIRST. Landing the code change without this row fix would silently downgrade
every existing tenant to the stub.

The WHERE clause matches the stub character for character, which is what makes it
safe:
  * a merchant who edited their agent's prompt is never touched,
  * a tenant provisioned after the registry became the only author already holds
    the real prompt, so it does not match,
  * re-running is a no-op, because after the first pass no row still reads stub.

Cross-tenant by design: this runs as the migration role (postgres/BYPASSRLS), so
RLS does not apply — the same assumption `c3d4e5f6a7b8` documents for its
conversations backfill.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100806"
down_revision: str | None = "fe2026100805"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: What bootstrap.py wrote for `sales_intelligence`, byte-identical to the string
#: in its deleted `canonical_agents` list. No single quotes, so it inlines safely.
_STUB_PROMPT = "You are a senior sales & commercial intelligence analyst."

#: What `agents/sales_intelligence/agent.py:SI_SYSTEM_PROMPT` defines, and what
#: the registry now provisions. Copied as a snapshot: a migration records the
#: value it moved rows to, it does not import application code.
_DEFINITION_PROMPT = (
    "أنت محلل مبيعات المتجر. عندك أدوات تحليل جاهزة — استخدمها للتحقيق "
    "قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. "
    "لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال."
)


def upgrade() -> None:
    op.execute(
        "UPDATE agents "
        f"   SET system_prompt = '{_DEFINITION_PROMPT}', "
        "       updated_at = now() "
        " WHERE kind = 'sales_intelligence' "
        f"   AND system_prompt = '{_STUB_PROMPT}'"
    )


def downgrade() -> None:
    # Deliberately restores nothing. The stub was a defect, and a tenant that has
    # since edited its prompt in the UI cannot be told apart from one this
    # migration wrote — putting the stub back would destroy real configuration.
    pass
