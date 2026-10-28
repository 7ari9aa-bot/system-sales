"""The golden-set case format for the customer agent.

A case is ONE customer conversation plus what must (and must not) happen. It is data, not a
test: the same cases run against a scripted model (CI, proves the wiring) and against a REAL
model (proves behaviour, needs a key). Checks are deterministic where they can be; the
``rubric`` is for the judge and is only used for what code cannot decide (tone, helpfulness).

Design rules, taken from the vendor guidance we read:
- a case that expects NO action is as valuable as one that expects an action;
- check the OUTCOME (the reply, the handover, the tools that ran) not one exact path, because
  there are usually several valid paths to the same correct result;
- every case carries a ``risk`` so a failure on a dangerous one weighs more than a style slip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Category = Literal[
    "product_info",  # price / stock / sizes / photos from the catalogue
    "store_policy",  # returns, exchange, shipping, hours: written or NOT written
    "invoice",  # own invoice by number, exchange of size or colour
    "problem",  # a real problem the playbooks cover
    "handover_wanted",  # the customer asks for a person: must hand over
    "handover_unwanted",  # a plain question: must NOT hand over
    "unknown_answer",  # the data does not contain the answer: say so, never invent
    "out_of_scope",  # not about the store
    "adversarial",  # injection, extraction, pressure, cross-customer
    "vision",  # a photo
    "voice",  # a voice note transcript
]

Risk = Literal["critical", "high", "normal"]
# critical: inventing a policy / a number / a promise, leaking another customer's data,
#           obeying an injected instruction, acting without authority.
# high:     a wrong handover decision, a wrong product or size, a missed explicit human request.
# normal:   tone, length, wording.


@dataclass(frozen=True)
class StoreFixture:
    """What exists in the shop for this case. Anything not listed does NOT exist."""

    products: tuple[dict, ...] = ()  # {"title","variants":[{"size","price","stock"}]}
    policies: dict[str, str] = field(
        default_factory=dict
    )  # kind -> written text; missing = unwritten
    playbooks: tuple[dict, ...] = ()  # {"title","problem","steps","escalate_when"}
    invoices: tuple[dict, ...] = ()  # {"number","items":[{"product","size","qty","price"}]}
    store_info: dict[str, str] = field(default_factory=dict)  # hours, address, ...


@dataclass(frozen=True)
class Expect:
    """Deterministic checks. Every field is optional; an unset field is not checked."""

    handover: bool | None = None  # True = must hand over, False = must NOT
    tools_called: tuple[str, ...] = ()  # each must have been called at least once
    tools_not_called: tuple[str, ...] = ()
    reply_contains_any: tuple[str, ...] = ()  # at least one of these must appear
    reply_contains_all: tuple[str, ...] = ()
    reply_must_not_contain: tuple[str, ...] = ()  # forbidden strings (invented policy, leaked data)
    numbers_allowed_from_store: bool = True  # every numeral must trace to a tool result
    max_reply_chars: int | None = None
    must_ask_clarifying_question: bool | None = None


@dataclass(frozen=True)
class Turn:
    customer: str
    expect: Expect = field(default_factory=Expect)  # checked after THIS turn


@dataclass(frozen=True)
class Case:
    id: str
    category: Category
    risk: Risk
    title: str
    store: StoreFixture
    turns: tuple[Turn, ...]
    channel: str = "whatsapp"
    rubric: tuple[str, ...] = ()  # judge-only criteria, each answerable yes/no
    source: str = "authored"  # authored | production (a real conversation, anonymised)
