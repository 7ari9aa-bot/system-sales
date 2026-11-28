"""Where an answer's time went, and what the model thought, written while the answer is produced.

The owner sees how long the assistant thought, can open each step to read the model's own thinking,
and gets a plain reason when an answer was slow. Every event is MEASURED where it happens: a model
call is timed around the provider request (in the gateway), a tool around its handler, so nothing
here is estimated or invented. Events are appended to ``ai_chat_messages.trace`` on their own
session while the row is still ``generating``; the page polls the row, so a step appears when it
begins and its thinking when it ends.

Append-only on purpose. A call writes ``start`` when it begins and ``end`` (with its duration,
tokens and thinking) when it returns, and the page joins them by ``id``. Two writers close together
then cannot overwrite each other, the same reason ``progress`` is written in one statement.

Outside a chat turn (a scheduled job, the customer agent) no answer is set and nothing is written.
A failed write is logged and dropped: a missing trace line must never cost the owner the answer.
"""

from __future__ import annotations

import itertools
import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import text

from app.core import db as core_db
from app.core.db import bind_tenant

logger = logging.getLogger(__name__)

# Long enough to read the model's reasoning for one round, short enough that a thread listing with
# many answers stays small. A cut thinking is marked as cut, never silently shortened.
REASONING_MAX_CHARS = 3000


@dataclass
class _Turn:
    tenant_id: uuid.UUID
    message_id: uuid.UUID
    started: float = field(default_factory=time.perf_counter)
    ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def at_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


_TURN: ContextVar[_Turn | None] = ContextVar("chat_trace_turn", default=None)
# What a model call is for. The shared runner's calls are the answer itself; the sales assistant's
# rewrite after a rejected figure or a coverage gap labels its own call, so the owner can see that a
# slow answer was slow because it was written twice.
_PURPOSE: ContextVar[str] = ContextVar("chat_trace_purpose", default="answer")


@contextmanager
def tracing(tenant_id: uuid.UUID, message_id: uuid.UUID):
    """Within this block, model calls and tools are timed onto ``message_id``."""
    token = _TURN.set(_Turn(tenant_id, message_id))
    try:
        yield
    finally:
        _TURN.reset(token)


@contextmanager
def purpose(name: str):
    """Label the model calls made inside this block (``rewrite``, ``fill_gap``)."""
    token = _PURPOSE.set(name)
    try:
        yield
    finally:
        _PURPOSE.reset(token)


def active() -> bool:
    return _TURN.get() is not None


def clip_reasoning(reasoning: str | None) -> tuple[str | None, bool]:
    """The thinking to keep, and whether it was cut."""
    if not isinstance(reasoning, str):
        return None, False
    reasoning = reasoning.strip()
    if not reasoning:
        return None, False
    if len(reasoning) <= REASONING_MAX_CHARS:
        return reasoning, False
    return reasoning[:REASONING_MAX_CHARS].rstrip(), True


