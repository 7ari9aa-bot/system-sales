"""Read the running app and list every /api/v1 operation with its owning module and guard.

Read-only: it walks the router tree the way the openapi lock is built and changes no route. The
module comes from ``endpoint.__module__`` because matching handler names is ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

API_PREFIX = "/api/v1"
# Weakest to strongest. ``public`` needs nothing, ``permission`` needs a named permission code.
ACCESS_KINDS: tuple[str, ...] = ("public", "api_key", "login", "member", "permission")


@dataclass(frozen=True)
class ScannedRoute:
    method: str
    path: str
    module: str
    access: str
    permissions: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def group(self) -> str:
        """First path segment after /api/v1, so ``/api/v1/pos/sell`` belongs to group ``pos``."""
        rest = self.path.removeprefix(API_PREFIX).strip("/")
        return rest.split("/")[0] if rest else ""


def _owner(module_name: str) -> str:
    parts = module_name.split(".")
    if len(parts) > 2 and parts[1] == "modules":
        return parts[2]
    return ".".join(parts[1:3])


def _access(route: APIRoute) -> tuple[str, tuple[str, ...]]:
    perms: set[str] = set()
    kinds: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        stack.extend(dep.dependencies)
        call = dep.call
        name = (getattr(call, "__qualname__", None) or type(call).__name__).lower()
        code = getattr(call, "code", None)
        if isinstance(code, str):
            perms.add(code)
            kinds.add("permission")
        elif "tenant_ctx" in name:
            kinds.add("member")
        elif "api_key" in name or "resolve_tenant" in name:
            kinds.add("api_key")
        elif "user" in name or "auth" in name or "session" in name:
            kinds.add("login")
    for kind in reversed(ACCESS_KINDS):
        if kind in kinds:
            return kind, tuple(sorted(perms))
    return "public", ()


def scan(app: FastAPI) -> list[ScannedRoute]:
    found: list[tuple[str, APIRoute]] = []

    def walk(router, prefix: str = "") -> None:
        for r in router.routes:
            if type(r).__name__ == "_IncludedRouter":
                walk(r.original_router, prefix + (getattr(r.include_context, "prefix", "") or ""))
            elif isinstance(r, APIRoute):
                found.append((prefix + r.path, r))

    walk(app.router)
    out: list[ScannedRoute] = []
    for path, route in found:
        if not path.startswith(API_PREFIX):
            continue
        access, perms = _access(route)
        for method in sorted(route.methods):
            out.append(ScannedRoute(method, path, _owner(route.endpoint.__module__), access, perms))
    return sorted(out, key=lambda x: (x.path, x.method))
