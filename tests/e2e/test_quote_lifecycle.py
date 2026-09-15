"""Quote lifecycle rules: expiry, single-use acceptance, and fund movement.

These cover the states a conversion can end up in other than success. They
matter more than the happy path in one respect: a bug here moves someone's
money twice, or moves it at a price that is no longer valid.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bvnk_sim import (
    PaymentStatus,
    Quote,
    QuoteStatus,
    quote_request,
    wait_for_expiry,
    wait_for_settlement,
)

pytestmark = pytest.mark.e2e


def _pending_quote(account, amount: str = "0.5", reference: str = "lifecycle") -> Quote:
    """Create an ETH -> TRX quote and leave it unaccepted."""
    response = account.client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=account.wallet("ETH").id,
            target_wallet_id=account.wallet("TRX").id,
            amount_in=amount,
            reference=reference,
        )
    )
    assert response.status_code == 201, response.describe()
    return Quote.model_validate(response.json)


@pytest.mark.slow
def test_quote_expires_after_the_documented_window_and_cannot_be_accepted(account, settings):
    """A quote must stop being acceptable once its 20 second window closes.

    This is the rule that protects the exchange from being held to a stale
    price: without it, a client could sit on a favourable quote and accept it
    after the market moved.
    """
    balances_before = account.balances()
    quote = _pending_quote(account, reference="expiry")

    assert quote.acceptance_window_seconds == settings.acceptance_window_seconds
    assert quote.state == (QuoteStatus.PENDING, PaymentStatus.PENDING)

    # Waits on the server's own expiry timestamp rather than a hardcoded 20
    # seconds, then polls for the transition — the API reports PENDING for a
    # couple of seconds past the deadline it published, so asserting straight
    # after the deadline is a race. See flows.wait_for_expiry.
    expired_quote = wait_for_expiry(account.client, quote, settings)

    assert expired_quote.state == (QuoteStatus.EXPIRED, PaymentStatus.EXPIRED)
    assert expired_quote.acceptance_date is None

    rejected = account.client.accept_quote(quote.uuid)
    assert rejected.status_code == 412, rejected.describe()
    assert rejected.detail == "Precondition Failed"

    # The critical part: a rejected acceptance must not have moved anything.
    account.refresh()
    assert account.balances() == balances_before, (
        "balances changed after an expired quote was rejected"
    )


def test_quote_cannot_be_accepted_twice(account, settings):
    """Accepting a settled quote again must fail rather than convert twice."""
    quote = _pending_quote(account, reference="double-accept")

    first = account.client.accept_quote(quote.uuid)
    assert first.status_code == 200, first.describe()
    wait_for_settlement(account.client, quote.uuid, settings)

    account.refresh()
    balances_after_first = account.balances()

    second = account.client.accept_quote(quote.uuid)
    assert second.status_code == 400, second.describe()
    assert second.detail == "Bad Request"

    account.refresh()
    assert account.balances() == balances_after_first, (
        "a second acceptance moved funds again — the conversion was applied twice"
    )


def test_creating_a_quote_does_not_move_funds(account):
    """Quoting is a price enquiry: nothing should leave the wallet yet.

    Note this also documents that the simulator does *not* reserve the funds
    behind a pending quote — ``available`` is unchanged, so several quotes can
    be open at once for more than the wallet holds. Whether that is intended is
    worth a conversation; the point of the test is that the behaviour is
    pinned down rather than discovered by accident later.
    """
    before = {code: (w.balance, w.available) for code, w in account.wallets.items()}

    quote = _pending_quote(account, reference="no-reservation")
    assert quote.state == (QuoteStatus.PENDING, PaymentStatus.PENDING)

    account.refresh()
    after = {code: (w.balance, w.available) for code, w in account.wallets.items()}
    assert after == before, "creating a quote changed a balance"


def test_quotes_are_listed_for_the_account_that_created_them(account):
    """A fresh account has no quotes; a created quote appears in its list."""
    empty = account.client.list_quotes()
    assert empty.status_code == 200, empty.describe()
    assert empty.json == [], "a newly initialised account already has quotes"

    quote = _pending_quote(account, reference="listing")

    listed = account.client.list_quotes()
    assert listed.status_code == 200, listed.describe()
    quotes = [Quote.model_validate(item) for item in listed.json]
    assert [q.uuid for q in quotes] == [quote.uuid]
    assert quotes[0].amount_in == quote.amount_in


def test_reverse_quote_prices_a_target_amount(account):
    """``amountOut`` may be specified instead of ``amountIn``.

    Useful for "I need exactly 1000 TRX, what does it cost me" — the API
    computes the input. Worth covering because it is the one documented request
    shape the conversion scenarios never exercise.
    """
    target_amount = Decimal("1000")
    response = account.client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=account.wallet("ETH").id,
            target_wallet_id=account.wallet("TRX").id,
            amount_out=target_amount,
            reference="reverse-quote",
        )
    )
    assert response.status_code == 201, response.describe()
    quote = Quote.model_validate(response.json)

    assert quote.amount_out == target_amount
    assert quote.amount_in > 0, "reverse quote did not compute an input amount"
    assert quote.amount_in <= account.wallet("ETH").available
