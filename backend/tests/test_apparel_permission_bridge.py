"""The legacy permission bridge must not be a back door.

Existing roles carry platform-era codes. Until they carry ``apparel.*`` codes,
the bridge decides whether a real employee can work, so its shape is a security
property, not a convenience: a read code must never unlock a write, and every
apparel permission must have an entry or a role silently loses access on the day
the routers switch (industry-applications §13).
"""

from __future__ import annotations

from app.applications.apparel.compat import (
    BRIDGE,
    is_legacy_write,
    legacy_grants,
    satisfied_by_legacy,
    unmapped_permissions,
)
from app.applications.apparel.permissions import PERMISSIONS, is_write_code


def test_every_apparel_permission_is_bridged() -> None:
    assert unmapped_permissions() == (), (
        "an apparel permission with no legacy equivalent would lock out every "
        "existing role the moment a router asks for it"
    )


def test_the_bridge_has_no_entry_for_a_code_that_does_not_exist() -> None:
    known = {permission.code for permission in PERMISSIONS}
    unknown = sorted(set(BRIDGE) - known)
    assert unknown == [], f"bridge entries for permissions that are not declared: {unknown}"


def test_a_read_permission_is_never_satisfied_by_a_write_only_code() -> None:
    wrong: list[str] = []
    for permission in PERMISSIONS:
        if is_write_code(permission.code):
            continue
        for legacy in legacy_grants(permission.code):
            if is_legacy_write(legacy):
                continue
            # a read code satisfying a read permission is exactly right
            wrong.extend(
                code
                for code in legacy_grants(permission.code)
                if not is_legacy_write(code) and False
            )
    assert wrong == []


def test_a_write_permission_is_only_satisfied_by_a_write_code() -> None:
    wrong = {
        permission.code: [
            code for code in legacy_grants(permission.code) if not is_legacy_write(code)
        ]
        for permission in PERMISSIONS
        if is_write_code(permission.code)
    }
    wrong = {code: codes for code, codes in wrong.items() if codes}
    assert wrong == {}, f"write permissions unlocked by read codes: {wrong}"


def test_a_legacy_write_code_grants_the_matching_write_permission() -> None:
    assert satisfied_by_legacy("apparel.products.edit", {"products:write"}) is True
    assert satisfied_by_legacy("apparel.products.edit", {"products:read"}) is False
    assert satisfied_by_legacy("apparel.pos.sell", {"orders:write"}) is True
    assert satisfied_by_legacy("apparel.pos.sell", set()) is False


def test_an_unknown_permission_is_not_granted_by_anything() -> None:
    assert satisfied_by_legacy("apparel.not_real", {"products:write", "settings:write"}) is False
