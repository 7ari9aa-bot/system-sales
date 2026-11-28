"""One Meta Page callback, two capabilities: ``/webhooks/meta/page``.

Meta gives an app ONE callback URL per object type. A Facebook Page is a single ``page`` object
whose delivery mixes two kinds of news in one signed POST:

* ``entry[].messaging[]`` — private chat. This is the **messenger** channel.
* ``entry[].changes[]`` — the Page's own news (``feed`` posts/comments, ``mention``). This is the
  **facebook** channel.

The platform keeps both channel records for that one Page. Before this router, the callback had to
be registered under ONE channel's URL, so the other kind of event was lost (or filed under the
wrong channel). These tests pin the split itself (``route_page_payload``), the two refusals
(signature, verify token) and — through the REAL app, the way
``tests/test_webhook_ingress_routing.py`` does it — that ``POST /api/v1/webhooks/meta/page`` hands
each capability to ``_ingest_one`` and never lets one capability's events reach the other's parser.

No provider traffic: the signature secret and verify token are patched into the settings the
gateway module reads, and ``_ingest_one`` / the DB session are replaced, so nothing here needs
PostgreSQL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.applications.apparel.modules.conversations.gateway import meta_page_events
from app.applications.apparel.modules.conversations.gateway.meta_page_events import (
    FACEBOOK,
    MESSENGER,
    check_page_signature,
    classify_entry,
    event_kinds,
    route_page_payload,
    verify_page_request,
)
from app.applications.apparel.modules.conversations.routers import webhooks as webhook_routes

PAGE_SECRET = "page-app-secret"
VERIFY_TOKEN = "page-verify-token"
PAGE_URL = "/api/v1/webhooks/meta/page"


# ---------------------------------------------------------------- payload builders


def _message(mid: str, sender: str, page: str) -> dict:
    return {
        "sender": {"id": sender},
        "recipient": {"id": page},
        "timestamp": 1_700_000_000_000,
        "message": {"mid": mid, "text": "hi"},
    }


def _feed_change(page: str, verb: str = "add") -> dict:
    return {
        "field": "feed",
        "value": {
            "item": "comment",
            "verb": verb,
            "post_id": f"{page}_123",
            "comment_id": f"{page}_456",
            "from": {"id": "customer-1", "name": "Customer"},
            "message": "how much?",
        },
    }


def _mention_change(page: str) -> dict:
    return {"field": "mention", "value": {"post_id": f"{page}_999", "message": "@shop"}}


def _batch(*entries: dict) -> dict:
    return {"object": "page", "entry": list(entries)}


# ------------------------------------------------------------------ routing (pure)


def test_a_mixed_delivery_is_split_into_one_envelope_per_capability() -> None:
    payload = _batch(
        {
            "id": "PAGE-A",
            "time": 1_700_000_000_000,
            "messaging": [_message("m-1", "user-1", "PAGE-A")],
            "changes": [_feed_change("PAGE-A")],
        }
    )

    routed = route_page_payload(payload)

    assert set(routed) == {MESSENGER, FACEBOOK}
    assert len(routed[MESSENGER]) == 1
    assert len(routed[FACEBOOK]) == 1

    chat = routed[MESSENGER][0]
    page_news = routed[FACEBOOK][0]

    # Each envelope keeps ONLY its own kind of event: neither adapter can parse the other's, and
    # nothing is parsed twice.
    assert [m["message"]["mid"] for m in chat["entry"][0]["messaging"]] == ["m-1"]
    assert "changes" not in chat["entry"][0]
    assert [c["field"] for c in page_news["entry"][0]["changes"]] == ["feed"]
    assert "messaging" not in page_news["entry"][0]

    # The delivery-level facts and the entry's own metadata survive the split on BOTH sides.
    for envelope in (chat, page_news):
        assert envelope["object"] == "page"
        assert envelope["entry"][0]["id"] == "PAGE-A"
        assert envelope["entry"][0]["time"] == 1_700_000_000_000


def test_two_pages_in_one_batch_stay_separate_so_each_resolves_its_own_store() -> None:
    payload = _batch(
        {"id": "PAGE-A", "messaging": [_message("a-1", "user-a", "PAGE-A")]},
        {"id": "PAGE-B", "messaging": [_message("b-1", "user-b", "PAGE-B")]},
        {"id": "PAGE-A", "messaging": [_message("a-2", "user-c", "PAGE-A")]},
    )

    routed = route_page_payload(payload)

    # One envelope PER PAGE (the router resolves the tenant once per envelope), in first-seen order.
    assert [env["entry"][0]["id"] for env in routed[MESSENGER]] == ["PAGE-A", "PAGE-B"]
    for envelope in routed[MESSENGER]:
        page = envelope["entry"][0]["id"]
        assert {str(e["id"]) for e in envelope["entry"]} == {page}
    assert [m["message"]["mid"] for m in routed[MESSENGER][0]["entry"][0]["messaging"]] == ["a-1"]
    assert [m["message"]["mid"] for m in routed[MESSENGER][1]["entry"][0]["messaging"]] == ["b-1"]
    # Nothing for Facebook, so it is not given an envelope at all.
    assert routed[FACEBOOK] == []


def test_a_messenger_only_delivery_never_reaches_facebook() -> None:
    routed = route_page_payload(
        _batch({"id": "PAGE-A", "messaging": [_message("m-1", "user-1", "PAGE-A")]})
    )

    assert len(routed[MESSENGER]) == 1
    assert routed[FACEBOOK] == []


def test_a_facebook_only_delivery_never_reaches_messenger() -> None:
    routed = route_page_payload(_batch({"id": "PAGE-A", "changes": [_feed_change("PAGE-A")]}))

    assert len(routed[FACEBOOK]) == 1
    assert routed[MESSENGER] == []


def test_one_entry_carrying_both_kinds_contributes_to_both_without_duplicating() -> None:
    entry = {
        "id": "PAGE-A",
        "messaging": [_message("m-1", "user-1", "PAGE-A"), _message("m-2", "user-2", "PAGE-A")],
        "changes": [_feed_change("PAGE-A"), _mention_change("PAGE-A")],
    }
    routed = route_page_payload(_batch(entry))

    chat_entries = routed[MESSENGER][0]["entry"]
    page_entries = routed[FACEBOOK][0]["entry"]
    # Exactly one copy of the entry on each side — not two, not one shared dict.
    assert len(chat_entries) == 1
    assert len(page_entries) == 1
    assert len(chat_entries[0]["messaging"]) == 2
    assert [c["field"] for c in page_entries[0]["changes"]] == ["feed", "mention"]
    assert classify_entry(entry) == {MESSENGER, FACEBOOK}


def test_standby_events_are_chat_too() -> None:
    """Meta's ``standby`` channel is a second receiver for the same conversation."""
    routed = route_page_payload(
        _batch({"id": "PAGE-A", "standby": [_message("s-1", "user-1", "PAGE-A")]})
    )

    assert [m["message"]["mid"] for m in routed[MESSENGER][0]["entry"][0]["standby"]] == ["s-1"]
    assert routed[FACEBOOK] == []


