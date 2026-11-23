"""Facebook Page management: the field matrix, and the Graph call behind each control.

Verified against the real client (app/modules/conversations/gateway/facebook_pages.py), not taken
from the audit: posts, Reels, Stories, video, comments and insights already existed, while the Page
itself could not be edited and a post could not be pinned or hidden.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.facebook_pages import (
    EDITABLE_PAGE_FIELDS,
    PAGE_FIELD_MATRIX,
    FacebookPagesClient,
)

CREDS = {"api_key": "page-token", "account_id": "P1"}


def _record(payload: dict | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload or {"id": "P1", "success": True})

    return seen, httpx.MockTransport(handler)


def test_the_matrix_names_a_permission_for_every_editable_field():
    for name, spec in PAGE_FIELD_MATRIX.items():
        if spec.get("editable"):
            assert spec.get("write_scope"), name
            assert spec.get("exposed", True), name
        else:
            assert not spec.get("write_scope"), name


def test_what_meta_does_not_expose_is_kept_out_of_the_edit_form():
    assert "description" in EDITABLE_PAGE_FIELDS and "hours" in EDITABLE_PAGE_FIELDS
    assert "name" not in EDITABLE_PAGE_FIELDS
    assert PAGE_FIELD_MATRIX["verification_status"]["exposed"] is False
    assert PAGE_FIELD_MATRIX["rating"]["exposed"] is False


@pytest.mark.asyncio
async def test_editing_a_page_posts_exactly_the_editable_values():
    seen, transport = _record()
    async with httpx.AsyncClient(transport=transport) as http:
        await FacebookPagesClient().update_page_fields(
            CREDS, {"description": "متجر", "website": "https://fihrist.world"}, _client=http
        )
    assert seen[0].method == "POST"
    assert seen[0].url.path.endswith("/P1")
    body = seen[0].content.decode()
    assert "description=" in body and "website=" in body


@pytest.mark.asyncio
async def test_a_read_only_field_is_refused_before_meta_is_called():
    seen, transport = _record()
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ValueError) as exc:
            await FacebookPagesClient().update_page_fields(
                CREDS, {"name": "اسم جديد"}, _client=http
            )
    assert "name" in str(exc.value)
    assert seen == []


@pytest.mark.asyncio
async def test_pin_and_hide_send_the_boolean_meta_expects():
    seen, transport = _record()
    client = FacebookPagesClient()
    async with httpx.AsyncClient(transport=transport) as http:
        await client.set_post_pinned(CREDS, "P1_9", True, _client=http)
        await client.set_post_pinned(CREDS, "P1_9", False, _client=http)
        await client.set_post_hidden(CREDS, "P1_9", True, _client=http)
    bodies = [r.content.decode() for r in seen]
    assert "is_pinned=true" in bodies[0]
    assert "is_pinned=false" in bodies[1]
    assert "is_hidden=true" in bodies[2]
    assert all(r.url.path.endswith("/P1_9") for r in seen)
