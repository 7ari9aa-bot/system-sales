"""WhatsApp keeps what Meta said about a failure, and tells the owner why a number was refused.

A delivery failure used to keep only ``errors[0].message``: no code, so a temporary fault could not
be told from a blocked number or an unpaid account. A refused number registration collapsed every
cause except 133016 into "finish verifying the number".
"""

from __future__ import annotations

import httpx
import pytest

from app.applications.apparel.modules.conversations.gateway.whatsapp import whatsapp_adapter
from app.applications.apparel.modules.customers.meta_whatsapp_signup import _register_error


def _failed(**error) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.1",
                                    "status": "failed",
                                    "timestamp": "1700000000",
                                    "errors": [error],
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_a_failed_status_keeps_meta_code_title_and_details() -> None:
    [u] = whatsapp_adapter.parse_status_updates(
        _failed(
            code=131047,
            title="Re-engagement message",
            message="Re-engagement message",
            error_data={"details": "More than 24 hours have passed"},
        )
    )
    assert u.error_code == 131047
    assert u.error_title == "Re-engagement message"
    assert u.error_details == "More than 24 hours have passed"
    assert u.error.startswith("131047: Re-engagement message")
    assert "More than 24 hours" in u.error


def test_a_status_without_errors_has_no_error_fields() -> None:
    payload = {
        "entry": [{"changes": [{"value": {"statuses": [{"id": "w", "status": "delivered"}]}}]}]
    }
    [u] = whatsapp_adapter.parse_status_updates(payload)
    assert (u.error, u.error_code, u.error_title, u.error_details) == (None, None, None, None)


def test_a_failure_with_only_a_title_still_reads() -> None:
    [u] = whatsapp_adapter.parse_status_updates(
        _failed(code=130472, title="User's number is part of an experiment")
    )
    assert u.error == "130472: User's number is part of an experiment"


def _refusal(code, text="x", subcode=None) -> httpx.Response:
    error = {"code": code, "message": text}
    if subcode:
        error["error_subcode"] = subcode
    return httpx.Response(400, json={"error": error})


@pytest.mark.parametrize(
    ("code", "needle", "retryable"),
    [
        (133016, "72 hours", False),
        (133005, "PIN", False),
        (133006, "verified again", False),
        (133008, "wrong two-step PIN", False),
        (133009, "too quickly", True),
        (133010, "not registered yet", True),
        (190, "Connect again", False),
        (200, "permission", False),
        (80007, "limiting", True),
    ],
)
def test_each_known_refusal_gets_its_own_message(code, needle, retryable) -> None:
    error = _register_error(_refusal(code))
    assert needle in str(error)
    assert error.retryable is retryable


def test_the_meta_code_and_text_travel_with_the_message() -> None:
    error = _register_error(_refusal(133005, "Incorrect PIN", subcode=2388001))
    assert "Meta 133005/2388001: Incorrect PIN" in str(error)


def test_an_unknown_code_keeps_the_generic_advice_and_the_code() -> None:
    error = _register_error(_refusal(999999, "weird"))
    assert "Finish verifying the number" in str(error)
    assert "999999" in str(error)
    assert error.retryable is False


def test_an_unreadable_refusal_is_still_an_error_not_a_crash() -> None:
    error = _register_error(httpx.Response(502, text="<html>bad gateway</html>"))
    assert "Finish verifying the number" in str(error)
