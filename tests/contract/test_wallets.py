"""Wallet endpoint contract: content, consistency, pagination and errors."""

from __future__ import annotations

import pytest

from bvnk_sim import Wallet

pytestmark = pytest.mark.contract

EXPECTED_CURRENCIES = {"ETH", "TRX", "USDT"}


def test_a_new_account_has_three_funded_active_wallets(account):
    assert set(account.wallets) == EXPECTED_CURRENCIES

    for code, wallet in account.wallets.items():
        assert wallet.status == "ACTIVE", f"{code} wallet is {wallet.status}"
        assert wallet.balance > 0, f"{code} wallet is unfunded"
        assert wallet.available == wallet.balance, (
            f"{code} has {wallet.balance} balance but only {wallet.available} available "
            "on a brand new account, so something is already held"
        )
        assert wallet.currency.code == code
        assert wallet.address, f"{code} wallet has no address"


def test_currency_metadata_is_usable_for_money_maths(account):
    """The precision fields are not decoration — the fee assertions rely on them."""
    for code, wallet in account.wallets.items():
        currency = wallet.currency
        assert currency.fiat is False, f"{code} is flagged as fiat"
        assert currency.quantity_precision > 0, f"{code} has no quantity precision"
        assert currency.price_precision > 0, f"{code} has no price precision"
        assert currency.protocols, f"{code} lists no protocols"
        assert wallet.protocol in {p.code for p in currency.protocols}, (
            f"{code} wallet uses protocol {wallet.protocol}, "
            f"not among {[p.code for p in currency.protocols]}"
        )


def test_single_wallet_matches_its_entry_in_the_list(account):
    for expected in account.wallets.values():
        response = account.client.get_wallet(expected.id)
        assert response.status_code == 200, response.describe()
        assert Wallet.model_validate(response.json) == expected, (
            f"wallet {expected.id} differs between the list and single-wallet endpoints"
        )


def test_pagination_splits_the_wallet_list(account):
    """Paging must partition the list — no wallet skipped, none returned twice."""
    total = len(account.wallets)
    page_size = 2

    first = account.client.list_wallets(offset=0, max_count=page_size)
    assert first.status_code == 200, first.describe()
    assert len(first.json) == page_size

    second = account.client.list_wallets(offset=page_size, max_count=page_size)
    assert second.status_code == 200, second.describe()
    assert len(second.json) == total - page_size

    paged_ids = [w["id"] for w in first.json] + [w["id"] for w in second.json]
    assert paged_ids == sorted(w.id for w in account.wallets.values()), (
        "paging through the wallets did not return each one exactly once"
    )


def test_offset_beyond_the_end_returns_an_empty_page(account):
    response = account.client.list_wallets(offset=99, max_count=10)
    assert response.status_code == 200, response.describe()
    assert response.json == []


def test_unknown_wallet_id_is_not_found(account):
    response = account.client.get_wallet(999_999)
    assert response.status_code == 404, response.describe()
    assert response.detail == "Not Found"


def test_non_integer_wallet_id_is_a_validation_error(account):
    response = account.client.get_wallet("not-an-integer")
    assert response.status_code == 422, response.describe()

    errors = response.json["detail"]
    assert [error["loc"] for error in errors] == [["path", "wallet_id"]]
    assert errors[0]["type"] == "int_parsing"
