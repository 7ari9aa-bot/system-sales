"""Sales Intelligence prompt: "sales" starts from DELIVERED revenue.

Revision ID: fe2026111208
Revises: fe2026111207
Create Date: 2026-11-14 00:40:00.000000

The owner decided that "how much did I sell" means the money from orders that reached the customer.
Collected money lags the real sale on cash on delivery, and ``collected_revenue`` cannot be split by
channel, product or governorate, while ``delivered_revenue`` can. fe2026111206 (already in production)
told the assistant to start from collected, so this moves every shop that still holds exactly that text.

An agent row's ``system_prompt`` ranks above the definition in code, so changing the constant in
``prompts.py`` alone never reaches a shop that already has the agent. This updates the stored text,
and ONLY where it still equals the previous canonical text: a shop owner who edited their prompt
keeps their edit. The downgrade restores the previous text under the same condition.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111208"
down_revision: str | None = "fe2026111207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "أنت مساعد صاحب المحل في تحليل المبيعات. بتكلمه هو شخصياً، وعندك أدوات تحليل جاهزة — "
    "استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. لو البيانات "
    "مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال، وإنت للقراءة بس: مش بتغيّر "
    "ولا بتنفّذ أي حاجة في المحل.\n"
    "لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس مش عدد "
    "الأوردرات. ابدأ بالإيراد المحصّل (collected_revenue: اللي اتدفع فعلاً). لو سأل عن اللي "
    "اتسلّم استخدم delivered_revenue، وسمّي كل رقم باسمه ومتخلطش بينهم. استخدم "
    "orders_placed (عدد الأوردرات) بس لو سأل عن العدد صراحةً («كام أوردر»)."
)

_NEW = (
    "أنت مساعد صاحب المحل في تحليل المبيعات. بتكلمه هو شخصياً، وعندك أدوات تحليل جاهزة — "
    "استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. لو البيانات "
    "مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال، وإنت للقراءة بس: مش بتغيّر "
    "ولا بتنفّذ أي حاجة في المحل.\n"
    "لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس مش عدد "
    "الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات وصلت للعميل فعلاً). لو "
    "سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم collected_revenue، وسمّي كل رقم باسمه "
    "ومتخلطش بينهم. استخدم orders_placed (عدد الأوردرات) بس لو سأل عن العدد صراحةً («كام "
    "أوردر»)."
)


def _swap(old: str, new: str) -> None:
    # Cross-tenant on purpose: this runs as the migration role, which RLS does not apply to (the
    # same assumption fe2026100806 documents). Both texts are module constants with no single
    # quote (asserted below), so inlining them is safe, and a plain ``op.execute`` is what the
    # migration SQL checks can parse.
    assert "'" not in old and "'" not in new
    op.execute(
        "UPDATE agents "
        f"   SET system_prompt = '{new}', "
        "       updated_at = now() "
        " WHERE kind = 'sales_intelligence' "
        f"   AND system_prompt = '{old}'"
    )


def upgrade() -> None:
    _swap(_OLD, _NEW)


def downgrade() -> None:
    _swap(_NEW, _OLD)
