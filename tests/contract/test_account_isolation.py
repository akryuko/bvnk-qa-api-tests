"""Cross-account isolation.

Wallet ids are allocated globally and increment predictably across accounts —
the first account gets 1-3, the next 4-6 — so another customer's wallet id is
trivially guessable. That makes these the highest-value tests in the suite:
they are the difference between a multi-tenant API and a shared database.

The API answers 404 rather than 403 for another account's resources, which is
the right choice: it does not confirm that the id exists.
"""

from __future__ import annotations

import pytest

from bvnk_sim import Quote, quote_request

pytestmark = pytest.mark.contract


def test_another_accounts_wallet_is_not_readable(account, other_account):
    victim_wallet_id = other_account.wallet("ETH").id
    assert victim_wallet_id not in {w.id for w in account.wallets.values()}, (
        "fixture error: both accounts share a wallet id"
    )

    response = account.client.get_wallet(victim_wallet_id)
    assert response.status_code == 404, response.describe()
    assert response.detail == "Not Found"


def test_another_accounts_wallet_cannot_be_used_as_a_conversion_target(account, other_account):
    """Funds must not be routable into a wallet the caller does not own."""
    response = account.client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=account.wallet("ETH").id,
            target_wallet_id=other_account.wallet("TRX").id,
            amount_in="0.1",
            reference="cross-account-payout",
        )
    )
    assert response.status_code == 400, response.describe()
    assert "not found" in (response.detail or "").lower()


def test_another_accounts_quote_is_neither_readable_nor_acceptable(account, other_account):
    created = other_account.client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=other_account.wallet("ETH").id,
            target_wallet_id=other_account.wallet("TRX").id,
            amount_in="0.1",
            reference="victim-quote",
        )
    )
    assert created.status_code == 201, created.describe()
    victim_quote = Quote.model_validate(created.json)

    read = account.client.get_quote(victim_quote.uuid)
    assert read.status_code == 404, read.describe()

    accept = account.client.accept_quote(victim_quote.uuid)
    assert accept.status_code == 404, accept.describe()

    # And the victim's quote must be untouched by the attempt.
    still_pending = other_account.client.get_quote(victim_quote.uuid)
    assert still_pending.status_code == 200, still_pending.describe()
    assert Quote.model_validate(still_pending.json).acceptance_date is None


def test_quote_listing_is_scoped_to_the_calling_account(account, other_account):
    created = other_account.client.create_quote(
        quote_request(
            source_currency="ETH",
            target_currency="TRX",
            source_wallet_id=other_account.wallet("ETH").id,
            target_wallet_id=other_account.wallet("TRX").id,
            amount_in="0.1",
            reference="scoping",
        )
    )
    assert created.status_code == 201, created.describe()

    listed = account.client.list_quotes()
    assert listed.status_code == 200, listed.describe()
    assert listed.json == [], "another account's quotes are visible in this account's list"
