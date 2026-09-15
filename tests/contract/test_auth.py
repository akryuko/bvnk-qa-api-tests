"""Authentication contract.

Every protected endpoint is checked against every way of getting auth wrong,
as a matrix rather than one test per endpoint. Auth bugs are rarely uniform —
it is common for one late-added endpoint to be missing the dependency the
others have — and a matrix is what catches the odd one out.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from bvnk_sim import SimulatorClient, quote_request

pytestmark = pytest.mark.contract

#: A uuid that is well-formed but certainly not ours: auth must be rejected
#: before the API ever looks the quote up, so these still expect 401 and not 404.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

PROTECTED_ENDPOINTS: dict[str, Callable[[SimulatorClient], object]] = {
    "GET /api/wallet": lambda client: client.list_wallets(),
    "GET /api/wallet/{id}": lambda client: client.get_wallet(1),
    "POST /echo": lambda client: client.echo({"probe": True}),
    "GET /api/v1/quote": lambda client: client.list_quotes(),
    "GET /api/v1/quote/{uuid}": lambda client: client.get_quote(ABSENT_UUID),
    "PUT /api/v1/quote/accept/{uuid}": lambda client: client.accept_quote(ABSENT_UUID),
    "POST /api/v1/quote": lambda client: client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=1,
            target_wallet_id=2,
            amount_in="1",
        )
    ),
}


@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS, ids=list(PROTECTED_ENDPOINTS))
def test_protected_endpoint_rejects_a_missing_token(anonymous_client, endpoint):
    response = PROTECTED_ENDPOINTS[endpoint](anonymous_client)
    assert response.status_code == 401, response.describe()
    assert response.detail == "Not authenticated"
    assert not isinstance(response.json, list), "endpoint returned data without a token"


@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS, ids=list(PROTECTED_ENDPOINTS))
def test_protected_endpoint_rejects_an_unknown_token(anonymous_client, endpoint):
    """A well-formed but unissued token is distinguishable from no token at all.

    The API says "Not authenticated" for a missing header and "Unauthorized"
    for a token it does not recognise. Both are 401, so the message is the only
    thing pinning the distinction down.
    """
    forged = anonymous_client.as_token("0" * 64)
    response = PROTECTED_ENDPOINTS[endpoint](forged)
    assert response.status_code == 401, response.describe()
    assert response.detail == "Unauthorized"


@pytest.mark.parametrize(
    "header_value",
    ["NotBearer abc123", "abc123", "Basic dXNlcjpwYXNz"],
    ids=["wrong-scheme", "no-scheme", "basic-auth"],
)
def test_only_the_bearer_scheme_is_accepted(anonymous_client, header_value):
    response = anonymous_client.http.request(
        "GET", "/api/wallet", headers={"Authorization": header_value}
    )
    assert response.status_code == 401, response.describe()
    assert response.detail == "Not authenticated"


def test_a_freshly_issued_token_is_accepted(account):
    """The counterweight to the tests above.

    Without this, every test in this module would still pass if the API simply
    rejected everything.
    """
    response = account.client.list_wallets()
    assert response.status_code == 200, response.describe()
    assert len(response.json) == 3
