"""Async client for the external Website Platform partner API.

The partner key lives in settings (`website_platform_api_key`) and NEVER
reaches the frontend. All failures surface as WebsitePlatformError with the
platform error contract {code, message, details}.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class WebsitePlatformError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(f"website-platform {status}: {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


async def _request(method: str, path: str, *, json: dict | None = None, use_partner_key: bool = True) -> Any:
    settings = get_settings()
    if use_partner_key and not settings.website_platform_api_key:
        raise WebsitePlatformError(500, "WP_NOT_CONFIGURED", "WEBSITE_PLATFORM_API_KEY is not set")
    headers = {"Content-Type": "application/json"}
    if use_partner_key:
        headers["Authorization"] = f"Partner {settings.website_platform_api_key}"
    url = f"{settings.website_platform_api_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.request(method, url, headers=headers, json=json)
    if res.status_code >= 400:
        try:
            body = res.json()
            raise WebsitePlatformError(res.status_code, body.get("code", "UNKNOWN"), body.get("message", res.text[:200]), body.get("details"))
        except ValueError as exc:
            raise WebsitePlatformError(res.status_code, "NON_JSON", res.text[:200]) from exc
    if res.status_code == 204 or not res.content:
        return {}
    return res.json()


async def resolve_website(external_tenant_id: str) -> dict:
    return await _request("GET", f"/api/v1/partner/websites?externalUserId={external_tenant_id}")


async def provision_website(*, email: str, external_tenant_id: str, tenant_name: str, website_name: str, template_id: str | None, display_name: str | None = None) -> dict:
    return await _request(
        "POST",
        "/api/v1/partner/websites",
        json={
            "email": email,
            "externalUserId": external_tenant_id,
            "tenantName": tenant_name,
            "websiteName": website_name,
            "templateId": template_id,
            "displayName": display_name,
        },
    )


async def sso_session(*, email: str) -> dict:
    return await _request("POST", "/api/v1/partner/sso/session", json={"email": email})


async def publish(website_id: str) -> dict:
    return await _request("POST", f"/api/v1/partner/websites/{website_id}/publish", json={})


async def usage(organization_id: str) -> dict:
    return await _request("GET", f"/api/v1/partner/usage/{organization_id}")


async def templates() -> list[dict]:
    settings = get_settings()
    url = f"{settings.website_platform_api_url.rstrip('/')}/api/v1/templates"
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.get(url)
    res.raise_for_status()
    return res.json()