def test_an_empty_delivery_routes_nowhere() -> None:
    assert route_page_payload({"object": "page", "entry": []}) == {MESSENGER: [], FACEBOOK: []}
    assert route_page_payload({"object": "page"}) == {MESSENGER: [], FACEBOOK: []}
    assert route_page_payload({}) == {MESSENGER: [], FACEBOOK: []}


def test_garbage_entries_are_dropped_instead_of_crashing_the_delivery() -> None:
    """Meta retries a 5xx forever, so a malformed entry must be skipped, not raised."""
    routed = route_page_payload(
        _batch(
            "not-an-entry",  # not even a dict
            {"messaging": [_message("no-id", "u", "?")]},  # no page id
            {"id": "PAGE-A", "messaging": ["not-an-event", None]},  # no usable event
            {"id": "PAGE-B", "changes": ["not-a-change"]},
            {"id": "PAGE-C", "messaging": [_message("ok-1", "u", "PAGE-C")]},
        )
    )

    assert [env["entry"][0]["id"] for env in routed[MESSENGER]] == ["PAGE-C"]
    assert [m["message"]["mid"] for m in routed[MESSENGER][0]["entry"][0]["messaging"]] == ["ok-1"]
    assert routed[FACEBOOK] == []


def test_event_kinds_counts_both_halves_for_the_diagnostics_screen() -> None:
    counts = event_kinds(
        _batch(
            {
                "id": "PAGE-A",
                "messaging": [
                    _message("m-1", "u", "PAGE-A"),
                    {
                        "sender": {"id": "u"},
                        "recipient": {"id": "PAGE-A"},
                        "read": {"watermark": 1},
                    },
                    {
                        "sender": {"id": "u"},
                        "recipient": {"id": "PAGE-A"},
                        "reaction": {"action": "react"},
                    },
                ],
                "changes": [_feed_change("PAGE-A"), _mention_change("PAGE-A")],
            }
        )
    )

    assert counts == {"message": 1, "read": 1, "reaction": 1, "change:feed": 1, "change:mention": 1}


