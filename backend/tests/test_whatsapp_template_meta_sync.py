"""A WhatsApp template is reviewed by Meta, so its status may only come from Meta.

These pin the rules that stop an owner (or a stray webhook) from making a template sendable that
Meta never approved, and the ones that keep a refused submit from leaving a phantom "submitted".
No database: a tiny in-memory session stands in, since the service only uses get/add/flush.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ConflictError, ExternalProviderError
from app.modules.conversations.models import MessageTemplate, TemplateApproval
from app.modules.conversations.templates import TemplateInput, TemplateService

TENANT = uuid.uuid4()
CREDS = {"access_token": "tok", "waba_id": "555"}


class _Result:
    def __init__(self, row, rows=None):
        self._row = row
        self._rows = rows if rows is not None else ([row] if row is not None else [])

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeSession:
    """Holds MessageTemplate rows; `execute` answers the one lookup the service makes."""

    def __init__(self):
        self.templates: dict[uuid.UUID, MessageTemplate] = {}
        self.approvals: list[TemplateApproval] = []

    def add(self, obj):
        if isinstance(obj, MessageTemplate):
            obj.id = obj.id or uuid.uuid4()
            self.templates[obj.id] = obj
        elif isinstance(obj, TemplateApproval):
            self.approvals.append(obj)

    async def flush(self):
        return None

    async def execute(self, stmt):
        # TemplateService.get / create both filter by tenant + id or name; pick the right row.
        params = stmt.compile().params
        if "LIMIT" in str(stmt).upper() and "ORDER BY" in str(stmt).upper():
            # list_templates: every row of the tenant, narrowed by provider when asked.
            provider = next((v for v in params.values() if v in ("whatsapp", "messenger")), None)
            rows = [t for t in self.templates.values() if provider in (None, t.provider)]
            return _Result(None, rows)
        wanted_id = next(
            (v for v in params.values() if isinstance(v, uuid.UUID) and v != TENANT), None
        )
        if wanted_id is not None:
            return _Result(self.templates.get(wanted_id))
        name = next((v for v in params.values() if isinstance(v, str) and v in self._names()), None)
        return _Result(next((t for t in self.templates.values() if t.name == name), None))

    def _names(self):
        return {t.name for t in self.templates.values()}


@pytest.fixture(autouse=True)
def _breaker():
    reset_breakers()
    yield
    reset_breakers()


def _input(**kw) -> TemplateInput:
    base = dict(name="order_ready", body_text="طلبك جاهز يا عميلنا", category="utility")
    base.update(kw)
    return TemplateInput(**base)


def _mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _draft(session, **kw) -> MessageTemplate:
    return await TemplateService.create(session, TENANT, _input(**kw))


# ------------------------------------------------------------------ creating


async def test_a_whatsapp_template_with_a_category_keeps_what_meta_needs():
    s = FakeSession()
    t = await _draft(s, footer="شكرا", buttons=({"type": "QUICK_REPLY", "text": "تمام"},))
    assert t.status == "draft" and t.category == "UTILITY"
    assert [c["type"] for c in t.components] == ["BODY", "FOOTER", "BUTTONS"]
    assert TemplateService.is_meta_managed(t)


async def test_a_template_without_a_category_stays_local():
    s = FakeSession()
    t = await TemplateService.create(s, TENANT, TemplateInput(name="local_one", body_text="hi"))
    assert t.category is None and t.components == []
    assert not TemplateService.is_meta_managed(t)


async def test_meta_rules_are_checked_when_saving_not_after_a_round_trip():
    from app.core.errors import ValidationError

    s = FakeSession()
    with pytest.raises(ValidationError):
        await _draft(s, name="Has Capitals")
    with pytest.raises(ValidationError, match="example"):
        await _draft(s, name="with_var", body_text="رقم {{1}} جاهز")


# ------------------------------------------------------------------ submitting


async def test_submit_creates_it_on_meta_and_records_the_id():
    s = FakeSession()
    t = await _draft(s)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"id": "777", "status": "PENDING", "category": "UTILITY"})

    out = await TemplateService.submit(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert out.status == "submitted" and out.provider_template_id == "777"
    assert seen["url"].endswith("/555/message_templates")
    assert [a.status for a in s.approvals] == ["submitted"]


async def test_a_refused_submit_leaves_a_draft_never_a_phantom_submitted():
    s = FakeSession()
    t = await _draft(s)

    def handler(req):
        return httpx.Response(400, json={"error": {"message": "Template name already exists"}})

    with pytest.raises(ExternalProviderError, match="already exists"):
        await TemplateService.submit(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert t.status == "draft" and t.provider_template_id is None
    assert s.approvals == []


async def test_submit_without_a_connected_whatsapp_is_a_clear_conflict():
    s = FakeSession()
    t = await _draft(s)
    with pytest.raises(ConflictError, match="not connected"):
        await TemplateService.submit(s, TENANT, t.id, credentials=None)
    assert t.status == "draft"


async def test_meta_may_answer_approved_at_once_and_we_follow_it():
    s = FakeSession()
    t = await _draft(s)

    def handler(req):
        return httpx.Response(200, json={"id": "1", "status": "APPROVED"})

    out = await TemplateService.submit(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert out.status == "approved"
    assert [a.status for a in s.approvals] == ["submitted", "approved"]  # the trail stays whole


async def test_a_local_template_submits_without_meta():
    s = FakeSession()
    t = await TemplateService.create(s, TENANT, TemplateInput(name="local_one", body_text="hi"))
    out = await TemplateService.submit(s, TENANT, t.id)  # no credentials, no client
    assert out.status == "submitted"


# ------------------------------------------------- nobody approves by hand


async def test_a_meta_template_cannot_be_approved_or_rejected_by_hand():
    s = FakeSession()
    t = await _draft(s)
    t.status = "submitted"
    with pytest.raises(ConflictError, match="by Meta"):
        await TemplateService.approve(s, TENANT, t.id, reviewer="staff")
    with pytest.raises(ConflictError, match="by Meta"):
        await TemplateService.reject(s, TENANT, t.id, reason="nope", reviewer="staff")
    assert t.status == "submitted"


async def test_a_local_template_can_still_be_approved_by_hand():
    s = FakeSession()
    t = await TemplateService.create(s, TENANT, TemplateInput(name="local_one", body_text="hi"))
    await TemplateService.submit(s, TENANT, t.id)
    out = await TemplateService.approve(s, TENANT, t.id, reviewer="staff")
    assert out.status == "approved"


# ------------------------------------------------- what Meta reports back


async def test_meta_approval_makes_it_sendable():
    s = FakeSession()
    t = await _draft(s)
    t.status = "submitted"
    out = await TemplateService.apply_provider_status(s, TENANT, t.id, "approved")
    assert out.status == "approved"


async def test_meta_rejection_keeps_its_reason_for_the_owner():
    s = FakeSession()
    t = await _draft(s)
    t.status = "submitted"
    out = await TemplateService.apply_provider_status(
        s, TENANT, t.id, "rejected", reason="  INVALID_FORMAT: variable at the end  "
    )
    assert out.status == "rejected"
    assert out.rejection_reason == "INVALID_FORMAT: variable at the end"
    assert s.approvals[-1].rejection_reason == "INVALID_FORMAT: variable at the end"


async def test_the_same_status_twice_is_a_noop():
    s = FakeSession()
    t = await _draft(s)
    t.status = "submitted"
    await TemplateService.apply_provider_status(s, TENANT, t.id, "approved")
    n = len(s.approvals)
    await TemplateService.apply_provider_status(s, TENANT, t.id, "approved")
    assert len(s.approvals) == n


async def test_a_late_pending_never_demotes_an_approved_template():
    s = FakeSession()
    t = await _draft(s)
    t.status = "approved"
    out = await TemplateService.apply_provider_status(s, TENANT, t.id, "submitted")
    assert out.status == "approved"


async def test_an_archived_template_stays_archived_whatever_meta_says():
    s = FakeSession()
    t = await _draft(s)
    t.status = "archived"
    out = await TemplateService.apply_provider_status(s, TENANT, t.id, "approved")
    assert out.status == "archived"


async def test_meta_pausing_an_approved_template_stops_it_being_sent():
    s = FakeSession()
    t = await _draft(s)
    t.status = "approved"
    out = await TemplateService.apply_provider_status(s, TENANT, t.id, "paused")
    assert out.status == "paused"


async def test_editing_after_a_rejection_clears_the_old_reason():
    s = FakeSession()
    t = await _draft(s)
    t.status = "rejected"
    t.rejection_reason = "old"
    out = await TemplateService.update(s, TENANT, t.id, _input(body_text="نص جديد ومعدل"))
    assert out.rejection_reason is None


# ------------------------------------------------------------------ pull sync


def _listing(*rows) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": list(rows)})

    return _mock(handler)


async def test_sync_turns_submitted_into_approved_by_meta_id():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "submitted", "777"
    out = await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {"id": "777", "name": "order_ready", "language": "ar", "status": "APPROVED"}
        ),
    )
    assert t.status == "approved"
    assert out == {"checked": 1, "changed": ["order_ready"], "missing_on_meta": []}


async def test_sync_brings_meta_s_rejection_reason_back():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "submitted", "777"
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {
                "id": "777",
                "name": "order_ready",
                "language": "ar",
                "status": "REJECTED",
                "rejected_reason": "INCORRECT_CATEGORY",
            }
        ),
    )
    assert t.status == "rejected" and t.rejection_reason == "INCORRECT_CATEGORY"


async def test_meta_saying_no_reason_is_not_stored_as_a_reason():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "submitted", "777"
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {
                "id": "777",
                "name": "order_ready",
                "language": "ar",
                "status": "REJECTED",
                "rejected_reason": "NONE",
            }
        ),
    )
    assert t.rejection_reason is None


async def test_sync_pauses_a_template_meta_paused_so_it_stops_being_sent():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "approved", "777"
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {"id": "777", "name": "order_ready", "language": "ar", "status": "PAUSED"}
        ),
    )
    assert t.status == "paused"


async def test_sync_never_creates_a_template_the_owner_did_not_write():
    s = FakeSession()
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {"id": "9", "name": "someone_elses", "language": "ar", "status": "APPROVED"}
        ),
    )
    assert s.templates == {}


async def test_sync_ignores_a_status_it_does_not_know():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "submitted", "777"
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {"id": "777", "name": "order_ready", "language": "ar", "status": "WEIRD_NEW"}
        ),
    )
    assert t.status == "submitted"


async def test_sync_reports_a_sent_template_that_vanished_from_meta():
    s = FakeSession()
    t = await _draft(s)
    t.status, t.provider_template_id = "approved", "777"
    out = await TemplateService.sync_from_meta(s, TENANT, credentials=CREDS, _client=_listing())
    assert out["missing_on_meta"] == ["order_ready"]
    assert t.status == "approved"  # reported, not silently changed


async def test_sync_does_not_flag_a_draft_as_missing():
    s = FakeSession()
    await _draft(s)
    out = await TemplateService.sync_from_meta(s, TENANT, credentials=CREDS, _client=_listing())
    assert out["missing_on_meta"] == []


async def test_sync_finds_an_older_template_by_name_and_keeps_its_id():
    s = FakeSession()
    t = await _draft(s)
    t.status = "submitted"  # sent before we kept Meta's id
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing(
            {"id": "42", "name": "order_ready", "language": "ar", "status": "APPROVED"}
        ),
    )
    assert t.provider_template_id == "42" and t.status == "approved"


async def test_sync_leaves_local_templates_alone():
    s = FakeSession()
    t = await TemplateService.create(s, TENANT, TemplateInput(name="local_one", body_text="hi"))
    # "submitted" -> "approved" IS a legal hop, so a sync that wrongly touched this template
    # would really move it (an approved -> rejected hop is refused anyway and proves nothing).
    t.status = "submitted"
    await TemplateService.sync_from_meta(
        s,
        TENANT,
        credentials=CREDS,
        _client=_listing({"id": "1", "name": "local_one", "language": "ar", "status": "APPROVED"}),
    )
    assert t.status == "submitted"


# ------------------------------------------------------------------- removing


async def test_removing_a_sent_template_deletes_it_on_meta_first():
    s = FakeSession()
    t = await _draft(s)
    t.status = "rejected"
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.params.get("name")))
        return httpx.Response(200, json={"success": True})

    out = await TemplateService.remove(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert out.status == "archived" and calls == [("DELETE", "order_ready")]


async def test_a_refused_delete_on_meta_keeps_the_template():
    s = FakeSession()
    t = await _draft(s)
    t.status = "approved"

    def handler(req):
        return httpx.Response(400, json={"error": {"message": "in use"}})

    with pytest.raises(ExternalProviderError):
        await TemplateService.remove(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert t.status == "approved"


async def test_a_draft_is_archived_without_calling_meta():
    s = FakeSession()
    t = await _draft(s)

    def handler(req):
        raise AssertionError("a draft was never on Meta")

    out = await TemplateService.remove(s, TENANT, t.id, credentials=CREDS, _client=_mock(handler))
    assert out.status == "archived"


async def test_a_template_meta_paused_cannot_be_resumed_by_hand():
    s = FakeSession()
    t = await _draft(s)
    t.status = "paused"
    with pytest.raises(ConflictError, match="by Meta"):
        await TemplateService.resume(s, TENANT, t.id)
    assert t.status == "paused"


async def test_a_local_template_can_still_be_resumed():
    s = FakeSession()
    t = await TemplateService.create(s, TENANT, TemplateInput(name="local_one", body_text="hi"))
    t.status = "paused"
    assert (await TemplateService.resume(s, TENANT, t.id)).status == "approved"
