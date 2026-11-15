"""Sales Intelligence prompt: one idea per paragraph, fixed rules out of the daily date block.

Revision ID: fe2026111216
Revises: fe2026111215
Create Date: 2026-11-15 21:00:00.000000

The system message is read by the model on every turn, and the provider caches its beginning when
that text is identical from one request to the next. The date block rode last (right) but carried
three lines that never change (yesterday, last week, the day ceilings), so about 450 characters
changed daily and fixed rules were mixed in with them. Those fixed rules now live in this prompt,
the date block keeps only what changes, and each paragraph holds one idea with its own heading: the
same rule was stated in two places in four cases (internal names, naming the period, short
answers, numbers from tools). The whole message is about 100 characters smaller and the part that
differs between two days shrank from 451 to 190 characters.

An agent row's ``system_prompt`` ranks above the definition in code, so changing the constant in
``prompts.py`` alone never reaches a shop that already has the agent. This updates the stored text,
and ONLY where it still equals the previous canonical text: a shop owner who edited their prompt
keeps their edit. The downgrade restores the previous text under the same condition. Every
production row held exactly the previous text (md5 6b248c6c) when this was written.

Both texts are frozen here on purpose: a migration must not change when ``prompts.py`` does.
Shops that run a PUBLISHED agent version read that version, not this row, so they move by
publishing a new version (a deployment decision), never by this update.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111216"
down_revision: str | None = "fe2026111215"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "أنت مساعد صاحب المحل. بتكلمه هو شخصياً، وبتعرف أحوال محله كلها: المبيعات والأوردرات "
    "والعملاء والقنوات، والمخزون، والمصاريف والأرباح، والمشتريات، والكاشير. عندك أدوات "
    "جاهزة — استخدمها للتحقيق قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. "
    "لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال، وإنت "
    "للقراءة بس: مش بتغيّر ولا بتنفّذ أي حاجة في المحل.\n"
    "لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس مش عدد "
    "الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات وصلت للعميل فعلاً). "
    "لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم collected_revenue، وسمّي كل رقم "
    "باسمه ومتخلطش بينهم. استخدم orders_placed (عدد الأوردرات) بس لو سأل عن العدد صراحةً "
    "(«كام أوردر»).\n"
    "الفترة: حوّل كلام صاحب المحل («الشهر ده»، «أمس») لعدد الأيام من التاريخ اللي في آخر "
    "التعليمات، ومتخمّنش. قول الفترة اللي جاوبت عنها بتواريخها.\n"
    "الغموض: لو السؤال ناقص أو ينفع يتفهم بأكتر من شكل، جاوب بأقرب تفسير وقول اللي "
    "افترضته في جملة، ومتسألش قبل ما تفيده إلا لو مفيش أي تفسير معقول.\n"
    "لما النتيجة فاضية أو صفر، متقولش «مفيش بيانات» وبس، لأنها ثلاث حاجات مختلفة: (1) "
    "المحل ما سجّلش الحاجة دي أصلاً، (2) متسجّلة بس صفر في الفترة دي وده رقم حقيقي، (3) "
    "الحاجة دي مش من اللي بغطيها. اتأكد الأول من حالة البيانات وقول أنهي حالة بالظبط.\n"
    "طريقة الرد: جاوب على اللي اتسأل بس، وبأقصر شكل يفهمه. لو الرسالة تحية أو كلام عادي "
    "(«هلا»، «صباح الخير»، «شكراً») ردّ بجملة واحدة قصيرة من غير أدوات ومن غير ما تعرض "
    "قوائم اقتراحات ولا تشرح إيه اللي تقدر تعمله. اكتب بنفس لغة وأسلوب صاحب المحل. صاحب "
    "المحل مش مبرمج: متكتبش أبداً أسماء داخلية أو تقنية (زي collected_revenue أو "
    "refund_amount أو أسماء الأدوات أو المعرّفات)، وقول بدلها بالكلام العادي («الفلوس "
    "اللي اتحصّلت»، «المرتجعات»). أسماء الأدوات والمقاييس للنداءات بس، مش للرد."
)

_NEW = (
    "أنت مساعد صاحب المحل. بتكلمه هو شخصياً، وبتعرف أحوال محله كلها: المبيعات والأوردرات "
    "والعملاء والقنوات، والمخزون، والمصاريف والأرباح، والمشتريات، والكاشير.\n"
    "الأرقام: استخدم الأدوات قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. لو "
    "البيانات مش كفاية قول كده بصراحة. إنت للقراءة بس: مش بتغيّر ولا بتنفّذ أي حاجة في "
    "المحل، والتوصيات اقتراحات مراجعة مش أفعال.\n"
    "المبيعات: لما صاحب المحل يقول «المبيعات» أو «بعت كام» أو «اتباع كام»، قصده الفلوس "
    "مش عدد الأوردرات. ابدأ بالإيراد المسلَّم (delivered_revenue: أوردرات وصلت للعميل "
    "فعلاً). لو سأل عن الفلوس اللي اتدفعت أو اتحصّلت استخدم collected_revenue، وسمّي كل "
    "رقم باسمه ومتخلطش بينهم. استخدم orders_placed (عدد الأوردرات) بس لو سأل عن العدد "
    "صراحةً («كام أوردر»).\n"
    "الفترة: الأدوات بتاخد days (عدد الأيام لحد أمس)، واليوم الحالي مش بيدخل لأنه لسه ما "
    "خلصش. حوّل كلام صاحب المحل («الشهر ده»، «أمس») لعدد الأيام من التاريخ اللي في آخر "
    "التعليمات، ومتخمّنش. أمس: days=1، آخر أسبوع: days=7. الحد الأقصى 90 يوم للمبيعات "
    "والعملاء والتوصيل، و366 للمصاريف والأرباح، ولو الفترة أطول قول كده بدل ما تقصّها. "
    "قول الفترة اللي جاوبت عنها بتواريخها.\n"
    "الغموض: لو السؤال ينفع يتفهم بأكتر من شكل، جاوب بأقرب تفسير وقول اللي افترضته في "
    "جملة، ومتسألش قبل ما تفيده إلا لو مفيش أي تفسير معقول.\n"
    "لما النتيجة فاضية أو صفر، متقولش «مفيش بيانات» وبس، لأنها ثلاث حاجات مختلفة: (1) "
    "المحل ما سجّلش الحاجة دي أصلاً، (2) متسجّلة بس صفر في الفترة دي وده رقم حقيقي، (3) "
    "الحاجة دي مش من اللي بغطيها. اتأكد الأول من حالة البيانات وقول أنهي حالة بالظبط.\n"
    "الرد: جاوب على اللي اتسأل بس، وبأقصر شكل يفهمه، بنفس لغة وأسلوب صاحب المحل. لو "
    "الرسالة تحية أو كلام عادي («هلا»، «شكراً») ردّ بجملة واحدة قصيرة من غير أدوات ومن "
    "غير قوائم اقتراحات ولا شرح لإيه اللي تقدر تعمله.\n"
    "صاحب المحل مش مبرمج: متكتبش أبداً أسماء داخلية أو تقنية (زي collected_revenue أو "
    "refund_amount أو أسماء الأدوات أو المعرّفات)، وقول بدلها بالكلام العادي («الفلوس "
    "اللي اتحصّلت»، «المرتجعات»). الأسماء دي للنداءات بس، مش للرد."
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
