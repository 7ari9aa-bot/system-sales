# Dedicated Sales Intelligence Chat ("مساعد المبيعات") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A persistent, multi-turn merchant chat with the existing `sales_intelligence` agent at `/sales-assistant` — server-persisted threads/messages, evidence-validated answers, structured render blocks — reusing `run_sales_analysis`, `AgentRunner`, the analytics metric registry, and the AI gateway unchanged.

**Architecture:** Two new tables (`ai_chat_threads`, `ai_chat_messages`) under the existing RLS conventions; a `SalesChatService` in `app/modules/ai/chat/` that owns thread/message state and turn execution; a thin `history` parameter added to `AgentRunner.run/_loop` so prior turns reach the model without touching the customer-messaging `conversation_id` path. Each turn calls the existing `run_sales_analysis` pipeline (evidence pack, findings, numeric validation) and persists the final answer with provenance (`run_id`, `analysis_id`).

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (Postgres, RLS ENABLE/FORCE + `tenant_isolation` on `app.tenant_id` GUC); Next-level React (react-router-dom, @tanstack/react-query, react-markdown ^9, recharts ^2.15); Playwright e2e (CI-only — this sandbox cannot bind ports).

**Spec:** `C:\Users\CS\.qoder\tmp\D--sales-system\attachments\219d0847-eb8a-4ef1-b383-693d50e5ce98\e3f79484-bf9b-49bb-8f10-a785838b3515.txt` (verbatim user attachment, 2026-10-10).

## Global Constraints

