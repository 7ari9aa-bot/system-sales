"""The tool-choice evaluator must tell a good model from a bad one, or its numbers mean nothing.

A tiny local OpenAI-compatible server stands in for the model. It never reaches a shop: the script
records the first tool call and never runs a handler.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts import eval_si_tool_choice as ev


def _serve(pick):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ANN002
            pass

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            name, args = pick(body["messages"][-1]["content"])
            out = {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        }
                    }
                ]
            }
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(monkeypatch, srv):
    import asyncio

    monkeypatch.setenv("EVAL_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("EVAL_API_KEY", "x")
    monkeypatch.setenv("EVAL_MODEL", "fake")
    monkeypatch.setattr("sys.argv", ["eval"])
    return asyncio.run(ev.main())


BY_Q = {c.q: c for c in ev.CASES}


def test_every_expected_tool_is_a_real_tool_and_every_required_arg_exists():
    from app.modules.ai.agents.sales_intelligence import tools as T
    from app.modules.ai.tools import get_tool

    T.register_si_tools()
    for c in ev.CASES:
        for name in c.ok:
            spec = get_tool(name)
            assert spec is not None, f"{c.q!r} expects {name}, which is not a tool"
            props = spec.args_schema.model_json_schema()["properties"]
            for k in c.args:
                assert k in props, f"{c.q!r} requires {k}, which {name} does not take"


def test_a_model_that_picks_right_scores_full(monkeypatch):
    srv = _serve(lambda q: (BY_Q[q].ok[0], dict(BY_Q[q].args)))
    try:
        assert _run(monkeypatch, srv) == 0
    finally:
        srv.shutdown()


def test_a_model_that_picks_a_look_alike_fails(monkeypatch):
    srv = _serve(
        lambda q: (
            "si_cashier_summary" if BY_Q[q].ok[0] != "si_cashier_summary" else "si_metric",
            {},
        )
    )
    try:
        assert _run(monkeypatch, srv) == 1
    finally:
        srv.shutdown()


def test_the_right_tool_with_the_wrong_mode_fails(monkeypatch):
    srv = _serve(lambda q: (BY_Q[q].ok[0], {k: "nope" for k in BY_Q[q].args}))
    try:
        assert _run(monkeypatch, srv) == 1
    finally:
        srv.shutdown()


def test_an_unreachable_endpoint_is_reported_not_scored_as_a_failure(monkeypatch):
    monkeypatch.setenv("EVAL_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("EVAL_API_KEY", "x")
    monkeypatch.setenv("EVAL_MODEL", "fake")
    monkeypatch.setattr("sys.argv", ["eval"])
    import asyncio

    assert asyncio.run(ev.main()) == 2


def test_missing_settings_exit_2(monkeypatch):
    import asyncio

    for k in ("EVAL_BASE_URL", "EVAL_API_KEY", "EVAL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sys.argv", ["eval"])
    assert asyncio.run(ev.main()) == 2


@pytest.mark.parametrize("c", ev.CASES)
def test_score_rejects_no_tool_call(c):
    ok, why = ev.score(c, {"tool": None, "args": {}, "text": "hi"})
    assert not ok and "no tool" in why
