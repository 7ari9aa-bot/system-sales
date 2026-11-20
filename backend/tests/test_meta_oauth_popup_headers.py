"""The OAuth result page must report back to the opener under the site CSP.

Regression: a successful connect still showed "window closed before
confirmation" because (a) COOP ``same-origin`` severed window.opener after the
facebook.com round trip and (b) the page's inline script was blocked
(``default-src 'none'`` from the API, ``script-src 'self'`` stamped by the
Vercel proxy on every path), so no result channel ever fired.
"""

import json
import re
from pathlib import Path

from app.modules.customers.meta_oauth import _popup_response

ORIGIN = "https://fihrist.world"
RESULT_JS = Path(__file__).resolve().parents[2] / "frontend" / "public" / "meta-oauth-result.js"


def _response(result):
    return _popup_response(result, ORIGIN)


def test_no_inline_script_or_handler_under_a_strict_csp():
    for result in (
        {"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"},
        {"type": "META_OAUTH_RESULT", "error": "access_denied"},
    ):
        body = _response(result).body.decode()
        executable = re.findall(
            r"<script(?![^>]*type=\"application/json\")[^>]*>(.*?)</script>", body, re.S
        )
        assert all(not chunk.strip() for chunk in executable), "inline code would be blocked by CSP"
        assert not re.search(r"\son[a-z]+=", body), "inline event handler would be blocked by CSP"
        assert f'<script src="{ORIGIN}/meta-oauth-result.js"></script>' in body


def test_result_is_inert_json_the_external_script_can_read():
    result = {"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"}
    body = _response(result).body.decode()
    raw = re.search(r'<script id="meta-oauth-data"[^>]*>(.*?)</script>', body, re.S).group(1)
    assert json.loads(raw) == result
    assert 'data-autoclose="1"' in body
    assert f'data-origin="{ORIGIN}"' in body


def test_json_payload_cannot_break_out_of_its_script_tag():
    body = _response(
        {"type": "META_OAUTH_RESULT", "error": "</script><script>alert(1)</script>"}
    ).body.decode()
    assert "</script><script>alert" not in body
    assert 'data-autoclose="0"' in body


def test_csp_allows_only_the_site_script_and_opener_is_preserved():
    resp = _response({"type": "META_OAUTH_RESULT", "connected": "messenger:Meruna"})
    csp = resp.headers["content-security-policy"]
    assert f"script-src {ORIGIN};" in csp
    assert "unsafe-inline" not in re.search(r"script-src [^;]+", csp).group(0)
    assert "default-src 'none'" in csp
    assert resp.headers["cross-origin-opener-policy"] == "unsafe-none"
    assert resp.headers["cache-control"] == "no-store"


def test_external_script_uses_all_result_channels_and_autoclose():
    js = RESULT_JS.read_text()
    for needle in (
        "meta-oauth-data",
        "opener.postMessage",
        "BroadcastChannel",
        "meta_oauth",
        "localStorage.setItem",
        "meta_oauth_result",
        "window.close",
        "meta-oauth-close",
    ):
        assert needle in js
