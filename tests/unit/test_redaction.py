"""Access tokens must never reach a log, a report, or a failure message.

``GET /init`` returns a live bearer token in its *response body*, and this suite
logs every response body and embeds those logs in the HTML report. Redacting
only the Authorization header would leave working credentials in a file that
gets committed and shared. These tests are the guard against that regressing.
"""

from __future__ import annotations

import pytest

from bvnk_sim.http import ApiResponse, redact_secrets

pytestmark = pytest.mark.unit

#: Shaped like a real token from /init, but not one.
TOKEN = "a1b2c3d4" * 8


def test_a_token_in_a_response_body_is_masked():
    body = f'{{"access_token":"{TOKEN}","token_type":"bearer","expiry":1789548705}}'

    redacted = redact_secrets(body)

    assert TOKEN not in redacted
    assert "<redacted-token>" in redacted
    # Everything else survives, so the log is still useful.
    assert '"token_type":"bearer"' in redacted
    assert "1789548705" in redacted


def test_tokens_are_masked_wherever_they_appear():
    """Matching on shape, not on a key name, covers /echo reflecting one back."""
    for body in (
        f'{{"request_payload":{{"token":"{TOKEN}"}}}}',
        f"Unauthorized: {TOKEN} is not a known token",
        f'["{TOKEN}","{TOKEN.upper()}"]',
    ):
        assert TOKEN not in redact_secrets(body)
        assert TOKEN.upper() not in redact_secrets(body)


def test_ordinary_content_is_left_alone():
    body = '{"amountOut":"12593.335135","uuid":"3642869f-386c-49ea-99c5-df16c4727377"}'
    assert redact_secrets(body) == body


def test_failure_messages_do_not_leak_the_token():
    """describe() is what lands in a pytest failure and in the HTML report."""
    response = ApiResponse(
        method="GET",
        url="https://example.test/init",
        status_code=200,
        elapsed_ms=12.0,
        headers={},
        text=f'{{"access_token":"{TOKEN}"}}',
        json={"access_token": TOKEN},
    )

    assert TOKEN not in response.describe()
