"""The image ceiling is a setting, not a constant two places can disagree about."""

from __future__ import annotations

from app.modules.settings.registry import get_definition


def test_max_images_is_a_setting_with_a_home_and_a_bound() -> None:
    d = get_definition("catalog.max_images_per_sku")
    assert d is not None
    assert d.home == ("catalog", "images-and-media")
    assert d.default == 10
    assert d.min_value >= 1
    assert d.max_value >= d.default


def test_the_catalog_constant_is_only_a_fallback() -> None:
    """limits.py must not be the authority: the service reads the setting first."""
    import inspect

    from app.modules.catalog.services import taxonomy

    src = inspect.getsource(taxonomy)
    assert "catalog.max_images_per_sku" in src
    assert src.index("catalog.max_images_per_sku") < src.index(">= limit")
