import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture()
def app():
    return create_app()


async def test_healthz(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "environment" in body


async def test_readyz_reports_dependencies(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    # Without live postgres/redis the endpoint must report NOT ready with detail.
    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"database", "redis"}
    assert body["ready"] is all(v == "ok" for v in body["checks"].values())
