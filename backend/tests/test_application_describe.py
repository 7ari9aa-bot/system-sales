"""Every application is described, and the row says which gate closed."""

from __future__ import annotations

from app.platform.applications.access import describe
from app.platform.applications.manifests import REGISTRY


def test_every_application_gets_exactly_one_row() -> None:
    rows = describe({})
    assert [row["key"] for row in rows] == list(REGISTRY)
    assert len(rows) == len(REGISTRY)


def test_an_unentitled_application_is_not_allowed_and_says_so() -> None:
    rows = {row["key"]: row for row in describe({})}
    assert all(row["allowed"] is False for row in rows.values())
    assert all(str(row["reason"]).startswith("not_entitled") for row in rows.values())


def test_an_entitled_and_installed_application_is_allowed() -> None:
    key = "apparel"
    rows = {
        row["key"]: row
        for row in describe(
            {
                "entitled_applications": frozenset({key}),
                "installation_states": {key: "active"},
            }
        )
    }
    assert rows[key]["allowed"] is True
    assert rows[key]["reason"] == "allowed"


def test_installed_but_unfinished_setup_is_reported_separately() -> None:
    key = "apparel"
    rows = {
        row["key"]: row
        for row in describe(
            {
                "entitled_applications": frozenset({key}),
                "installation_states": {key: "setup_required"},
            }
        )
    }
    assert rows[key]["allowed"] is False
    assert "setup" in str(rows[key]["reason"])


def test_titles_come_from_the_manifest() -> None:
    rows = {row["key"]: row for row in describe({})}
    for key, row in rows.items():
        assert row["title_ar"] == REGISTRY[key].title_ar
        assert row["title_en"] == REGISTRY[key].title_en
