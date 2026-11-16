"""Which tool does a real model pick for an owner's question? (no tool is executed)

The unit tests pin what the tool descriptions SAY; only a model shows whether it picks right. This
sends the real identity prompt and the real eleven tool definitions to any OpenAI-compatible
endpoint, for a fixed set of owner questions, and scores the first tool call against what is
acceptable. Nothing runs against a shop: the call is recorded, not executed.

    EVAL_BASE_URL=https://.../v1 EVAL_API_KEY=... EVAL_MODEL=... \
        python scripts/eval_si_tool_choice.py [--runs 3] [--json out.json]

Exit 0 when every case passes, 1 otherwise, 2 when the endpoint could not be used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field

import httpx

# (question, tools that are a correct first move, params that must hold when given, note)
# Several tools are accepted where a question really is ambiguous; a wrong family is a miss.


@dataclass(frozen=True)
class Case:
    q: str
    ok: tuple[str, ...]
    args: dict[str, object] = field(default_factory=dict)  # required arg values (exact)
    note: str = ""


CASES: tuple[Case, ...] = (
    Case("كام مبيعاتي الشهر ده؟", ("si_metric",), {"mode": "value"}),
    Case("المبيعات زادت ولا قلت عن الشهر اللي فات؟", ("si_metric",), {"mode": "compare"}),
    Case("المبيعات جاية منين، انهي قناة؟", ("si_metric",), {"mode": "split"}),
    Case("يعني إيه صافي الربح عندك؟", ("si_metric",), {"mode": "explain"}),
    Case("ليه المبيعات وقعت الأسبوع ده؟", ("si_metric",), {"mode": "why", "focus": "drivers"}),
    Case(
        "أنهي شركة شحن بترجّع أوردرات كتير؟",
        ("si_metric",),
        {"mode": "why", "focus": "fulfillment"},
    ),
    Case("العملاء بترجع تشتري ولا لا؟", ("si_metric",), {"mode": "why", "focus": "customers"}),
    Case("أنهي أيام الأسبوع أقوى عندي؟", ("si_metric",), {"mode": "why", "focus": "seasonality"}),
    Case("إيه الأكتر مبيعاً عندي؟", ("si_shop",), {"view": "products"}),
    Case("إيه اللي خلص من المخزون؟", ("si_shop",), {"view": "stock"}),
    Case("إيه اللي راكد ومش بيتباع؟", ("si_shop",), {"view": "stock"}),
    Case("صرفت كام الشهر ده؟", ("si_finance",), {"report": "expenses"}),
    Case("أنا كسبان ولا خسران؟", ("si_finance",), {"report": "profit"}),
    Case("عليا كام للموردين؟", ("si_finance",), {"report": "purchasing"}),
    Case("الكاشير باع كام النهارده؟", ("si_shop",), {"view": "cashier"}),
    Case("فين الأوردر رقم 1042؟", ("si_shop",), {"view": "order"}),
    Case("مين أحمد محمود وكام اشترى؟", ("si_shop",), {"view": "customer"}),
    Case("مين بيكلمنا أكتر على واتساب؟", ("si_metric",), {"mode": "activity", "view": "customers"}),
    Case("الناس بتقول إيه على بوستاتنا؟", ("si_metric",), {"mode": "activity", "view": "comments"}),
    Case("عندي إيه بيانات في السيستم؟", ("si_metric",), {"mode": "status"}),
    # the look-alike traps the descriptions were written for
    Case(
        "كام أوردر جالي النهارده؟",
        ("si_metric",),
        {"mode": "value"},
        "total count, not a lookup or the cashier",
    ),
    Case(
        "إجمالي أوردرات الأونلاين الأسبوع ده؟",
        ("si_metric",),
        {"mode": "value"},
        "not the cashier read",
    ),
    Case(
        "هات لي بيانات العميل سارة",
        ("si_shop",),
        {"view": "customer"},
        "one named person",
    ),
    Case(
        "مين أكتر عملاء بيرجعوا يشتروا؟",
        ("si_metric",),
        {"mode": "why", "focus": "customers"},
        "not a lookup",
    ),
)


def _tools() -> list[dict]:
    from app.modules.ai.agents.sales_intelligence import tools as T
    from app.modules.ai.tools import get_tool, tool_to_openai_schema

    T.register_si_tools()
    return [tool_to_openai_schema(get_tool(n)) for n in T.SI_TOOLS]


def _system() -> str:
    from app.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT

    return SI_SYSTEM_PROMPT


async def _ask(client: httpx.AsyncClient, case: Case, tools: list[dict], system: str) -> dict:
    payload = {
        "model": os.environ["EVAL_MODEL"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": case.q}],
        "tools": tools,
        "temperature": 0,
        "max_tokens": 400,
    }
    url = os.environ["EVAL_BASE_URL"].rstrip("/") + "/chat/completions"
    r = await client.post(
        url, json=payload, headers={"Authorization": f"Bearer {os.environ['EVAL_API_KEY']}"}
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    msg = r.json()["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    if not calls:
        return {"tool": None, "args": {}, "text": (msg.get("content") or "")[:80]}
    fn = calls[0]["function"]
    return {"tool": fn["name"], "args": json.loads(fn.get("arguments") or "{}"), "text": ""}


def score(case: Case, got: dict) -> tuple[bool, str]:
    if got["tool"] is None:
        return False, "no tool called"
    if got["tool"] not in case.ok:
        return False, f"picked {got['tool']}"
    for k, v in case.args.items():
        if got["args"].get(k) != v:
            return False, f"{got['tool']} with {k}={got['args'].get(k)!r}, wanted {v!r}"
    return True, ""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--json")
    ns = ap.parse_args()
    for k in ("EVAL_BASE_URL", "EVAL_API_KEY", "EVAL_MODEL"):
        if not os.environ.get(k):
            print(f"missing {k}", file=sys.stderr)
            return 2
    tools, system = _tools(), _system()
    rows, fails = [], Counter()
    async with httpx.AsyncClient(timeout=60) as client:
        for case in CASES:
            for _ in range(ns.runs):
                try:
                    got = await _ask(client, case, tools, system)
                except Exception as exc:  # noqa: BLE001 - report and stop: nothing to score
                    print(f"endpoint unusable: {exc}", file=sys.stderr)
                    return 2
                ok, why = score(case, got)
                rows.append({"q": case.q, "ok": ok, "why": why, **got, "note": case.note})
                if not ok:
                    fails[case.q] += 1
                print(("PASS " if ok else "FAIL ") + case.q + ("" if ok else f"   <- {why}"))
    total = len(rows)
    passed = sum(r["ok"] for r in rows)
    print(f"\n{passed}/{total} correct on {os.environ['EVAL_MODEL']}")
    if ns.json:
        with open(ns.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
