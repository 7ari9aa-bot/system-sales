"""Credentials must never reach the logs (httpx logged Meta URLs with access_token=...)."""

import io
import logging

import httpx
import pytest

from app.core.log_redaction import REDACTED, RedactSecretsFilter, install_secret_redaction, redact

FAKE = "EAAUtSPZCPZCF0BTfakefakefakefakefake1234567890"


def test_graph_url_token_is_redacted_and_the_rest_survives():
    url = (
        "HTTP Request: GET https://graph.facebook.com/v27.0/me/accounts"
        f'?fields=id%2Cname&access_token={FAKE} "HTTP/1.1 200 OK"'
    )
    out = redact(url)
    assert FAKE not in out
    assert f"access_token={REDACTED}" in out
    assert "fields=id%2Cname" in out and "HTTP/1.1 200 OK" in out


@pytest.mark.parametrize(
    "text",
    [
        f"client_secret={FAKE}&code=abc123&redirect_uri=https://x.test/cb",
        f"{{'access_token': '{FAKE}'}}",
        f'{{"fb_exchange_token": "{FAKE}"}}',
        f"Authorization: Bearer {FAKE}",
        f"something went wrong with {FAKE} today",
    ],
)
def test_other_shapes_are_redacted(text):
    assert FAKE not in redact(text)


def test_oauth_code_is_redacted():
    assert "abc123" not in redact("callback?code=abc123&state=s")


@pytest.mark.parametrize(
    "text",
    ["page 1215323418341930 connected", "tokens refreshed: 3", "status=active provider=facebook"],
)
def test_ordinary_text_is_untouched(text):
    assert redact(text) == text


def _logger_with_filter():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactSecretsFilter())
    log = logging.getLogger("test.redaction.unique")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.DEBUG)
    return log, stream


def test_filter_rewrites_formatted_args_not_just_the_template():
    log, stream = _logger_with_filter()
    log.info("GET %s", f"https://graph.facebook.com/me?access_token={FAKE}")
    assert FAKE not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_bad_format_string_does_not_lose_the_line():
    log, stream = _logger_with_filter()
    log.info("only one placeholder %s")  # no args: getMessage-safe path
    assert "only one placeholder" in stream.getvalue()


def test_installed_on_root_handlers_and_httpx_is_quiet(monkeypatch):
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    monkeypatch.setattr(root, "handlers", [handler])
    install_secret_redaction()
    install_secret_redaction()  # idempotent
    assert sum(isinstance(f, RedactSecretsFilter) for f in handler.filters) == 1
    assert logging.getLogger("httpx").level == logging.WARNING


def test_real_httpx_request_line_never_carries_the_token(monkeypatch):
    """End to end with the real library, through a root handler the way the app wires it."""
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    monkeypatch.setattr(root, "handlers", [handler])
    monkeypatch.setattr(root, "level", logging.INFO)
    install_secret_redaction()
    # Defeat the second layer on purpose: the filter alone must be enough.
    logging.getLogger("httpx").setLevel(logging.INFO)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    try:
        with httpx.Client(transport=transport) as client:
            client.get("https://graph.facebook.com/v27.0/me", params={"access_token": FAKE})
    finally:
        logging.getLogger("httpx").setLevel(logging.NOTSET)
    written = stream.getvalue()
    assert "graph.facebook.com" in written, "httpx request line was not captured"
    assert FAKE not in written
    assert f"access_token={REDACTED}" in written
