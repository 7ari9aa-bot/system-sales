"""Every Meta failure has a name, the name carries no secret, and recording never raises."""

import ast
import pathlib
import re

import pytest

from app.core import meta_diagnostics as md

FAKE = "EAAUtSPZCPZCF0BTfakefakefakefakefake1234567890"
APP = pathlib.Path(__file__).resolve().parent.parent / "app"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"code": 190, "error_subcode": 463}, "token.expired"),
        ({"code": 190, "error_subcode": 467}, "token.invalidated"),
        ({"code": 190, "error_subcode": 460}, "token.invalidated"),
        ({"code": 190}, "token.invalidated"),
        ({"code": 10}, "permission.denied"),
        ({"code": 200}, "permission.denied"),
        ({"code": 4}, "send.rate_limited"),
        ({"code": 80007}, "send.rate_limited"),
        ({"code": 368}, "account.restricted"),
        ({"code": 131047}, "send.window_closed"),
        ({"code": 131026}, "send.recipient_unreachable"),
        ({"code": 999999}, "api.unexpected"),
        ({}, "api.unexpected"),
        (None, "api.unexpected"),
        ("not a dict", "api.unexpected"),
    ],
)
def test_graph_errors_are_classified(error, expected):
    assert md.classify_graph_error(error) == expected


def test_every_classification_target_exists_in_the_catalog():
    for _code, _sub, key in md._GRAPH_RULES:
        assert key in md.CATALOG, key


def test_catalog_entries_are_complete_and_severity_is_valid():
    assert md.CATALOG
    for key, issue in md.CATALOG.items():
        assert re.fullmatch(r"[a-z]+(\.[a-z_]+)+", key), key
        assert issue.severity in {"critical", "high", "medium", "low"}, key
        assert issue.summary.strip() and issue.action.strip(), key


def test_graph_error_fields_keep_the_support_id_and_drop_nothing_secret():
    fields = md.graph_error_fields(
        {
            "message": f"bad token {FAKE}",
            "code": 190,
            "error_subcode": 463,
            "type": "OAuthException",
            "fbtrace_id": "AbC123",
            "unrelated": "dropped",
        }
    )
    assert fields["fbtrace_id"] == "AbC123"
    assert fields["error_subcode"] == 463
    assert "unrelated" not in fields
    assert FAKE not in str(fields)


def test_details_are_redacted_bounded_and_carry_the_catalog_text():
    body = md.build_details(
        "link.no_pages",
        channel="instagram",
        details={
            "url": f"https://graph.facebook.com/me?access_token={FAKE}",
            "n": 3,
            "x": "y" * 9000,
        },
    )
    assert FAKE not in str(body)
    assert body["severity"] == "high"
    assert body["channel"] == "instagram"
    assert body["action"]
    assert len(body["x"]) <= 500


@pytest.fixture(autouse=True)
def _fresh_dedupe(monkeypatch):
    md._fallback.clear()
    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: None)
    yield
    md._fallback.clear()


async def test_recording_never_raises_even_when_the_writer_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", boom)
    await md.record_channel_issue("webhook.bad_signature", channel="messenger")


async def test_event_type_is_prefixed_and_details_reach_the_writer(monkeypatch):
    seen = {}

    async def fake(event_type, **kwargs):
        seen.update(event_type=event_type, **kwargs)

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", fake)
    await md.record_channel_issue(
        "link.no_instagram_account", channel="instagram", details={"page_id": "1215323418341930"}
    )
    assert seen["event_type"] == "meta.link.no_instagram_account"
    assert seen["details"]["page_id"] == "1215323418341930"
    assert seen["details"]["channel"] == "instagram"


def _call_sites_keys():
    """Every literal key passed to record_channel_issue anywhere in app/."""
    keys = []
    for path in APP.rglob("*.py"):
        if path.name == "meta_diagnostics.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", ""))
                == "record_channel_issue"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                keys.append((str(path.relative_to(APP)), node.args[0].value))
    return keys


def test_every_call_site_uses_a_catalogued_key():
    for where, key in _call_sites_keys():
        assert key in md.CATALOG, f"{where} records an unknown key {key!r}"


async def test_a_flood_of_the_same_failure_writes_one_row(monkeypatch):
    rows = []

    async def fake(event_type, **kwargs):
        rows.append(event_type)

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", fake)
    for _ in range(500):
        await md.record_channel_issue("webhook.bad_signature", channel="messenger")
    assert rows == ["meta.webhook.bad_signature"]


async def test_different_channels_and_keys_are_counted_separately(monkeypatch):
    rows = []

    async def fake(event_type, **kwargs):
        rows.append((event_type, kwargs["details"]["channel"]))

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", fake)
    await md.record_channel_issue("webhook.bad_signature", channel="messenger")
    await md.record_channel_issue("webhook.bad_signature", channel="instagram")
    await md.record_channel_issue("webhook.unparsable", channel="messenger")
    assert len(rows) == 3


async def test_without_redis_the_row_count_is_still_bounded(monkeypatch):
    rows = []

    async def fake(event_type, **kwargs):
        rows.append(event_type)

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", fake)
    for i in range(500):
        await md.record_channel_issue("webhook.unknown_account", channel=f"c{i}")
    assert len(rows) == md._FALLBACK_BUDGET


async def test_redis_failure_falls_back_instead_of_losing_the_event(monkeypatch):
    rows = []

    async def fake(event_type, **kwargs):
        rows.append(event_type)

    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis_or_none", broken)
    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", fake)
    await md.record_channel_issue("webhook.bad_signature", channel="messenger")
    assert rows == ["meta.webhook.bad_signature"]
