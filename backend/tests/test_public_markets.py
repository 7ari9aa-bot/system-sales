"""Tests for the public markets endpoint (/api/v1/public/markets/{country})."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_public_market_egypt():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/markets/eg")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "EG"
        assert data["currency"] == "EGP"
        assert data["default_timezone"] == "Africa/Cairo"
        assert data["launch_status"] == "live"
        assert data["tax_regime"] == "standard"
        assert data["tax_standard_rate"] == 0.14
        assert "Cache-Control" in response.headers
        assert "max-age" in response.headers["Cache-Control"]

        payment_keys = {m["key"] for m in data["payment_methods"]}
        assert "instapay" in payment_keys
        assert "fawry" in payment_keys


@pytest.mark.asyncio
async def test_get_public_market_saudi():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/markets/sa")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "SA"
        assert data["currency"] == "SAR"
        assert data["default_timezone"] == "Asia/Riyadh"
        assert data["launch_status"] == "live"
        assert data["tax_regime"] == "standard"
        assert data["tax_standard_rate"] == 0.15

        payment_keys = {m["key"] for m in data["payment_methods"]}
        assert "mada" in payment_keys
        assert "tamara" in payment_keys


@pytest.mark.asyncio
async def test_get_public_market_qatar_no_vat():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/markets/qa")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "QA"
        assert data["currency"] == "QAR"
        assert data["tax_regime"] == "none"
        assert data["tax_standard_rate"] is None
        assert data["launch_status"] == "waitlist"


@pytest.mark.asyncio
async def test_get_public_market_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/markets/xyz")
        assert response.status_code == 404