async def _append(turn: _Turn, event: dict) -> None:
    try:
        async with core_db.get_sessionmaker()() as session:
            await bind_tenant(session, turn.tenant_id)
            await session.execute(
                text(
                    "UPDATE ai_chat_messages "
                    "   SET trace = COALESCE(trace, '[]'::jsonb) "
                    "               || jsonb_build_array(CAST(:ev AS jsonb)) "
                    " WHERE id = :id AND status = 'generating'"
                ),
                {"id": turn.message_id, "ev": json.dumps(event, ensure_ascii=False)},
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — a missed trace line must never cost the owner the answer
        logger.warning(
            "chat_trace.unwritten message=%s kind=%s", turn.message_id, event.get("kind")
        )


async def start(kind: str, **fields) -> int | None:
    """Write that ``kind`` has begun. Returns its id, or None outside a chat turn."""
    turn = _TURN.get()
    if turn is None:
        return None
    event_id = next(turn.ids)
    event = {"id": event_id, "kind": kind, "phase": "start", "at_ms": turn.at_ms(), **fields}
    if kind == "model":
        event.setdefault("purpose", _PURPOSE.get())
    await _append(turn, event)
    return event_id


async def end(event_id: int | None, kind: str, ms: int, **fields) -> None:
    """Write that event ``event_id`` has ended, with its measured duration."""
    turn = _TURN.get()
    if turn is None or event_id is None:
        return
    await _append(
        turn,
        {"id": event_id, "kind": kind, "phase": "end", "at_ms": turn.at_ms(), "ms": ms, **fields},
    )


# ── Why an answer took the time it took ──────────────────────────────────────────────────────────
# Read from the measured events only. Each reason names what happened and how long it cost, in
# plain Arabic for the owner. Thresholds are where a cost is worth naming, not targets.
LONG_WRITE_TOKENS = 1200
SLOW_TOOL_MS = 2000
SLOW_MS_PER_TOKEN = (
    60  # Qwen writes ~20 ms a token; three times that is the provider, not the length
)
SLOW_CALL_MS = 8000
OTHER_WORTH_NAMING_MS = 3000
MANY_ROUNDS = 4


def _secs(ms: int) -> str:
    return f"{ms / 1000:.1f}"


def _joined(events: list[dict]) -> list[dict]:
    """One record per started event, with its end merged in (an event with no end stays open)."""
    by_id: dict[int, dict] = {}
    for ev in events:
        if not isinstance(ev, dict) or "id" not in ev:
            continue
        rec = by_id.setdefault(ev["id"], {})
        rec.update({k: v for k, v in ev.items() if k != "phase"})
        if ev.get("phase") == "start":
            rec["started_at_ms"] = ev.get("at_ms", 0)
        if ev.get("phase") == "end":
            rec["done"] = True
    return [by_id[k] for k in sorted(by_id)]


def explain(events: list[dict], total_ms: int) -> dict:
    """Where the time went and why, from the measured events. Pure."""
    recs = _joined(events)
    models = [r for r in recs if r.get("kind") == "model" and r.get("done")]
    tools = [r for r in recs if r.get("kind") == "tool" and r.get("done")]
    model_ms = sum(int(r.get("ms") or 0) for r in models)
    tools_ms = sum(int(r.get("ms") or 0) for r in tools)
    other_ms = max(0, total_ms - model_ms - tools_ms)
    reasons: list[str] = []
    codes: list[str] = []

    def why(code: str, line: str) -> None:
        reasons.append(line)
        codes.append(code)

    seen: dict[tuple, int] = {}
    per_tool: dict[str, int] = {}
    for r in tools:
        key = (r.get("tool"), json.dumps(r.get("args") or {}, sort_keys=True, ensure_ascii=False))
        seen[key] = seen.get(key, 0) + 1
        per_tool[r.get("tool") or ""] = per_tool.get(r.get("tool") or "", 0) + 1
    for (tool, _), n in seen.items():
        if n > 1:
            why(
                "repeat_same",
                f"طلب نفس البيانات بالظبط {n} مرات ({tool})، وكل مرة جولة تفكير زيادة",
            )
    for tool, n in per_tool.items():
        if n >= 3 and not any(t == tool and c > 1 for (t, _), c in seen.items()):
            why("repeat_source", f"رجع لنفس المصدر {n} مرات بطلبات مختلفة ({tool})")

    for r in models:
        ms = int(r.get("ms") or 0)
        out = int(r.get("tokens_out") or 0)
        if r.get("purpose") == "rewrite":
            why("rewrite", f"الرد اترفض في مراجعة الأرقام فاتكتب تاني ({_secs(ms)} ث)")
        elif r.get("purpose") == "fill_gap":
            why("fill_gap", f"الرد كان ناقص حاجة من الأرقام فاتكمّل ({_secs(ms)} ث)")
        if out >= LONG_WRITE_TOKENS:
            why("long_write", f"كتب كتير في جولة واحدة (حوالي {out} توكن في {_secs(ms)} ث)")
        elif ms >= SLOW_CALL_MS and ms > SLOW_MS_PER_TOKEN * max(out, 1):
            why("slow_provider", f"جولة اتأخرت عند مزوّد النموذج ({_secs(ms)} ث لـ{out} توكن بس)")
        if r.get("ok") is False:
            why("failed_round", f"جولة فشلت عند المزوّد واتعادت ({_secs(ms)} ث ضايعة)")

    if len(models) >= MANY_ROUNDS:
        avg = model_ms // max(len(models), 1)
        why("many_rounds", f"{len(models)} جولات تفكير، كل جولة حوالي {_secs(avg)} ث")
    for r in tools:
        if int(r.get("ms") or 0) >= SLOW_TOOL_MS:
            why(
                "slow_read",
                f"قراءة «{r.get('step') or r.get('tool')}» أخدت {_secs(int(r['ms']))} ث",
            )
    if other_ms >= OTHER_WORTH_NAMING_MS:
        why("other_time", f"{_secs(other_ms)} ث برّه النموذج والأدوات (مراجعة الرد وحفظه)")

    return {
        "kind": "summary",
        "total_ms": total_ms,
        "model_ms": model_ms,
        "tools_ms": tools_ms,
        "other_ms": other_ms,
        "rounds": len(models),
        "tool_calls": len(tools),
        "tokens_in": sum(int(r.get("tokens_in") or 0) for r in models),
        "tokens_out": sum(int(r.get("tokens_out") or 0) for r in models),
        "reasons": reasons,
        "codes": codes,
    }


async def finish() -> None:
    """Append the summary of this answer's time. Call while the row is still ``generating``."""
    turn = _TURN.get()
    if turn is None:
        return
    total_ms = turn.at_ms()
    try:
        async with core_db.get_sessionmaker()() as session:
            await bind_tenant(session, turn.tenant_id)
            row = await session.execute(
                text("SELECT trace FROM ai_chat_messages WHERE id = :id"), {"id": turn.message_id}
            )
            events = row.scalar_one_or_none() or []
    except Exception:  # noqa: BLE001
        logger.warning("chat_trace.summary_unread message=%s", turn.message_id)
        return
    await _append(turn, {"id": 0, **explain(events, total_ms)})


# What each reason code is called in the shop report: the same causes, without one answer's numbers.
CODE_TEXT = {
    "repeat_same": "طلب نفس البيانات أكتر من مرة",
    "repeat_source": "رجع لنفس المصدر كذا مرة بطلبات مختلفة",
    "rewrite": "الرد اترفض في مراجعة الأرقام فاتكتب تاني",
    "fill_gap": "الرد كان ناقص فاتكمّل",
    "long_write": "كتب كتير في جولة واحدة",
    "slow_provider": "مزوّد النموذج كان بطيء",
    "failed_round": "جولة فشلت عند المزوّد",
    "many_rounds": "جولات تفكير كتير",
    "slow_read": "قراءة بيانات بطيئة",
    "other_time": "وقت برّه النموذج والأدوات",
}


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) // 2


