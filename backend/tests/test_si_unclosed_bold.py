"""A bold marker that never closes is removed, so the owner never reads two stray stars.

Found in the live assistant's saved replies: Qwen wrote "قصير ومباشر: **سبتمبر 2026 هو أحسن شهر
عندك" and forgot the closing pair, and the chat page (react-markdown) prints the stars as they
are. A well formed pair is real markdown that the page shows bold, so it is never touched; only
the last unmatched pair on a line goes. The words and every number stay exactly as written. This
is formatting cleanup after the numbers were checked, not a prepared reply.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.ai.agents.sales_intelligence.plain_words import plain_words
from app.modules.ai.gateway import AIGateway
from app.modules.ai.providers import ChatCompletionResult
from tests.test_si_agent import _seed

DIGITS = "299.98 425.00 1112.98 2026-11-15"


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        ("قصير ومباشر: **سبتمبر 2026 هو أحسن شهر", "قصير ومباشر: سبتمبر 2026 هو أحسن شهر"),
        ("رقم 299.98 و**425.00 مفتوح", "رقم 299.98 و425.00 مفتوح"),
        ("**الإيراد 1112.98 من 2026-11-15", "الإيراد 1112.98 من 2026-11-15"),
    ],
)
def test_an_unclosed_bold_loses_only_its_stars(written, shown):
    assert plain_words(written) == shown


@pytest.mark.parametrize(
    "text",
    [
        "عندك **3 عملاء** مسجّلين في النظام.",
        "**الإيراد المسلَّم:** صفر في آخر 30 يوم.",
        "**أ** و**ب** و**ج**",
        "كلام عادي من غير أي نجوم 299.98",
    ],
)
def test_a_well_formed_bold_is_left_alone(text):
    assert plain_words(text) == text


def test_each_line_is_judged_on_its_own():
    out = plain_words("سطر **غامق** سليم\nوسطر **مفتوح هنا\nوسطر عادي")
    assert out == "سطر **غامق** سليم\nوسطر مفتوح هنا\nوسطر عادي"


def test_only_the_last_unmatched_pair_goes_when_a_line_has_a_closed_pair_too():
    assert plain_words("**قفلت** و**فتحت بس") == "**قفلت** وفتحت بس"


def test_the_numbers_are_never_changed():
    out = plain_words(f"**{DIGITS}")
    assert out == DIGITS


def test_an_empty_or_missing_answer_stays_empty():
    assert plain_words(None) == ""
    assert plain_words("") == ""


async def test_a_real_run_never_shows_the_unclosed_stars(db, tenant_ctx, monkeypatch):
    agent = await _seed(db, tenant_ctx.tenant_id)

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return ChatCompletionResult(
            content="**أهلاً بيك، قول لي عايز إيه",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    result = await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="هلا")
    assert "**" not in result.answer
    assert "أهلاً بيك، قول لي عايز إيه" in result.answer


def test_two_open_lines_are_each_fixed_even_though_the_stars_add_up_to_an_even_count():
    # one star pair per line, so the whole text has an even count: judging the whole text
    # instead of each line would leave both stray pairs on the page
    assert plain_words("سطر **مفتوح أول\nوسطر **مفتوح تاني") == "سطر مفتوح أول\nوسطر مفتوح تاني"