# ------------------------------------------------------- signature / verify (pure)


def _sign(body: bytes, secret: str = PAGE_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def page_settings(monkeypatch):
    """Patch the settings the gateway module reads (app secret + verify token)."""

    def _patch(*, secret: str = PAGE_SECRET, verify: str = VERIFY_TOKEN) -> None:
        monkeypatch.setattr(
            meta_page_events,
            "get_settings",
            lambda: SimpleNamespace(messenger_app_secret=secret, messenger_verify_token=verify),
        )

    _patch()
    return _patch


def test_a_correct_signature_is_accepted(page_settings) -> None:
    raw = json.dumps(_batch({"id": "PAGE-A", "messaging": [_message("m", "u", "PAGE-A")]})).encode()
    assert check_page_signature({"x-hub-signature-256": _sign(raw)}, raw) is True


def test_a_bad_signature_is_rejected(page_settings) -> None:
    raw = b'{"object": "page", "entry": []}'
    assert check_page_signature({"x-hub-signature-256": _sign(b"tampered")}, raw) is False
    assert check_page_signature({}, raw) is False
    # A bare hex digest (no algorithm prefix) is not the header Meta sends.
    assert check_page_signature({"x-hub-signature-256": _sign(raw)[7:]}, raw) is False


def test_a_missing_app_secret_fails_closed(page_settings) -> None:
    page_settings(secret="")
    raw = b'{"object": "page", "entry": []}'
    # Nothing can be verified without the secret, so NOTHING is accepted — not even an
    # empty signature over an empty body.
    assert check_page_signature({"x-hub-signature-256": _sign(raw)}, raw) is False


def test_verify_handshake_returns_the_challenge(page_settings) -> None:
    assert (
        verify_page_request(
            {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "42"}
        )
        == "42"
    )


def test_verify_handshake_refuses_a_wrong_or_missing_token(page_settings) -> None:
    assert (
        verify_page_request(
            {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"}
        )
        is None
    )
    assert verify_page_request({"hub.mode": "subscribe", "hub.challenge": "42"}) is None
    # A non-subscribe mode is not a handshake.
    assert (
        verify_page_request(
            {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "42"}
        )
        is None
    )


def test_verify_handshake_fails_closed_without_a_configured_token(page_settings) -> None:
    page_settings(verify="")
    assert (
        verify_page_request(
            {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "42"}
        )
        is None
    )


# ------------------------------------------- the real route, through the real app


class _FakeSession:
    """Stands in for the request session; ``_ingest_one`` is mocked, so it is never used."""


@pytest.fixture
def ingested(monkeypatch) -> list[dict]:
    """Replace ``_ingest_one`` and the DB session so the route runs without PostgreSQL.

    ``_ingest_one`` is the one seam both per-channel routes and the Page route share, so asserting
    on ITS calls pins the split at exactly the boundary that matters: which capability, which
    envelope, which adapter.
    """
    calls: list[dict] = []

    async def _fake_ingest_one(session, channel, adapter, payload, raw):  # noqa: ANN001
        calls.append(
            {
                "session": session,
                "channel": channel,
                "adapter": adapter,
                "payload": payload,
                "raw": raw,
            }
        )
        return {"ok": True, "queued": True}

    monkeypatch.setattr(webhook_routes, "_ingest_one", _fake_ingest_one)
    return calls


def _app_with_fake_session():
    from app.modules.identity.deps import get_db

    app = create_app()
    fake = _FakeSession()

    async def _session():
        yield fake

    app.dependency_overrides[get_db] = _session
    return app


async def _post_page(app, payload: dict | bytes, *, signature: str | None = None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["x-hub-signature-256"] = signature
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(PAGE_URL, content=raw, headers=headers)


async def test_the_route_is_mounted_under_the_versioned_api() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert PAGE_URL in paths
    assert {"get", "post"} <= set(paths[PAGE_URL])


@pytest.mark.usefixtures("page_settings")
async def test_post_splits_a_mixed_delivery_between_messenger_and_facebook(ingested) -> None:
    payload = _batch(
        {
            "id": "PAGE-A",
            "messaging": [_message("m-1", "user-1", "PAGE-A")],
            "changes": [_feed_change("PAGE-A")],
        }
    )
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "queued": True,
        "capabilities": [MESSENGER, FACEBOOK],
        "deliveries": 2,
    }
    assert [c["channel"] for c in ingested] == [MESSENGER, FACEBOOK]
    assert [c["adapter"].name for c in ingested] == [MESSENGER, FACEBOOK]

    chat, page_news = ingested[0]["payload"], ingested[1]["payload"]
    assert chat["entry"][0]["messaging"][0]["message"]["mid"] == "m-1"
    assert "changes" not in chat["entry"][0]
    assert page_news["entry"][0]["changes"][0]["field"] == "feed"
    assert "messaging" not in page_news["entry"][0]
    # The replay guard digests the bytes Meta signed plus the capability and position, so the two
    # halves of ONE delivery stay distinct (neither dedupes the other away) while the identity is
    # still anchored to the signed body rather than to JSON we re-serialised ourselves.
    digests = [c["raw"] for c in ingested]
    assert digests[0] != digests[1]
    assert all(len(d) == 64 and int(d, 16) >= 0 for d in digests)
    assert hashlib.sha256(raw).hexdigest() not in digests  # a part is never the whole delivery


@pytest.mark.usefixtures("page_settings")
async def test_post_keeps_two_pages_in_one_batch_apart(ingested) -> None:
    payload = _batch(
        {"id": "PAGE-A", "messaging": [_message("a-1", "user-a", "PAGE-A")]},
        {"id": "PAGE-B", "messaging": [_message("b-1", "user-b", "PAGE-B")]},
    )
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json()["deliveries"] == 2
    assert [c["channel"] for c in ingested] == [MESSENGER, MESSENGER]
    assert [c["payload"]["entry"][0]["id"] for c in ingested] == ["PAGE-A", "PAGE-B"]
    assert ingested[0]["payload"]["entry"][0]["messaging"][0]["message"]["mid"] == "a-1"
    assert ingested[1]["payload"]["entry"][0]["messaging"][0]["message"]["mid"] == "b-1"


@pytest.mark.usefixtures("page_settings")
async def test_post_ingests_a_messenger_only_delivery_once(ingested) -> None:
    payload = _batch({"id": "PAGE-A", "messaging": [_message("m-1", "user-1", "PAGE-A")]})
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json()["capabilities"] == [MESSENGER]
    assert [c["channel"] for c in ingested] == [MESSENGER]


@pytest.mark.usefixtures("page_settings")
async def test_post_ingests_a_facebook_only_delivery_once(ingested) -> None:
    payload = _batch({"id": "PAGE-A", "changes": [_feed_change("PAGE-A")]})
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json()["capabilities"] == [FACEBOOK]
    assert [c["channel"] for c in ingested] == [FACEBOOK]
    assert ingested[0]["payload"]["entry"][0]["changes"][0]["value"]["comment_id"] == "PAGE-A_456"


@pytest.mark.usefixtures("page_settings")
async def test_post_acks_an_empty_entry_without_ingesting(ingested) -> None:
    """Meta sends test deliveries with no entries; a 4xx here would fail "Verify and save"."""
    raw = b'{"object": "page", "entry": []}'

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "queued": False,
        "capabilities": [],
        "deliveries": 0,
    }
    assert ingested == []


@pytest.mark.usefixtures("page_settings")
async def test_post_acks_a_delivery_of_pure_garbage_without_ingesting(ingested) -> None:
    payload = _batch(
        "not-an-entry",
        {"messaging": [_message("no-page", "u", "?")]},
        {"id": "PAGE-A", "messaging": ["not-an-event"]},
    )
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 200, response.text
    assert response.json()["deliveries"] == 0
    assert ingested == []


@pytest.mark.usefixtures("page_settings")
async def test_post_rejects_a_bad_signature_before_any_ingest(ingested) -> None:
    payload = _batch({"id": "PAGE-A", "messaging": [_message("m-1", "user-1", "PAGE-A")]})

    response = await _post_page(_app_with_fake_session(), payload, signature=_sign(b"tampered"))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"
    assert ingested == [], "an unsigned delivery must never reach the ingest seam"


@pytest.mark.usefixtures("page_settings")
async def test_post_without_a_signature_header_is_rejected(ingested) -> None:
    payload = _batch({"id": "PAGE-A", "messaging": [_message("m-1", "user-1", "PAGE-A")]})

    response = await _post_page(_app_with_fake_session(), payload)

    assert response.status_code == 403, response.text
    assert ingested == []


async def test_post_is_rejected_when_no_app_secret_is_configured(ingested, page_settings) -> None:
    """Fail closed: with no secret nothing can be verified, so nothing is ingested."""
    page_settings(secret="")
    payload = _batch({"id": "PAGE-A", "messaging": [_message("m-1", "user-1", "PAGE-A")]})
    raw = json.dumps(payload).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 403, response.text
    assert ingested == []


@pytest.mark.usefixtures("page_settings")
async def test_post_refuses_a_signed_body_that_is_not_json(ingested) -> None:
    raw = b"this is not json {{{"

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert ingested == []


@pytest.mark.usefixtures("page_settings")
async def test_post_refuses_signed_json_that_is_not_an_object(ingested) -> None:
    raw = json.dumps([1, 2, 3]).encode()

    response = await _post_page(_app_with_fake_session(), raw, signature=_sign(raw))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert ingested == []


@pytest.mark.usefixtures("page_settings")
async def test_get_verify_handshake_answers_the_challenge() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            PAGE_URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "challenge-123",
            },
        )

    assert response.status_code == 200, response.text
    assert response.text == "challenge-123"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.usefixtures("page_settings")
async def test_get_verify_handshake_refuses_a_wrong_token() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            PAGE_URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "not-the-token",
                "hub.challenge": "challenge-123",
            },
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"


async def test_get_verify_handshake_fails_closed_without_a_configured_token(page_settings) -> None:
    page_settings(verify="")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            PAGE_URL,
            params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "c"},
        )

    assert response.status_code == 403, response.text