def report(answers: list[tuple[str, list | None]], *, slowest: int = 5) -> dict:
    """Where the assistant's time goes across answers, from their summaries. Pure.

    ``answers`` is ``(question, trace)`` per answer. Answers without a summary (not traced, or
    written before tracing existed) are left out and counted apart, never guessed.
    """
    rows = []
    untraced = 0
    for question, trace in answers:
        summary = next(
            (
                e
                for e in reversed(trace or [])
                if isinstance(e, dict) and e.get("kind") == "summary"
            ),
            None,
        )
        if summary is None or not isinstance(summary.get("total_ms"), int):
            untraced += 1
            continue
        rows.append((question, summary))
    n = len(rows)

    def avg(key: str) -> int:
        return sum(int(s.get(key) or 0) for _, s in rows) // n if n else 0

    counts: dict[str, int] = {}
    for _, s in rows:
        for code in set(s.get("codes") or []):
            if code in CODE_TEXT:
                counts[code] = counts.get(code, 0) + 1
    causes = [
        {"code": c, "text": CODE_TEXT[c], "answers": k}
        for c, k in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    worst = sorted(rows, key=lambda r: -int(r[1]["total_ms"]))[:slowest]
    return {
        "answers": n,
        "untraced": untraced,
        "median_total_ms": _median([int(s["total_ms"]) for _, s in rows]),
        "avg_total_ms": avg("total_ms"),
        "avg_model_ms": avg("model_ms"),
        "avg_tools_ms": avg("tools_ms"),
        "avg_other_ms": avg("other_ms"),
        "avg_rounds": round(sum(int(s.get("rounds") or 0) for _, s in rows) / n, 2) if n else 0,
        "causes": causes,
        "slowest": [
            {
                "question": (q or "")[:200],
                "total_ms": int(s["total_ms"]),
                "model_ms": int(s.get("model_ms") or 0),
                "rounds": int(s.get("rounds") or 0),
                "reasons": list(s.get("reasons") or []),
            }
            for q, s in worst
        ],
    }
