"""Built-in templates.

``register_all`` is called by the package ``__init__`` at import time. The
merchant's 20 templates land here the same way: one module per template that
exposes a ``manifest`` and gets registered.
"""


def register_all(catalog) -> None:  # noqa: ANN001 - catalog type kept local to avoid a cycle
    from app.modules.website.templates.funny_baby import manifest as funny_baby
    from app.modules.website.templates.reference.general_commerce import (
        manifest as general_commerce,
    )
    from app.modules.website.templates.reference.restaurant import manifest as restaurant

    catalog.register(general_commerce)
    catalog.register(restaurant)
    catalog.register(funny_baby)
