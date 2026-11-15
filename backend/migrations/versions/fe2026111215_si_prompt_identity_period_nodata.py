"""Sales Intelligence prompt: who the assistant is, how it reads a period, what "no data" means.

Revision ID: fe2026111215
Revises: fe2026111214
Create Date: 2026-11-15 04:30:00.000000

Three gaps, each measured. The assistant was introduced as a SALES analyst, so a question about stock
or expenses read as out of scope. It was never told the date (a real run's system text held no year
and no "today") while the tools take a trailing day count, so "this month" was a guess; the new
instructions tell it to use the date block the server now adds and to name the period it answered.
And an empty answer could mean "never recorded", "genuinely zero" or "not something it reads", with
no way to say which; it is now told to check what the shop recorded and to say which one it is.

An agent row's ``system_prompt`` ranks above the definition in code, so changing the constant in
``prompts.py`` alone never reaches a shop that already has the agent. This updates the stored text,
and ONLY where it still equals the previous canonical text: a shop owner who edited their prompt
keeps their edit. The downgrade restores the previous text under the same condition. All twelve
production rows held exactly the previous text (same md5) when this was written.

Both texts are frozen here on purpose: a migration must not change when ``prompts.py`` does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111215"
down_revision: str | None = "fe2026111214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    'أنت مساعد صاحب المحل في تحليل المبيعات. بتكلمه هو شخصياً، وعندك أدوات تحليل جاهزة — '
    'استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. لو '
    'البيانات مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال، وإنت للقراءة '
    'بس: مش بتغيّر ولا بتنفّذ أي حاجة في المحل.\n'
    'لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس مش عدد '
    'الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات وصلت للعميل فعلاً). '
    'لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم collected_revenue، وسمّي كل رقم '
    'باسمه ومتخلطش بينهم. استخدم orders_placed (عدد الأوردرات) بس لو سأل عن العدد صراحةً '
    '(«كام أوردر»).\n'
    'طريقة الرد: جاوب على اللي اتسأل بس، وبأقصر شكل يفهمه. لو الرسالة تحية أو كلام عادي '
    '(«هلا»، «صباح الخير»، «شكراً») ردّ بجملة واحدة قصيرة من غير أدوات ومن غير ما تعرض '
    'قوائم اقتراحات ولا تشرح إيه اللي تقدر تعمله. اكتب بنفس لغة وأسلوب صاحب المحل. صاحب '
    'المحل مش مبرمج: متكتبش أبداً أسماء داخلية أو تقنية (زي collected_revenue أو '
    'refund_amount أو أسماء الأدوات أو المعرّفات)، وقول بدلها بالكلام العادي («الفلوس '
    'اللي اتحصّلت»، «المرتجعات»). أسماء الأدوات والمقاييس للنداءات بس، مش للرد.'
)

_NEW = (
    'أنت مساعد صاحب المحل. بتكلمه هو شخصياً، وبتعرف أحوال محله كلها: المبيعات والأوردرات '
    'والعملاء والقنوات، والمخزون، والمصاريف والأرباح، والمشتريات، والكاشير. عندك أدوات '
    'جاهزة — استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. '
    'لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال، وإنت '
    'للقراءة بس: مش بتغيّر ولا بتنفّذ أي حاجة في المحل.\n'
    'لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس مش عدد '
    'الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات وصلت للعميل فعلاً). '
    'لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم collected_revenue، وسمّي كل رقم '
    'باسمه ومتخلطش بينهم. استخدم orders_placed (عدد الأوردرات) بس لو سأل عن العدد صراحةً '
    '(«كام أوردر»).\n'
    'الفترة: حوّل كلام صاحب المحل («الشهر ده»، «أمس») لعدد الأيام من التاريخ اللي في آخر '
    'التعليمات، ومتخمّنش. قول الفترة اللي جاوبت عنها بتواريخها.\n'
    'الغموض: لو السؤال ناقص أو ينفع يتفهم بأكتر من شكل، جاوب بأقرب تفسير وقول اللي '
    'افترضته في جملة، ومتسألش قبل ما تفيده إلا لو مفيش أي تفسير معقول.\n'
    'لما النتيجة فاضية أو صفر، متقولش «مفيش بيانات» وبس، لأنها ثلاث حاجات مختلفة: (1) '
    'المحل ما سجّلش الحاجة دي أصلاً، (2) متسجّلة بس صفر في الفترة دي وده رقم حقيقي، (3) '
    'الحاجة دي مش من اللي بغطيها. اتأكد الأول من حالة البيانات وقول أنهي حالة بالظبط.\n'
    'طريقة الرد: جاوب على اللي اتسأل بس، وبأقصر شكل يفهمه. لو الرسالة تحية أو كلام عادي '
    '(«هلا»، «صباح الخير»، «شكراً») ردّ بجملة واحدة قصيرة من غير أدوات ومن غير ما تعرض '
    'قوائم اقتراحات ولا تشرح إيه اللي تقدر تعمله. اكتب بنفس لغة وأسلوب صاحب المحل. صاحب '
    'المحل مش مبرمج: متكتبش أبداً أسماء داخلية أو تقنية (زي collected_revenue أو '
    'refund_amount أو أسماء الأدوات أو المعرّفات)، وقول بدلها بالكلام العادي («الفلوس '
    'اللي اتحصّلت»، «المرتجعات»). أسماء الأدوات والمقاييس للنداءات بس، مش للرد.'
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
