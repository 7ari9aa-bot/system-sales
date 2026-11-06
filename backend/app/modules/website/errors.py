"""Website domain exceptions.

Mapped at the API edge by the shared ``DomainError`` handler; every code is
stable and machine-readable. Publish validation is a 422 (the request was
well-formed but the CONTENT cannot go live), following the spec's contract.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import ConflictError, NotFoundError, ValidationError


class WebsiteDomainError(ValidationError):
    """Base for website-specific validation refusals (400)."""

    code = "website_error"
    default_message = "Website error"


class TemplateNotFoundError(NotFoundError):
    code = "website_template_not_found"
    default_message = "Website template not found"


class InvalidSection(ValidationError):
    """A section's type is unknown or its props fail the registry schema."""

    code = "website_section_invalid"
    http_status = 422
    default_message = "Invalid section"

    def __init__(self, section_type: str, reason: str) -> None:
        super().__init__(
            f"invalid section {section_type!r}: {reason}",
            details={"section_type": section_type, "reason": reason},
        )


class SlugUnavailableError(ConflictError):
    code = "website_slug_unavailable"
    default_message = "This site address is already taken"


class SlugReservedError(WebsiteDomainError):
    code = "website_slug_reserved"
    default_message = "This site address is reserved"


class PurchaseStateError(ConflictError):
    code = "website_purchase_state"
    default_message = "Purchase is not in a state that allows this action"


class PublishValidationFailed(ValidationError):
    """A failed publish must never break the live site: raised BEFORE any
    mutation, with the full list of content errors."""

    code = "website_publish_invalid"
    http_status = 422
    default_message = "Website content failed publish validation"

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(
            "website content failed publish validation",
            details={"errors": self.errors},
        )


class RollbackNotAllowed(ConflictError):
    code = "website_rollback_not_allowed"
    default_message = "Cannot roll back to this version"

    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason, details=details or None)


class NoDraftError(ConflictError):
    code = "website_no_draft"
    default_message = "There is no draft version to publish"
