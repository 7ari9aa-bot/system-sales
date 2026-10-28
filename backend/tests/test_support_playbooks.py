"""Support playbooks: recurring problems solved by merchant-written steps.

The agent only EXPLAINS the steps; nothing here executes. These run the real
handler and the real runtime, with only the model scripted.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.customer.tools import _find_support_playbook
from app.modules.ai.models import SupportPlaybook
from tests.test_customer_agent_store_info_e2e import (
    _calls,
    _customer_agent,
    _says,
    _script,
    _turn,
)

LATE_ORDER = dict(
    title="تأخر الطلب",
    problem="الطلب اتأخر ولسه موصلنيش، فين الأوردر بتاعي",
    steps=[
        "اطلب من العميل رقم الطلب",
        "اتأكد من حالة الشحنة من لوحة الطلبات",
        "لو الشحنة خرجت للتوصيل، قول له يتوقع الوصول خلال اليوم",
    ],
    escalate_when="الطلب متأخر أكتر من 5 أيام أو العميل بيطلب استرداد",
)
WRONG_SIZE = dict(
    title="مقاس غلط",
    problem="المقاس اللي وصلني غلط، المقاس مش مظبوط عليا",
    steps=["اطلب صورة للمنتج والتيكيت", "اشرح خطوات الاستبدال"],
    escalate_when="العميل مصمم على استرجاع فلوسه",
)


async def _seed(db, tenant_id, *rows, active=True):
    for row in rows:
        db.add(SupportPlaybook(tenant_id=tenant_id, is_active=active, **row))
    await db.flush()


@pytest.mark.parametrize(
    "phrasing",
    [
        "الطلب اتأخر",
        "الاوردر لسه موصلش",
        "فين الطلب بتاعي",
        "طلبي اتاخر اوي",
        "الأوردر متأخر",
    ],
)
async def test_one_problem_phrased_many_colloquial_ways_finds_the_same_playbook(
    db, tenant_ctx, phrasing
):
    """The core retrieval claim: a customer never repeats the merchant's wording."""
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, WRONG_SIZE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem=phrasing)

    assert out["matched"] >= 1, phrasing
    assert out["playbooks"][0]["title"] == "تأخر الطلب", phrasing


async def test_a_different_problem_ranks_its_own_playbook_first(db, tenant_ctx):
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, WRONG_SIZE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem="المقاس غلط عايز اغيره")

    assert out["playbooks"][0]["title"] == "مقاس غلط"


async def test_no_match_says_zero_so_the_agent_hands_over_instead_of_guessing(db, tenant_ctx):
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, WRONG_SIZE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem="عايز اعرف الطقس بكرة")

    assert out == {"matched": 0, "playbooks": []}


async def test_an_inactive_playbook_is_never_returned(db, tenant_ctx):
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, active=False)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem="الطلب اتأخر")

    assert out["matched"] == 0


async def test_the_database_refuses_a_playbook_written_for_another_tenant(db, tenant_ctx):
    """Isolation is enforced by RLS, not just by the query's WHERE clause: a
    session scoped to one tenant cannot even INSERT a row for another."""
    import uuid

    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        await _seed(db, uuid.uuid4(), LATE_ORDER)


async def test_steps_and_escalation_condition_come_back_intact(db, tenant_ctx):
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER)

    hit = (await _find_support_playbook(db, tenant_ctx.tenant_id, problem="الطلب اتأخر"))[
        "playbooks"
    ][0]

    assert hit["steps"] == LATE_ORDER["steps"]
    assert hit["escalate_when"] == LATE_ORDER["escalate_when"]


@pytest.mark.parametrize(
    "unrelated",
    [
        "عايز اعرف الطقس بكرة",
        "ازاي اعمل حساب",
        "بكام الشحن لاسكندرية",
        "في خصم على المنتج",
        "اهلا",
        "شكرا ليك",
    ],
)
async def test_unrelated_questions_do_not_match_a_playbook(db, tenant_ctx, unrelated):
    """Folding and suffix-stripping widen the match; they must not widen it into
    noise. A false positive here is the agent confidently explaining the wrong
    fix to a customer, which is worse than handing over."""
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, WRONG_SIZE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem=unrelated)

    assert out["matched"] == 0, (unrelated, [p["title"] for p in out["playbooks"]])


