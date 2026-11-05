"""Website templates: the manifest contract + built-in reference templates.

Importing this package registers the reference templates into the module-level
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

_reference.register_all(catalog)

__all__ = [
    "TemplateManifest",
    "TemplatePage",
    "TemplateSection",
    "WebsiteTemplateCatalog",
    "catalog",
]