- **Stage 0 gate (spec §10.1):** the in-flight CI blocker fix (fe2026100804 dollar-quote collision + `test_every_executed_sql_string_parses` pglast guard) MUST be landed green on `main` before the feature branch is cut. No new migrations until CI is green on main.
- **Branch model (spec §10):** all feature work on `feature/sales-assistant-chat`; finish with a reviewable PR to `main`. No direct push of this feature to main. No production migration/deployment is performed as part of the PR.
- Alembic: single linear head; after adding `fe2026100816`, BOTH head pins in `backend/tests/test_tenancy_and_fts_schema_debt.py` (chain-shape assert AND the `alembic heads` subprocess assert) move to the new head.
- Migration authorship rules (each has already caused a CI failure once): literal table names in `op.create_table`/`op.add_column` (the AST drift guard reads only literals); `WorkspaceScopeMixin` tables declare BOTH `workspace_id` and `location_id` plus `ix_<table>_<col>` for each; RLS = ENABLE + FORCE + `DROP POLICY IF EXISTS` + `CREATE POLICY tenant_isolation ... USING/WITH CHECK` in the same migration; `sales_app` grants wrapped in a `DO $$ ... IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') ... END $$` block; one SQL statement per `op.execute` (asyncpg); any `DO` block whose body contains `$$` literals must use a different outer tag (e.g. `DO $chat$`); migration upgrade() strings are now parsed by `test_every_executed_sql_string_parses` (pglast) — keep them parseable as written.
- Money/ratios on the wire: amounts are strings (§47/ADR-001 extension), ratios numeric. Frontend parses without float coercion.
- Money-on-wire, 422 for bogus input vs 409 for state conflict, outbox event types must be registered in `app/core/events/schemas.py` AND given a tier in `core/fairness.py` `DOMAIN_PRIORITIES`.
- Ruff gate is `ruff check app tests scripts` (migrations/versions is excluded by config). Full local suite before any push: `cd backend && python -m pytest -q -rs` (expect ~2493 passed / ~1281 skipped locally; DB-backed classes skip without `DATABASE_URL_APP_ADMIN` — CI is their first real run, per the honest-RED convention).
- OpenAPI lock: regenerate after any router/schema change: `cd backend && python scripts/export_openapi_lock.py` (CI has a drift gate; `desktop/openapi.lock.json` must be committed).
- Frontend in this sandbox: `tsc --noEmit`/`npm run lint`/`npm run build`/`playwright test --list` work; binding TCP ports does NOT — e2e verdicts come only from CI's `frontend-e2e` job, and must be reported as such.
- Never trust tenant/user/agent ids from the frontend: `create_thread` resolves the SI agent server-side via `resolve_agent_by_kind(ctx.session, ctx.tenant_id, "sales_intelligence")`; `AnalyticsCtx` (`require_permission("analytics:read")`, identity/deps.py:83) supplies tenant and user.
- Thread visibility: private-to-creator by default, enforced in the service on EVERY query (RLS stays tenant-scoped); tenant owners may see all tenant threads.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/modules/ai/models.py` (modify) | `AIChatThread`, `AIChatMessage` ORM models |
| `backend/migrations/versions/fe2026100816_sales_chat.py` (create) | tables, indexes, RLS, grants |
| `backend/app/modules/ai/chat/__init__.py` (create) | package marker |
| `backend/app/modules/ai/chat/schemas.py` (create) | Pydantic request/response + render-block contracts |
| `backend/app/modules/ai/chat/service.py` (create) | thread CRUD, message append, idempotency, visibility |
| `backend/app/modules/ai/chat/turns.py` (create) | turn executor + bounded history + structured blocks |
| `backend/app/modules/ai/runtime.py` (modify) | `history: list[dict[str,str]] \| None` param on `run()`/`_loop()` |
| `backend/app/modules/ai/router.py` (modify) | `/ai/sales-chat/*` routes |
| `backend/tests/test_sales_chat_service.py` (create) | service/idempotency/blocks (no DB) |
| `backend/tests/test_sales_chat_api.py` (create) | route contract via ASGI + dependency_overrides |
| `backend/tests/test_sales_chat_rls.py` (create) | DB-backed CI-only: RLS as app role, isolation |
| `frontend/src/pages/SalesAssistant.jsx` (create) | the page |
| `frontend/src/components/salesAssistant/*.jsx` (create) | ThreadListPanel, MessageList, BlockRenderer, Composer |
| `frontend/src/App.jsx` (modify) | lazy route |
| `frontend/src/components/dashboard/Sidebar.jsx` (modify) | nav entry |
| `frontend/src/lib/i18n/ar.js`, `en.js` (modify) | `nav.salesAssistant` + chat strings |
| `e2e/sales-assistant.spec.js` (create) | Playwright e2e (CI) |

**Interfaces (stable across tasks):**

- `SalesChatService.create_thread(session, ctx, *, title: str | None = None, context: dict | None = None) -> AIChatThread`
- `SalesChatService.get_thread(session, ctx, thread_id) -> AIChatThread` (raises `NotFoundError` on foreign/cross-tenant)
- `SalesChatService.append_user_message(session, ctx, thread, *, content: str, idempotency_key: str | None) -> tuple[AIChatMessage, bool]`
- `run_chat_turn(session, ctx, thread) -> AIChatMessage` (assistant row, terminal status)
- `build_structured_blocks(result: AnalysisResult) -> list[dict]`
- `AgentRunner.run(..., history: list[dict[str, str]] | None = None)`

---

### Task 1: Models + migration fe2026100816 + RLS + head pins

**Files:**
- Modify: `backend/app/modules/ai/models.py` (append after `AIHandover`)
- Create: `backend/migrations/versions/fe2026100816_sales_chat.py`
- Modify: `backend/tests/test_tenancy_and_fts_schema_debt.py` (two head pins)
- Test: `backend/tests/test_sales_chat_rls.py` (DB-backed, CI-only), `backend/tests/test_migrations.py` (auto-covers via capture)

**Interfaces:**
- Produces: `AIChatThread`, `AIChatMessage` models; table names `ai_chat_threads`, `ai_chat_messages`; head `fe2026100816`.

- [ ] **Step 1: Write the models** (follow `AIHandover` style in the same file)

```python
class AIChatThread(TenantMixin, WorkspaceScopeMixin, Base):
    """§SI-chat — one merchant conversation with the sales_intelligence agent.

    Deliberately NOT the customer-messaging `conversations` table: this is a
    merchant-facing analysis thread, private to its creator by default.
    """

    __tablename__ = "ai_chat_threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), server_default="")
    # active | archived | deleted
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    # validated chat context: {"period": ..., "filters": {...}} — set by the UI, read by turns
    context: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # compaction: deterministic summary of turns older than summary_through_seq
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_through_seq: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_ai_chat_threads_tenant_user_updated",
            "tenant_id",
            "created_by_user_id",
            "updated_at",
        ),
        Index("ix_ai_chat_threads_workspace_id", "workspace_id"),
        Index("ix_ai_chat_threads_location_id", "location_id"),
    )


class AIChatMessage(TenantMixin, Base):
    __tablename__ = "ai_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_chat_threads.id", ondelete="CASCADE")
    )
    sequence_no: Mapped[int] = mapped_column(nullable=False)
    # user | assistant
    role: Mapped[str] = mapped_column(String(15), nullable=False)
    # pending | generating | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    content: Mapped[str] = mapped_column(Text, server_default="")
    # validated render blocks (see chat/schemas.py) — never model-authored JSON
    structured_content: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # opaque ref to the saved analysis/evidence row (analytics. analyses) when one exists
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(63), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "thread_id", "sequence_no", name="uq_ai_chat_messages_thread_seq"),
        Index(
            "uq_ai_chat_messages_thread_key",
            "tenant_id",
            "thread_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_ai_chat_messages_thread_seq", "thread_id", "sequence_no"),
    )
```

Verify the actual mixin/column imports already at the top of `models.py` (`TenantMixin`, `WorkspaceScopeMixin`, `JSONB`, `UUID` import form) and match them exactly — do not introduce new import aliases. NOTE: the drift guard reads literal table names from `op.create_table` in the MIGRATION, and `tests/test_migrations.py` compares model columns vs migration columns — every column above must appear in the migration.

- [ ] **Step 2: Write the migration** `fe2026100816_sales_chat.py` (down_revision `fe2026100815`), one statement per `op.execute`, literal table names, guarded grants:

```python
def upgrade() -> None:
    op.create_table(
        "ai_chat_threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), server_default="", nullable=False),
        sa.Column("status", sa.String(15), server_default="active", nullable=False),
        sa.Column("context", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("summary_through_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_chat_threads_tenant_user_updated", "ai_chat_threads", ["tenant_id", "created_by_user_id", "updated_at"])
    op.create_index("ix_ai_chat_threads_workspace_id", "ai_chat_threads", ["workspace_id"])
    op.create_index("ix_ai_chat_threads_location_id", "ai_chat_threads", ["location_id"])
    # (same shape for ai_chat_messages: id, tenant_id FK CASCADE, thread_id FK
    #  ai_chat_threads.id CASCADE, sequence_no Integer NOT NULL, role/status
    #  String(15), content Text server_default "", structured_content JSONB
    #  nullable, run_id FK agent_runs.id SET NULL, analysis_id Uuid nullable,
    #  idempotency_key String(64) nullable, error_code String(63) nullable,
    #  created_at; uq_ai_chat_messages_thread_seq UNIQUE; partial unique
    #  uq_ai_chat_messages_thread_key WHERE idempotency_key IS NOT NULL;
    #  ix_ai_chat_messages_thread_seq)
    # RLS for BOTH tables: ENABLE, FORCE, DROP POLICY IF EXISTS, CREATE POLICY
    # tenant_isolation USING/WITH CHECK (tenant_id = _TENANT_GUARD) — copy the
    # exact guard expression pattern from fe2026100813_ai_order_quotes.py.
    # Grants DO-block (sales_app) for BOTH tables — copy from fe2026100813.
```

The FK-listing order inside `op.create_table` is irrelevant to Postgres but the file must satisfy `tests/test_migrations.py`'s model-vs-migration column diff — write every column.

- [ ] **Step 3: Move both head pins** in `backend/tests/test_tenancy_and_fts_schema_debt.py` from `fe2026100815` to `fe2026100816` (chain-shape `tail == {...}` assert AND `lines[0].startswith(...)` in the subprocess test). Also confirm `alembic heads` reports exactly one head.

- [ ] **Step 4: Write the RED tests** in `backend/tests/test_sales_chat_rls.py`:

```python
import pytest

pytestmark = [pytest.mark.usefixtures("db")]


async def test_thread_policy_hides_other_tenant_rows_as_app_role(db):
    """CI-only: insert as tenant A via owner session, bind app GUCs for tenant
    B's app role context, assert SELECT returns nothing — and vice versa.
    Follow the tenant_ctx fixture pattern in tests/conftest.py (real Tenant row,
    bind_tenant kwargs), NOT a synthetic uuid4 (the FK lesson)."""
```

Two DB-backed tests minimum: (1) cross-tenant thread invisible as app role; (2) app role can INSERT/SELECT its own thread and message (proves grants exist — the `provision.py` prints-owner-counts lesson). These skip locally; their RED is a CI failure per the honest-RED convention.

- [ ] **Step 5: Run the local gates**

```bash
cd backend && python -m pytest tests/test_migrations.py tests/test_tenancy_and_fts_schema_debt.py -q
cd backend && python -m ruff check app tests scripts
```

Expected: migration tests PASS (including `test_every_executed_sql_string_parses` — it now parses the new migration's SQL), schema-debt tests PASS with the moved pins.

- [ ] **Step 6: Commit** `git add ... && git commit -m "feat(ai): sales chat persistence — threads, messages, RLS (fe2026100816)"`

### Task 2: Chat schemas + service (threads, messages, idempotency)

**Files:**
- Create: `backend/app/modules/ai/chat/__init__.py`, `chat/schemas.py`, `chat/service.py`
- Test: `backend/tests/test_sales_chat_service.py`

**Interfaces:**
- Consumes: `AIChatThread`/`AIChatMessage` (Task 1), `TenantContext` (identity/deps.py), repo errors (`NotFoundError`, `ConflictError`, `ValidationError` from `app/core/errors`).
- Produces: the service functions listed under **Interfaces** above; `TITLE_MAX=200`, `MESSAGE_MAX=4000`, `PAGE_LIMIT_MAX=100`, `IDEMPOTENCY_KEY_MAX=64`.

- [ ] **Step 1: schemas.py** — Pydantic contracts (the wire format for Task 4's routes and the frontend):

```python
class ThreadContextIn(BaseModel):
    period: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)

class ThreadCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: ThreadContextIn | None = None

class ThreadUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None

class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    status: str
    context: dict
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None

# Render blocks — a closed vocabulary; the renderer rejects unknown types.
class TextBlock(BaseModel):    type: Literal["text"];        body: str
class KpiBlock(BaseModel):     type: Literal["kpi"];         metric: str; label: str; value: str; unit: str; window: str
class FindingsBlock(BaseModel):type: Literal["findings"];    items: list[FindingOut]
class NoticeBlock(BaseModel):  type: Literal["notice"];      severity: Literal["info","warning"]; message: str
class RefsBlock(BaseModel):    type: Literal["refs"];        analysis_id: uuid.UUID | None; run_id: uuid.UUID | None
Blocks = Annotated[TextBlock | KpiBlock | FindingsBlock | NoticeBlock | RefsBlock, Field(discriminator="type")]

class MessageOut(BaseModel):
    id: uuid.UUID; thread_id: uuid.UUID; sequence_no: int; role: str; status: str
    content: str; structured_content: list[Blocks] | None
    run_id: uuid.UUID | None; analysis_id: uuid.UUID | None
    error_code: str | None; created_at: datetime

class MessageSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = Field(default=None, max_length=64)
```

`FindingOut` already exists in `app/modules/ai/schemas.py` — import it, do not duplicate.

- [ ] **Step 2: Write RED service tests** (`test_sales_chat_service.py`, no DB — fake session doubles following the `_FakeResult` pattern; DB truth is CI's job):

Idempotent re-submit returns `(same_row, False)`; new key creates `(new_row, True)` with `sequence_no = max+1`. `get_thread` raises `NotFoundError` for a foreign user's thread. `list_threads` filters `status != "deleted"` and `created_by_user_id == ctx.user.id` unless tenant owner. Rename validates non-empty title; archive/restore are legal status transitions; archive→archive raises `ConflictError`. Message pagination caps limit at 100.

- [ ] **Step 3: Implement service.py** — key logic:

```python
HISTORY = None  # (turns live in Task 3)

async def append_user_message(session, ctx, thread, *, content, idempotency_key):
    if idempotency_key:
        existing = (await session.execute(
            select(AIChatMessage).where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.idempotency_key == idempotency_key,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return existing, False
    next_seq = (await session.execute(
        select(func.coalesce(func.max(AIChatMessage.sequence_no), 0)).where(
            AIChatMessage.tenant_id == ctx.tenant_id, AIChatMessage.thread_id == thread.id)
    )).scalar_one() + 1
    row = AIChatMessage(tenant_id=ctx.tenant_id, thread_id=thread.id, sequence_no=next_seq,
                        role="user", status="completed", content=content,
                        idempotency_key=idempotency_key)
    session.add(row)
    thread.last_message_at = func.now()
    return row, True
```

Visibility: every read filters `AIChatThread.created_by_user_id == ctx.user.id` OR tenant-owner check (`await _is_tenant_owner(session, ctx)` — reuse the same role/permission query pattern the hierarchy work uses; if none exists, filter strictly by creator). `delete_thread` sets `status="deleted"` (soft — audit) and always raises `NotFoundError` afterward.

- [ ] **Step 4: Run service tests → green. Commit** `feat(ai): sales chat service — thread CRUD, message append, idempotency`.

### Task 3: Turn executor + runtime history injection

**Files:**
- Modify: `backend/app/modules/ai/runtime.py` (run/_loop signatures + message assembly)
- Create: `backend/app/modules/ai/chat/turns.py`
- Test: `backend/tests/test_sales_chat_service.py` (extend), `backend/tests/test_ai_runtime_history.py` (create)

**Interfaces:**
- Consumes: `run_sales_analysis(session, tenant_id, *, agent_id, question, runner=None) -> AnalysisResult` (agent.py:287 — unchanged), `build_structured_blocks`, Task 2 service.
- Produces: `run_chat_turn(session, ctx, thread) -> AIChatMessage`; `AgentRunner.run(..., history=...)`.

- [ ] **Step 1: RED runtime test** (`test_ai_runtime_history.py`, no DB beyond the existing fake pattern in `test_wiring.py`): a fake gateway records the `messages` it receives; `runner.run(..., history=[{"role":"user","content":"قارن مبيعات الشهر ده باللي فات."},{"role":"assistant","content":"..."}], user_message="طب إيه سبب الانخفاض؟")` shows history turns BETWEEN the system message and the current user message, and NO `conversation_id` lookup occurs. Run → fails (no `history` param).

- [ ] **Step 2: Implement** — in `run()` add keyword `history: list[dict[str, str]] | None = None`, thread through `_loop(...)`; in `_loop` after the knowledge_context append:

```python
        if history:
            # SI chat: bounded prior turns, server-built from ai_chat_messages.
            # Narrative context only — never numeric authority; facts are
            # re-queried per turn by the deterministic tools.
            messages.extend(history)
```

- [ ] **Step 3: turns.py** — the executor:

```python
HISTORY_MESSAGE_LIMIT = 12  # 6 turns max reach the prompt

async def run_chat_turn(session, ctx, thread) -> AIChatMessage:
    user_rows = (await session.execute(
        select(AIChatMessage)
        .where(AIChatMessage.tenant_id == ctx.tenant_id, AIChatMessage.thread_id == thread.id,
               AIChatMessage.role == "user")
        .order_by(AIChatMessage.sequence_no.desc()).limit(1)
        .with_for_update(of=AIChatMessage)   # serialize concurrent submits per thread
    )).scalars().all()
    user_row = user_rows[0]
    next_seq = user_row.sequence_no + 1
    assistant = AIChatMessage(tenant_id=ctx.tenant_id, thread_id=thread.id, sequence_no=next_seq,
                              role="assistant", status="generating", content="")
    session.add(assistant)
    await session.commit()               # durable BEFORE the model call (§lease lesson)

    history = await _bounded_history(session, ctx, thread, through_seq=user_row.sequence_no)
    try:
        from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
        result = await run_sales_analysis(session, ctx.tenant_id, agent_id=thread.agent_id,
                                          question=user_row.content)
    except Exception:
        assistant.status, assistant.error_code = "failed", "run_failed"
        await session.commit()
        raise ConflictError("assistant turn failed; retry is available")

    assistant.content = result.answer
    assistant.structured_content = build_structured_blocks(result)
    assistant.status = "completed"
    assistant.run_id = result.run_id
    assistant.analysis_id = result.saved_evidence_id
    if thread.title == "" and user_row.sequence_no == 1:
        thread.title = user_row.content[:60]
    await _maybe_compact(session, ctx, thread, through_seq=user_row.sequence_no)
    await session.commit()
    return assistant
```

`_bounded_history` returns `[{"role": m.role, "content": m.content} for m in prior messages]` capped at `HISTORY_MESSAGE_LIMIT`; when `thread.summary_through_seq > 0`, prepend a single `{"role": "system", "content": f"[Prior conversation summary]\n{thread.context_summary}"}` marker instead of the pre-summary turns. `_maybe_compact` (deterministic, NO model call): when `user_row.sequence_no - thread.summary_through_seq > 12`, rebuild `context_summary` from the stored assistant rows' structured blocks in that range — one line per turn: metric names + window + outcome (never model text), set `summary_through_seq`.

`build_structured_blocks(result) -> list[dict]` (turns.py, model_dump()-able by MessageOut):

```python
def build_structured_blocks(result):
    blocks: list[dict] = []
    if result.answer:
        blocks.append({"type": "text", "body": result.answer})
    for f in result.facts[:8]:
        blocks.append({"type": "kpi", "metric": f.get("metric", ""),
                       "label": f.get("metric", "").replace("_", " "),
                       "value": str(f.get("value", "")),          # money stays a string
                       "unit": str(f.get("unit", "")),
                       "window": str(f.get("window", ""))})
    if result.findings:
        blocks.append({"type": "findings", "items": [
            {"statement": f.statement, "type": f.type,
             "relationship": f.relationship.value, "confidence": f.confidence,
             "confidence_reasons": f.confidence_reasons,
             "evidence_refs": f.evidence_refs} for f in result.findings[:6]]})
    if result.data_quality.status.value != "complete":
        blocks.append({"type": "notice", "severity": "warning",
                       "message": f"data quality: {result.data_quality.status.value}"})
    if result.guardrail_reason:
        blocks.append({"type": "notice", "severity": "warning",
                       "message": f"safe response: {result.guardrail_reason}"})
    if result.saved_evidence_id or result.run_id:
        blocks.append({"type": "refs", "analysis_id": str(result.saved_evidence_id) if result.saved_evidence_id else None,
                       "run_id": str(result.run_id) if result.run_id else None})
    return blocks
```

- [ ] **Step 4: Turn tests** (extend `test_sales_chat_service.py` with a fake `run_sales_analysis` monkeypatch): user message persisted + assistant terminal status (never left `generating` — assert the exception path also lands `failed`); history passed to the runner contains prior turns and the summary marker after compaction; `structured_content` validates against `MessageOut`; retry overwrites a failed assistant row (Task 4 route calls `run_chat_turn` again after clearing the failed row's `status` — retry only allowed when the last assistant row for that user message has `status="failed"`, else `ConflictError`).

- [ ] **Step 5: Gates + commit** `feat(ai): multi-turn SI chat — bounded history, validated turn executor`.

### Task 4: Router `/ai/sales-chat/*` + OpenAPI lock

**Files:**
- Modify: `backend/app/modules/ai/router.py`
- Test: `backend/tests/test_sales_chat_api.py`
- Regenerate: `desktop/openapi.lock.json`

- [ ] **Step 1: RED API tests** — real ASGI stack with `dependency_overrides[get_tenant_ctx]` (the `_IncludedRouter` lesson: walking `app.routes` finds nothing — prove through the client). Cover: 201 create (client-supplied `agent_id` is IGNORED — server resolves SI kind), list pagination + search, foreign-user thread → 404, cross-tenant thread → 404, send message happy path returns assistant `MessageOut` (runner faked), duplicate `idempotency_key` returns the SAME message id, 422 on >4000 content, PATCH archive→restore, DELETE → subsequent GET 404, retry on failed allowed / on completed 409.

- [ ] **Step 2: Implement routes** (all take `AnalyticsCtx`):

```
POST   /ai/sales-chat/threads                                   → 201 ThreadOut
GET    /ai/sales-chat/threads?include_archived=&search=&limit=&before= → list[ThreadOut]
GET    /ai/sales-chat/threads/{thread_id}                        → ThreadOut
PATCH  /ai/sales-chat/threads/{thread_id}                        → ThreadOut
DELETE /ai/sales-chat/threads/{thread_id}                        → 204
GET    /ai/sales-chat/threads/{thread_id}/messages?limit=&before_seq= → list[MessageOut]
POST   /ai/sales-chat/threads/{thread_id}/messages               → MessageOut (synchronous final turn)
POST   /ai/sales-chat/threads/{thread_id}/messages/{message_id}/retry → MessageOut
```

The POST-messages handler: load thread via service (ownership enforced), `append_user_message`, commit; then `run_chat_turn`; return the assistant row. Duplicate `idempotency_key` (created=False) → return that user message's existing assistant reply by looking up `sequence_no = user.sequence_no + 1` — no second run (the "no duplicate billing" requirement). No SSE/streaming in v1: the execution path is not stream-capable; the frontend gets honest progress states (spec §2 explicitly allows this). Do NOT emit raw exceptions (repo error handlers already map DomainError family).

- [ ] **Step 3: Regenerate the lock** `cd backend && python scripts/export_openapi_lock.py` and commit it with the routes.

- [ ] **Step 4: Gates + commit** `feat(ai): sales chat API — threads, messages, retry under analytics:read`.

### Task 5: Frontend — `/sales-assistant` page, nav, i18n

**Files:**
- Create: `frontend/src/pages/SalesAssistant.jsx`, `frontend/src/components/salesAssistant/ThreadListPanel.jsx`, `MessageList.jsx`, `BlockRenderer.jsx`, `Composer.jsx`
- Modify: `frontend/src/App.jsx`, `frontend/src/components/dashboard/Sidebar.jsx`, `frontend/src/lib/i18n/ar.js`, `frontend/src/lib/i18n/en.js`
- Constraint: the user's in-flight dashboard re-theme owns `frontend/src/components/sales/`, `AddProduct.jsx`, `ui.jsx`, `index.css` — do NOT edit those; consume shared components as they exist at execution time.

- [ ] **Step 1: Route + nav + i18n.** In `App.jsx` mirror the `AI` route's exact wrapper (lazy import + `ProtectedRoute` + dashboard layout). In `Sidebar.jsx` insert between `/ai` and `/analytics`:

```jsx
{ to: "/sales-assistant", label: t("nav.salesAssistant"), icon: MessageSquareText },
```

i18n (ar): `"salesAssistant": "مساعد المبيعات"` + strings for newChat/newThread/send/retry/copy/archive/rename/delete/thinking/empty-state examples ("قارن مبيعات الشهر ده باللي فات.", "أفضل المنتجات المبيع الشهر ده؟", "إيه أداء القنوات؟", "المرتجعات عملت إيه؟", "أداء الشحن والفروع", "المنتجات اللي مخزونها هيخلص") / (en) equivalents.

- [ ] **Step 2: Data layer** (react-query; precise keys — the prefix-invalidation crash lesson):

```js
const useThreads = (params) => useQuery({ queryKey: ["sales-chat", "threads", params ?? {}], queryFn: () => api("/ai/sales-chat/threads", { query: params }) });
const useThread = (id) => useQuery({ queryKey: ["sales-chat", "thread", id], enabled: !!id, queryFn: () => api(`/ai/sales-chat/threads/${id}`) });
const useMessages = (id) => useQuery({ queryKey: ["sales-chat", "thread", id, "messages"], enabled: !!id, queryFn: () => api(`/ai/sales-chat/threads/${id}/messages?limit=100`) });
const sendTurn = useMutation(...) // POST messages; on success invalidate EXACTLY ["sales-chat","thread",id,"messages"] and the threads list key
```

- [ ] **Step 3: Page + components.** Layout: right panel (RTL-aware) = thread list with search input, "new chat" button, per-thread menu (rename inline / archive / delete with confirm); main area = `MessageList` (user right, assistant left, react-markdown for `text` blocks, `BlockRenderer` for kpi/findings/notice/refs; money values rendered as strings, `Intl.NumberFormat` only for display grouping — never `parseFloat` into math), assistant turns show `thinking` state while the send mutation runs (honest progress — no fake token streaming), failed turns show retry button + safe error code, copy button per assistant message; `Composer` textarea pinned bottom: Enter sends, Shift+Enter newline, disabled while pending, draft preserved across thread switches (component-level `useState` keyed by thread id); empty thread shows the six example questions as buttons that prefill and send. Mobile: thread panel collapses into a drawer. Follow the dashboard's existing design tokens/classes (inspect `ui.jsx` exports at execution time and reuse its card/button/input primitives).

- [ ] **Step 4: Local checks** (this sandbox's ceiling — say so in the report):

```bash
cd frontend && npx tsc --noEmit; npm run lint; npm run build; npx playwright test --list
```

- [ ] **Step 5: Commit** `feat(frontend): dedicated sales-assistant chat page (/sales-assistant)`.

### Task 6: E2E spec + full gates + PR

**Files:**
- Create: `e2e/sales-assistant.spec.js`

- [ ] **Step 1: Playwright spec** (auth via the existing e2e helpers; assertions per memory: `getByText(..., { exact: true })` for Radix toasts): create thread → send example question → assistant bubble renders (backend faked in e2e via `page.route` mocking `/api/v1/ai/sales-chat/*` so the spec tests UI, not the model) → switch thread → reload → history still renders → rename/archive/delete visible → AR and EN pass (`?lang=` / i18n toggle) → `/ai`, `/analytics`, `/inbox` unaffected.

- [ ] **Step 2: Full backend gate** before any push: `cd backend && python -m pytest -q -rs` (green, 0 failed) + `ruff check app tests scripts` + `alembic heads` single head.

- [ ] **Step 3: Push branch + open PR** (`gh pr create --base main`): body lists files changed, migrations added (fe2026100816), routes, new/extended capabilities, tests actually executed with exact results, unsupported metrics (profit/margin/CLV/ROAS stay typed-unsupported — no invented values), and explicit confirmation that NO production migration/deployment was performed. CI verdicts (including `frontend-e2e`, which cannot run in this sandbox) are reported from the run, not assumed.

- [ ] **Step 4: Watch CI properly** (capture `gh run watch`'s own exit code; re-query `--json conclusion` and per-job conclusions; DB tests + e2e get their first real run here — iterate on honest REDs).

---

## Self-Review Notes

- Spec §3 tables/fields → Task 1 (all listed fields present; `status` vocabulary per spec; compaction fields = `context_summary`/`summary_through_seq`).
- Spec §4 routes → Task 4 (SSE omitted with justification — spec permits honest progress states; retry endpoint included).
- Spec §5 multi-turn → Task 3 (bounded history + deterministic compaction; prior model text never numeric authority — pipeline re-queries per turn; customer `conversation_id`/memory paths untouched: `run()` is called without `conversation_id`, `knowledge_context` unset).
- Spec §6 tools → no tool changes needed: the nine SI tools already cover revenue/orders/AOV/refunds/products/channels/customers/fulfillment via `si_*`; insufficient-data paths already return typed safe responses (`Outcome.INSUFFICIENT_DATA`). `si_data_status` tenant-scoping is inherited from ctx-scoped session queries; verified in Task 4 API tests indirectly. Profit/margin/CLV/ROAS: no trusted source → never surfaced (existing registry behavior).
- Spec §7 evidence contract → Task 3 blocks from `AnalysisResult` (already validated via `validate_answer` in `run_sales_analysis` — invalid answers are replaced by safe responses BEFORE persistence).
- Spec §8 usage/audit → reuses `agent_runs`/gateway ledger via `run_sales_analysis`; idempotency prevents duplicate runs; failed turns land terminal statuses (timeout surfaces as `run_failed` with retry).
- Spec §9 tests → Tasks 1–4 (backend), Task 6 (e2e; CI-only verdicts), RLS as app role (Task 1 Step 4).
