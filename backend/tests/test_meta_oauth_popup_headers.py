"""The OAuth result page must be able to run its one script and keep window.opener.

Regression: SecurityHeadersMiddleware's blanket ``default-src 'none'`` + COOP
``same-origin`` blocked the page's inline script and severed the opener, so a
successful connect still showed "window closed before confirmation".
"""

import re

from app.modules.customers.meta_oauth import _popup_html, _popup_response


def _response(result):
    return _popup_response(result, "https://fihrist.world")


def test_script_nonce_matches_csp_and_no_unsafe_inline_script():
    resp = _response({"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"})
    csp = resp.headers["content-security-policy"]
    body = resp.body.decode()

    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in body
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert "unsafe-inline" not in script_src
    assert "'self'" not in script_src
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_opener_is_preserved_for_this_response_only():
    resp = _response({"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"})
    assert resp.headers["cross-origin-opener-policy"] == "unsafe-none"
    assert resp.headers["cache-control"] == "no-store"


def test_nonce_is_unique_per_response():
    a = _response({"type": "META_OAUTH_RESULT", "error": "x"}).headers["content-security-policy"]
    b = _response({"type": "META_OAUTH_RESULT", "error": "x"}).headers["content-security-policy"]
    assert a != b


def test_all_three_result_channels_and_autoclose_present_on_success():
    body = _response({"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"}).body.decode()
    for needle in (
        "opener.postMessage",
        "BroadcastChannel",
        "localStorage.setItem",
        "window.close",
    ):
        assert needle in body


def test_popup_html_default_nonce_is_valid_html():
    assert "<script nonce=" in _popup_html({"type": "META_OAUTH_RESULT", "error": "x"}, "https://x")
