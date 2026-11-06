"""Website templates: the manifest contract + the built-in templates.

Importing this package registers the templates into the module-level
``catalog`` (fail-closed: a template whose preset sections fail the section
registry breaks the import, same contract as the AI agent registry).
"""

from app.modules.website.templates import reference as _reference
from app.modules.website.templates.catalog import (
    TemplateManifest,
    TemplatePage,
    TemplateSection,
    WebsiteTemplateCatalog,
    catalog,
)
from app.modules.website.templates.funny_baby import manifest as _funny_baby
from app.modules.website.templates.street_poster import manifest as _street_poster
from app.modules.website.templates.warm_paper import manifest as _warm_paper

_reference.register_all(catalog)
catalog.register(_funny_baby)
catalog.register(_warm_paper)
catalog.register(_street_poster)

__all__ = [
    "TemplateManifest",
    "TemplatePage",
    "TemplateSection",
    "WebsiteTemplateCatalog",
    "catalog",
]
