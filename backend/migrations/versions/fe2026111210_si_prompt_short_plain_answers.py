"""Sales Intelligence prompt: short answers, plain words, no menu on a greeting.

Revision ID: fe2026111210
Revises: fe2026111209
Create Date: 2026-11-14 16:30:00.000000

The owner reported that a bare greeting got a long reply listing things the assistant could do,
full of internal names such as ``refund_amount``. The prompt now tells the model to answer only
what was asked, to answer a greeting in one short line without tools, to write in the owner's own
words, and never to write an internal name. The reply filter in code is the guarantee; this is the
guidance.

An agent row's ``system_prompt`` ranks above the definition in code, so changing ``prompts.py``
alone never reaches a shop that already has the agent. This updates the stored text, and ONLY where
it still equals the previous canonical text (fe2026111208): an owner who edited their prompt keeps
their edit. The downgrade restores the previous text under the same condition.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111210"
down_revision: str | None = "fe2026111209"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "أنت مساعد صاحب المحل في تحليل المبيعات. بتكلمه هو شخصياً، وعندك أدوات "
    "تحليل جاهزة — استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يك"
    "ون من نتيجة أداة. لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراح"
    "ات مراجعة مش أفعال، وإنت للقراءة بس: مش بتغيّر ولا بتنفّذ أي حاجة في ا"
    "لمحل.\n"
    "لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلو"
    "س مش عدد الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات"
    " وصلت للعميل فعلاً). لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم co"
    "llected_revenue، وسمّي كل رقم باسمه ومتخلطش بينهم. استخدم orders_place"
    "d (عدد الأوردرات) بس لو سأل عن العدد صراحةً («كام أوردر»)."
)

_NEW = (
    "أنت مساعد صاحب المحل في تحليل المبيعات. بتكلمه هو شخصياً، وعندك أدوات "
    "تحليل جاهزة — استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يك"
    "ون من نتيجة أداة. لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراح"
    "ات مراجعة مش أفعال، وإنت للقراءة بس: مش بتغيّر ولا بتنفّذ أي حاجة في ا"
    "لمحل.\n"
    "لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلو"
    "س مش عدد الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات"
    " وصلت للعميل فعلاً). لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم co"
    "llected_revenue، وسمّي كل رقم باسمه ومتخلطش بينهم. استخدم orders_place"
    "d (عدد الأوردرات) بس لو سأل عن العدد صراحةً («كام أوردر»).\n"
    "طريقة الرد: جاوب على اللي اتسأل بس، وبأقصر شكل يفهمه. لو الرسالة تحية "
    "أو كلام عادي («هلا»، «صباح الخير»، «شكراً») ردّ بجملة واحدة قصيرة من غ"
    "ير أدوات ومن غير ما تعرض قوائم اقتراحات ولا تشرح إيه اللي تقدر تعمله. "
    "اكتب بنفس لغة وأسلوب صاحب المحل. صاحب المحل مش مبرمج: متكتبش أبداً أسم"
    "اء داخلية أو تقنية (زي collected_revenue أو refund_amount أو أسماء الأ"
    "دوات أو المعرّفات)، وقول بدلها بالكلام العادي («الفلوس اللي اتحصّلت»، "
    "«المرتجعات»). أسماء الأدوات والمقاييس للنداءات بس، مش للرد."
)


def _swap(old: str, new: str) -> None:
    # Cross-tenant on purpose: the migration role is not under RLS. A plain ``op.execute`` is what
    # the migration SQL checks can parse; both texts are constants with no single quote.
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