@pytest.mark.parametrize(
    "phrasing",
    [
        "عايز اغير المقاس",  # عايز is a stopword; المقاس must carry the match
        "ازاي ارجع المقاس الغلط",  # ازاي is a stopword
        "فين الاوردر بتاعي",  # فين is a stopword; الاوردر must carry it
        "ممكن تقولي الطلب اتاخر ليه",  # ممكن/ليه around the real topic
    ],
)
async def test_stopwords_around_the_real_topic_still_find_the_playbook(db, tenant_ctx, phrasing):
    """Dropping function words must not drop the question: the topic word is
    still there to match."""
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER, WRONG_SIZE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem=phrasing)

    assert out["matched"] >= 1, phrasing


async def test_a_question_made_only_of_stopwords_matches_nothing(db, tenant_ctx):
    await _seed(db, tenant_ctx.tenant_id, LATE_ORDER)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem="ممكن ازاي")

    assert out == {"matched": 0, "playbooks": []}


# ----------------------------------------------------- through the real runtime


async def test_a_playbook_figure_the_tool_returned_is_a_legitimate_source(
    db, tenant_ctx, monkeypatch
):
    """The playbook says "5 أيام". The agent repeats it after calling the tool,
    so it is backed by the ledger and must NOT be withheld."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    await _seed(db, tenant_id, LATE_ORDER)
    _script(
        monkeypatch,
        _calls("find_support_playbook", problem="الطلب اتأخر"),
        _says("أكيد، ابعتلي رقم الطلب الأول. ولو عدّى أكتر من 5 أيام هنحولك لزميل."),
    )

    outcome = await _turn(db, tenant_id, agent, "الطلب اتأخر")

    assert outcome.blocked_reason is None
    assert "5 أيام" in outcome.reply


async def test_a_figure_not_in_the_playbook_is_still_withheld(db, tenant_ctx, monkeypatch):
    """The playbook backs ITS numbers only. An invented "3 أيام" is not covered."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    await _seed(db, tenant_id, LATE_ORDER)
    _script(
        monkeypatch,
        _calls("find_support_playbook", problem="الطلب اتأخر"),
        _says("هيوصلك خلال 3 أيام بإذن الله."),
    )

    outcome = await _turn(db, tenant_id, agent, "الطلب اتأخر")

    assert outcome.reply is None
    assert outcome.blocked_reason is not None


