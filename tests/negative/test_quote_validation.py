"""Rejection paths for quote creation and lookup.

An exchange API is judged as much by what it refuses as by what it does. Each
test below asserts the status code *and* the message, because the code alone
does not tell a client what to fix — and a 400 that says the wrong thing is its
own defect.
"""

from __future__ import annotations

import pytest

from bvnk_sim import quote_request

pytestmark = pytest.mark.negative

REQUIRED_QUOTE_FIELDS = {
    "fromWallet",
    "toWallet",
    "useMaximum",
    "useMinimum",
    "reference",
    "payInMethod",
    "payOutMethod",
}


def _valid_body(account, **overrides):
    return quote_request(
        source_currency="ETH",
        target_currency="TRX",
        source_wallet_id=account.wallet("ETH").id,
        target_wallet_id=account.wallet("TRX").id,
        amount_in="1",
        reference="negative",
        **overrides,
    )


def test_a_body_missing_required_fields_lists_every_one_of_them(account):
    """Reporting only the first missing field would mean N round trips to fix N."""
    response = account.client.create_quote({"from": "ETH", "to": "TRX"})
    assert response.status_code == 422, response.describe()

    reported = {
        error["loc"][1]
        for error in response.json["detail"]
        if error["type"] == "missing" and error["loc"][0] == "body"
    }
    assert reported >= REQUIRED_QUOTE_FIELDS, (
        f"missing fields not reported: {sorted(REQUIRED_QUOTE_FIELDS - reported)}"
    )


def test_a_quote_with_no_amount_at_all_is_rejected(account):
    body = _valid_body(account)
    body.pop("amountIn")

    response = account.client.create_quote(body)
    assert response.status_code == 400, response.describe()
    assert response.detail == (
        "One of 'amountIn' or 'amountOut' must be specified but not both."
    )


def test_specifying_both_amounts_is_rejected(account):
    response = account.client.create_quote(_valid_body(account, amountOut="1000"))
    assert response.status_code == 400, response.describe()
    assert response.detail == (
        "One of 'amountIn' or 'amountOut' must be specified but not both."
    )


def test_converting_more_than_the_wallet_holds_is_refused(account):
    """A 412 here, not a 400: the request is well-formed, the account is not ready."""
    source = account.wallet("ETH")
    too_much = source.available * 2

    response = account.client.create_quote(_valid_body(account, amountIn=str(too_much)))
    assert response.status_code == 412, response.describe()
    assert response.detail == f"Insufficient funds available in source wallet #{source.id}."

    # And no quote was created as a side effect of the failed attempt.
    listed = account.client.list_quotes()
    assert listed.json == [], "a rejected quote request still created a quote"


def test_source_currency_must_match_the_source_wallet(account):
    """Guards against a transposed wallet id silently trading the wrong asset."""
    response = account.client.create_quote(
        _valid_body(account, fromWallet=account.wallet("TRX").id)
    )
    assert response.status_code == 400, response.describe()
    assert response.detail == (
        "Request to trade ETH for TRX but source wallet has currency TRX."
    )


def test_currency_codes_are_case_sensitive(account):
    """``eth`` is not ``ETH`` — the wallet's currency comparison is exact."""
    response = account.client.create_quote(_valid_body(account, **{"from": "eth"}))
    assert response.status_code == 400, response.describe()
    assert response.detail == (
        "Request to trade eth for TRX but source wallet has currency ETH."
    )


def test_an_unrecognised_currency_code_is_rejected(account):
    """Note *how* it is rejected: on the wallet mismatch, not on the code itself.

    The API never validates the currency code in isolation — it compares it to
    the source wallet's currency. Since wallets exist only for ETH, TRX and
    USDT, there is no way to send an unsupported code that also matches its
    wallet, so this path is the only observable rejection for one.
    """
    response = account.client.create_quote(_valid_body(account, **{"from": "BTC"}))
    assert response.status_code == 400, response.describe()
    assert response.detail == (
        "Request to trade BTC for TRX but source wallet has currency ETH."
    )


def test_unknown_quote_uuid_is_not_found(account):
    absent = "00000000-0000-4000-8000-000000000000"

    read = account.client.get_quote(absent)
    assert read.status_code == 404, read.describe()
    assert read.detail == "Not Found"

    accept = account.client.accept_quote(absent)
    assert accept.status_code == 404, accept.describe()
    assert accept.detail == "Not Found"


@pytest.mark.parametrize(
    "malformed",
    ["not-a-uuid", "12345", "00000000-0000-4000-8000"],
    ids=["words", "digits", "truncated"],
)
def test_malformed_quote_uuid_is_a_validation_error(account, malformed):
    response = account.client.get_quote(malformed)
    assert response.status_code == 422, response.describe()

    errors = response.json["detail"]
    assert errors[0]["loc"] == ["path", "quote_uuid"]
    assert errors[0]["type"] == "uuid_parsing"


def test_a_destination_wallet_that_does_not_exist_is_rejected(account):
    response = account.client.create_quote(_valid_body(account, toWallet=999_999))
    assert response.status_code == 400, response.describe()
    assert response.detail == "Destination wallet with ID #999999 not found."


def test_a_rejected_request_moves_no_funds(account):
    """A refusal must be inert — no partial debit, no fee taken for the attempt."""
    before = account.balances()

    response = account.client.create_quote(
        _valid_body(account, amountIn=str(account.wallet("ETH").available * 10))
    )
    assert response.status_code == 412, response.describe()

    account.refresh()
    assert account.balances() == before
