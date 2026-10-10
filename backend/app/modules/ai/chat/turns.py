"""Turn execution for the merchant SI chat — spec §SI-chat.

One chat turn = one `run_sales_analysis` execution with bounded history.
Everything numeric is re-queried per turn by the deterministic tools; history
is narrative context only and never numeric authority. The assistant row is
durable BEFORE the model call, so a crash leaves a retryable `failed` row —
never a silently missing answer.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.errors import ConflictError
from app.modules.ai.models import AIChatMessage

HISTORY_MESSAGE_LIMIT = 12  # 6 turns max reach the prompt


def build_structured_blocks(result) -> list[dict]:
    """Server-built render blocks from a validated AnalysisResult.

    A closed vocabulary (chat/schemas.py): text, kpi, findings, notice, refs.
    Money values stay strings — the frontend formats, never parses into math.
    """
    blocks: list[dict] = []
    if result.answer:
        blocks.append({"type": "text", "body": result.answer})
    for f in result.facts[:8]:
        blocks.append(
            {
                "type": "kpi",
                "metric": f.get("metric", ""),
                "label": f.get("metric", "").replace("_", " "),
                "value": str(f.get("value", "")),
                "unit": str(f.get("unit", "")),
                "window": str(f.get("window", "")),
            }
        )
    if result.findings:
        blocks.append(
            {
                "type": "findings",
                "items": [
                    {
                        "statement": f.statement,
                        "type": f.type,
                        "relationship": f.relationship.value,
                        "confidence": f.confidence,
                        "confidence_reasons": f.confidence_reasons,
                        "evidence_refs": f.evidence_refs,
                    }
                    for f in result.findings[:6]
                ],
            }
        )
    if result.data_quality.status.value != "COMPLETE":
        blocks.append(
            {
                "type": "notice",
                "severity": "warning",
                "message": f"data quality: {result.data_quality.status.value.lower()}",
            }
        )
    if result.guardrail_reason:
        blocks.append(
            {
                "type": "notice",
                "severity": "warning",
                "message": f"safe response: {result.guardrail_reason}",
            }
        )
    if result.saved_evidence_id or result.run_id:
        blocks.append(
            {
                "type": "refs",
                "analysis_id": result.saved_evidence_id,
                "run_id": result.run_id,
            }
        )
    return blocks


async def _bounded_history(session, ctx, thread, *, through_seq: int) -> list[dict[str, str]]:
    """Prior turns up to `through_seq`, capped; summary marker replaces the
    pre-summary span once compaction ran (deterministic — never model text)."""
    if thread.summary_through_seq > 0 and thread.context_summary:
        summary_marker = {
            "role": "user",
            "content": f"[Prior conversation summary]\n{thread.context_summary}",
        }
        rows = (
            await session.execute(
                select(AIChatMessage)
                .where(
                    AIChatMessage.tenant_id == ctx.tenant_id,
                    AIChatMessage.thread_id == thread.id,
                    AIChatMessage.sequence_no > thread.summary_through_seq,
                    AIChatMessage.sequence_no <= through_seq,
                )
                .order_by(AIChatMessage.sequence_no.asc())
                .limit(HISTORY_MESSAGE_LIMIT)
            )
        ).scalars().all()
        return [summary_marker] + [
            {"role": m.role, "content": m.content} for m in rows
        ]
    rows = (
        await session.execute(
            select(AIChatMessage)
            .where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.sequence_no <= through_seq,
            )
            .order_by(AIChatMessage.sequence_no.desc())
            .limit(HISTORY_MESSAGE_LIMIT)
        )
    ).scalars().all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


async def _maybe_compact(session, ctx, thread, *, through_seq: int) -> None:
    """Deterministic compaction — NO model call. One line per compacted turn,
    built from the stored structured blocks (metric + window + outcome), so
    the summary can never invent a number the tools did not measure."""
    if through_seq - thread.summary_through_seq <= HISTORY_MESSAGE_LIMIT:
        return
    rows = (
        await session.execute(
            select(AIChatMessage)
            .where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.sequence_no > thread.summary_through_seq,
                AIChatMessage.sequence_no <= through_seq,
                AIChatMessage.role == "assistant",
            )
            .order_by(AIChatMessage.sequence_no.asc())
        )
    ).scalars().all()
    lines: list[str] = []
    for row in rows:
        metrics = [
            b.get("metric", "")
            for b in (row.structured_content or [])
            if isinstance(b, dict) and b.get("type") == "kpi"
        ]
        tail = f" — {', '.join(m for m in metrics if m)}" if metrics else ""
        lines.append(f"turn {row.sequence_no - 1}: {row.status}{tail}")
    thread.context_summary = "\n".join(lines)
    thread.summary_through_seq = through_seq


async def run_chat_turn(session, ctx, thread) -> AIChatMessage:
    """Execute one assistant turn against the SI agent and persist the answer.

    The assistant row is durable (status=generating) before the model call;
    any failure lands the row in `failed` with an error code — a retry
    overwrites THAT row, so a sequence number is never burned twice.
    """
    user_rows = (
        await session.execute(
            select(AIChatMessage)
            .where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.role == "user",
            )
            .order_by(AIChatMessage.sequence_no.desc())
            .limit(1)
            .with_for_update(of=AIChatMessage)  # serialize concurrent submits per thread
        )
    ).scalars().all()
    if not user_rows:
        raise ConflictError("no user message to answer")
    user_row = user_rows[0]
    next_seq = user_row.sequence_no + 1

    # A failed assistant row at the next slot means this is a RETRY: the same
    # slot is overwritten rather than burned (uq thread+seq stays honest).
    assistant = (
        await session.execute(
            select(AIChatMessage).where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.sequence_no == next_seq,
                AIChatMessage.role == "assistant",
            )
        )
    ).scalar_one_or_none()
    if assistant is not None and assistant.status != "failed":
        raise ConflictError("this turn already has an answer")
    if assistant is None:
        assistant = AIChatMessage(
            tenant_id=ctx.tenant_id,
            thread_id=thread.id,
            sequence_no=next_seq,
            role="assistant",
            status="generating",
            content="",
        )
        session.add(assistant)
    else:
        assistant.status = "generating"
        assistant.error_code = None
        assistant.content = ""
        assistant.structured_content = None
    await session.commit()  # durable BEFORE the model call (§lease lesson)

    history = await _bounded_history(session, ctx, thread, through_seq=user_row.sequence_no)
    try:
        from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis

        result = await run_sales_analysis(
            session,
            ctx.tenant_id,
            agent_id=thread.agent_id,
            question=user_row.content,
            history=history,
        )
    except Exception as exc:  # noqa: BLE001 — the row must land `failed`
        assistant.status = "failed"
        assistant.error_code = "run_failed"
        await session.commit()
        raise ConflictError("assistant turn failed; retry is available") from exc

    assistant.content = result.answer
    assistant.structured_content = build_structured_blocks(result)
    assistant.status = "completed"
    assistant.run_id = result.run_id
    assistant.analysis_id = result.saved_evidence_id or result.analysis_id
    if thread.title == "" and user_row.sequence_no == 1:
        thread.title = user_row.content[:60]
    await _maybe_compact(session, ctx, thread, through_seq=user_row.sequence_no)
    await session.commit()
    return assistant
