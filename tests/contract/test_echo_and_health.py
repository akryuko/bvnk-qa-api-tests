"""The two diagnostic endpoints: /echo and /health.

``/echo`` is more useful than it looks — it is the only endpoint that reports
when the caller's token expires, so it is where the token's lifetime can be
verified against what ``/init`` promised.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bvnk_sim import EchoResponse, HealthMetrics

pytestmark = pytest.mark.contract

ONE_DAY_SECONDS = 24 * 60 * 60

#: Allowance for request latency and clock skew between this machine and the API.
CLOCK_TOLERANCE_SECONDS = 300


@pytest.mark.parametrize(
    "payload",
    [
        {"currency": "ETH", "nested": {"amount": "1.5", "flag": True}},
        {},
        "a plain string",
        12345,
        None,
    ],
    ids=["object", "empty-object", "string", "integer", "null"],
)
def test_echo_reflects_the_request_body_unchanged(account, payload):
    response = account.client.echo(payload)
    assert response.status_code == 200, response.describe()

    echo = EchoResponse.model_validate(response.json)
    assert echo.request_payload == payload


def test_echo_reports_the_same_expiry_that_init_issued(account):
    """Cross-checks two endpoints against each other.

    ``/init`` returns the expiry as epoch seconds and ``/echo`` returns it as a
    formatted string; they must describe the same instant. This is the kind of
    inconsistency that only shows up when something compares the two.
    """
    response = account.client.echo({"probe": "expiry"})
    assert response.status_code == 200, response.describe()
    echo = EchoResponse.model_validate(response.json)

    # The API sends no timezone, and the value is UTC (verified against the
    # epoch below), so a naive parse compared against a naive UTC value is the
    # honest reading of it.
    reported = datetime.strptime(  # noqa: DTZ007 - deliberately naive, see above
        echo.auth_token_expiry_time, "%Y-%m-%d %H:%M:%S"
    )
    expected = datetime.fromtimestamp(account.token_expiry, tz=timezone.utc).replace(tzinfo=None)
    assert reported == expected, (
        f"/echo says the token expires at {reported} (UTC) but /init issued "
        f"expiry={account.token_expiry}, which is {expected}"
    )


def test_issued_tokens_last_a_day(account):
    """``/init`` issues a token valid for 24 hours.

    The tolerance is wide because this comparison involves *this machine's*
    clock: the difference covers request latency plus any skew between the test
    runner and the server. Five minutes is loose enough never to fail on a
    slightly out-of-sync laptop, and still tight enough to catch a token issued
    for an hour or a week.
    """
    lifetime = account.token_expiry - datetime.now(tz=timezone.utc).timestamp()
    assert abs(lifetime - ONE_DAY_SECONDS) < CLOCK_TOLERANCE_SECONDS, (
        f"token lifetime is {lifetime:.0f}s, expected about {ONE_DAY_SECONDS}s"
    )


def test_health_is_public_and_reports_metrics(anonymous_client):
    response = anonymous_client.health()
    assert response.status_code == 200, response.describe()

    health = HealthMetrics.model_validate(response.json)
    assert health.uptime, "no uptime reported"
    assert health.approximate_db_size, "no database size reported"
    assert health.total_authenticated_requests >= 0
