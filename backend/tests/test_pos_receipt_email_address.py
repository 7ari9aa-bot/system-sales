"""The receipt-email address is validated like every other email in the app.

It used to be ``"@" in email``, so ``a@``, ``a@b@c`` and ``a@b.com,c@d.com`` all queued a real send
from the merchant's own domain. A cashier could point it at any list of addresses.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.modules.errors import ValidationError
from app.modules.pos.router import ReceiptEmailRequest

BAD = [
    "a@",
    "x@y",
    "a@b@c",
    "a b@c.com",
    "a@b.com,c@d.com",
    "a@b.com\nBcc: x@y.com",
    "a@.",
    "@@@",
]


@pytest.mark.parametrize("address", BAD)
def test_the_request_refuses_a_malformed_address(address):
    with pytest.raises(PydanticValidationError):
        ReceiptEmailRequest(email=address)


def test_the_request_accepts_a_real_address_and_trims_it():
    assert ReceiptEmailRequest(email="  customer@example.com ").email == "customer@example.com"


@pytest.mark.parametrize("address", BAD)
def test_the_service_refuses_it_too(address):
    from app.modules.pos.service import PosService

    with pytest.raises(ValidationError):
        PosService._clean_receipt_email(address)


def test_the_service_returns_the_cleaned_address():
    from app.modules.pos.service import PosService

    assert (
        PosService._clean_receipt_email(" Customer@Example.com ") == "Customer@example.com"
    )  # the domain is case-insensitive, the local part is not
