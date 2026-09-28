"""WhatsApp provider responsibilities are served by FastAPI itself."""

from __future__ import annotations

from app.main import create_app


def test_fastapi_exposes_the_versioned_whatsapp_webhook_contract() -> None:
    paths = create_app().openapi()["paths"]

    assert set(paths["/api/v1/webhooks/{channel}"]) >= {"get", "post"}


def test_fastapi_does_not_expose_the_removed_proxy_paths() -> None:
    paths = create_app().openapi()["paths"]

    assert "/webhook/whatsapp" not in paths
    assert "/whatsapp-send" not in paths