async def test_the_model_can_hand_over_when_no_playbook_matches(db, tenant_ctx, monkeypatch):
    """matched=0 reaches the model as a stated fact; it escalates, then says
    goodbye in its own words (no template)."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    await _seed(db, tenant_id, WRONG_SIZE)
    seen = _script(
        monkeypatch,
        _calls("find_support_playbook", problem="الفاتورة فيها غلطة"),
        _calls(
            "handover_to_human",
            reason="missing_data",
            summary="العميل بيشتكي من غلطة في الفاتورة ومفيش حل مكتوب",
        ),
        _says("هحولك لحد من الفريق يراجع الفاتورة معاك."),
    )

    outcome = await _turn(db, tenant_id, agent, "الفاتورة فيها غلطة")

    tool_results = " ".join(
        str(m["content"]) for m in seen["calls"][1]["messages"] if m.get("role") == "tool"
    )
    assert '"matched": 0' in tool_results or "'matched': 0" in tool_results
    assert outcome.reply and "الفريق" in outcome.reply


async def test_the_agent_is_offered_the_playbook_tool(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    seen = _script(monkeypatch, _says("أهلا"))

    await _turn(db, tenant_id, agent, "السلام عليكم")

    offered = {t["function"]["name"] for t in seen["calls"][0]["tools"]}
    assert "find_support_playbook" in offered
    assert {"get_store_info", "handover_to_human"} <= offered


# ------------------------------------------------ a realistic multi-playbook store

_STORE = [
    dict(
        title="تأخر الطلب",
        problem="الطلب اتأخر ولسه موصلنيش، فين الأوردر بتاعي",
        steps=["اطلب رقم الطلب"],
        escalate_when="متأخر أكتر من 5 أيام",
    ),
    dict(
        title="مقاس غلط",
        problem="المقاس اللي وصلني غلط، المقاس مش مظبوط عليا",
        steps=["اطلب صورة التيكيت"],
        escalate_when="العميل مصمم على استرجاع الفلوس",
    ),
    dict(
        title="الدفع مارضيش",
        problem="الدفع بالكارت مارضيش يتم والعملية فشلت",
        steps=["اتأكد من رصيد الكارت"],
        escalate_when="اتخصم من الكارت ومفيش طلب",
    ),
    dict(
        title="تتبع الشحنة",
        problem="عايز اتتبع الشحنة واعرف رقم التتبع",
        steps=["ابعت رقم التتبع"],
        escalate_when="مفيش رقم تتبع",
    ),
    dict(
        title="منتج وصل بايظ",
        problem="المنتج وصلني مكسور او فيه عيب تالف",
        steps=["اطلب صور العيب"],
        escalate_when="العميل بيطلب استرداد",
    ),
    dict(
        title="تغيير العنوان",
        problem="عايز اغير عنوان التوصيل قبل ما الطلب يخرج",
        steps=["اطلب العنوان الجديد"],
        escalate_when="الطلب خرج للشحن",
    ),
]

# (what the customer says, the title that SHOULD come back first, or None = no playbook)
_REAL_WORLD = [
    ("الاوردر بتاعي لسه موصلش", "تأخر الطلب"),
    ("طلبي اتاخر اوي", "تأخر الطلب"),
    ("المقاس مش مظبوط", "مقاس غلط"),
    ("الكارت مارضيش يدفع", "الدفع مارضيش"),
    ("فين رقم تتبع الشحنة", "تتبع الشحنة"),
    ("المنتج وصلني مكسور", "منتج وصل بايظ"),
    ("عايز اغير العنوان", "تغيير العنوان"),
    # Questions that look like complaints but have NO written solution:
    ("الفاتورة فيها غلطة", None),
    ("الموظف كان وحش معايا", None),
    ("عايز اعرف بتفتحوا امتى", None),
]


@pytest.mark.parametrize("said,expected", _REAL_WORLD)
async def test_realistic_phrasings_find_the_right_playbook_or_none(db, tenant_ctx, said, expected):
    await _seed(db, tenant_ctx.tenant_id, *_STORE)

    out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem=said)

    if expected is None:
        assert out["matched"] == 0, (said, [p["title"] for p in out["playbooks"]])
    else:
        titles = [p["title"] for p in out["playbooks"]]
        assert titles and titles[0] == expected, (said, titles)


async def test_keyword_search_cannot_bridge_synonyms_the_merchant_did_not_write(db, tenant_ctx):
    """A KNOWN limit, pinned so nobody mistakes it for a bug. "فيزا" is not
    "كارت" and "صغير" is not "مقاس غلط" to a keyword search; bridging that is
    what an embedding does. Loosening the threshold to catch these would bring
    back the wrong-fix false positives, so the answer is operational: the
    merchant lists the customer's own wordings in `problem` (see next test)."""
    await _seed(db, tenant_ctx.tenant_id, *_STORE)

    for said in ("لبست المنتج والمقاس صغير عليا", "حاولت ادفع بالفيزا وفشلت"):
        out = await _find_support_playbook(db, tenant_ctx.tenant_id, problem=said)
        assert out["matched"] == 0, said


async def test_listing_the_customers_own_wordings_in_problem_closes_the_gap(db, tenant_ctx):
    rows = [dict(r) for r in _STORE]
    rows[1]["problem"] += "، المقاس صغير عليا، لبسته وضيق، المقاس كبير"
    rows[2]["problem"] += "، الفيزا مارضيتش، ادفع بالفيزا وفشلت، الماستر كارد"
    await _seed(db, tenant_ctx.tenant_id, *rows)

    size = await _find_support_playbook(
        db, tenant_ctx.tenant_id, problem="لبست المنتج والمقاس صغير عليا"
    )
    pay = await _find_support_playbook(db, tenant_ctx.tenant_id, problem="حاولت ادفع بالفيزا وفشلت")

    assert size["playbooks"][0]["title"] == "مقاس غلط"
    assert pay["playbooks"][0]["title"] == "الدفع مارضيش"
