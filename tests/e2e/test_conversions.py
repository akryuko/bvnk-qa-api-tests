"""The headline end-to-end conversions.

Each test walks the full journey — read balances, quote, accept, wait for
settlement, read balances again — and checks the things that could plausibly
be wrong at every step, not just that the final number moved.

Two rules shape every assertion here:

*Nothing is compared against a hardcoded rate.* The simulator's exchange rates
fluctuate; ETH -> TRX was observed at 12594.59 and 13083.33 within two minutes.
Expectations are recomputed from what the quote itself reports.

*Balances are compared exactly, derived amounts with a tolerance.* Settlement
moves precisely ``amountIn`` and ``amountOut``, so those are exact Decimal
comparisons. Recomputing ``amountOut`` from ``price`` cannot be exact, because
``price`` is reported already rounded to 8 dp — see ``money.amount_out_tolerance``.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from scenarios import CORE_CONVERSIONS

from bvnk_sim import (
    SETTLED,
    PaymentStatus,
    Quote,
    QuoteStatus,
    expected_conversion,
    quote_request,
    wait_for_settlement,
)

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("scenario", CORE_CONVERSIONS, ids=str)
def test_conversion_settles_and_moves_exactly_the_quoted_amounts(account, settings, scenario):
    source = account.wallet(scenario.source)
    target = account.wallet(scenario.target)

    # --- Preconditions ---------------------------------------------------
    # Checked rather than assumed: if the account fixture ever stops funding
    # these wallets, the failure should say so instead of surfacing as a
    # confusing 412 three steps later.
    assert source.status == "ACTIVE", f"{source.code} wallet is {source.status}"
    assert target.status == "ACTIVE", f"{target.code} wallet is {target.status}"
    assert source.available >= scenario.amount, (
        f"{source.code} wallet holds {source.available}, "
        f"cannot convert {scenario.amount}"
    )

    balances_before = account.balances()

    # --- 1. Create the quote ---------------------------------------------
    response = account.client.create_quote(
        quote_request(
            source_currency=scenario.source,
            target_currency=scenario.target,
            source_wallet_id=source.id,
            target_wallet_id=target.id,
            amount_in=scenario.amount,
            reference=f"e2e-{scenario}",
        )
    )
    assert response.status_code == 201, response.describe()

    # Validating the whole payload, not just the fields asserted below:
    # a type change or a missing field anywhere fails here.
    quote = Quote.model_validate(response.json)

    assert quote.state == (QuoteStatus.PENDING, PaymentStatus.PENDING)
    assert quote.from_currency == scenario.source
    assert quote.to_currency == scenario.target
    assert quote.amount_in == scenario.amount
    assert quote.amount_due == quote.amount_in
    assert quote.price > 0, "a quote priced at zero would let funds vanish"
    assert quote.amount_out > 0
    assert quote.pay_in_method.settlement_currency == scenario.source
    assert quote.pay_out_method.currency == scenario.target

    # The documented acceptance window.
    assert quote.acceptance_window_seconds == settings.acceptance_window_seconds
    assert quote.acceptance_expiry_date > time.time(), "quote arrived already expired"

    # --- 2. The money maths ----------------------------------------------
    expectation = expected_conversion(
        quote,
        destination_precision=target.currency.quantity_precision,
        price_precision=target.currency.price_precision,
        settings=settings,
    )

    assert quote.fee == expectation.fee, (
        f"expected a {settings.service_fee_rate:%} service fee of {expectation.fee} "
        f"on {quote.amount_in} {scenario.source}, API charged {quote.fee}"
    )
    assert quote.fees.value.service == quote.fee
    assert quote.fees.percentage.service / 100 == settings.service_fee_rate
    assert quote.processing_fee == Decimal(0)
    assert quote.fees.value.processing == Decimal(0)

    # Cross-check that amountOut is consistent with amountIn, fee and price.
    # The fee itself is proven by the exact assertion above, not by this one:
    # on pairs with a very small price the reported 8 dp rate is too coarse for
    # this comparison to detect a fee error. See money.amount_out_tolerance.
    difference = abs(quote.amount_out - expectation.amount_out)
    assert difference <= expectation.tolerance, (
        f"amountOut {quote.amount_out} differs from "
        f"({quote.amount_in} - {quote.fee}) * {quote.price} = {expectation.amount_out} "
        f"by {difference}, which exceeds the {expectation.tolerance} allowed for "
        f"the quoted price's own rounding"
    )

    # --- 3. Accept it ------------------------------------------------------
    accepted_response = account.client.accept_quote(quote.uuid)
    assert accepted_response.status_code == 200, accepted_response.describe()
    accepted = Quote.model_validate(accepted_response.json)

    assert accepted.uuid == quote.uuid
    assert accepted.quote_status == QuoteStatus.ACCEPTED
    assert accepted.acceptance_date is not None, "accepted quote has no acceptanceDate"
    assert accepted.acceptance_date <= accepted.acceptance_expiry_date, (
        "quote was accepted after its own expiry"
    )
    # Accepting must not re-price the trade.
    assert (accepted.amount_in, accepted.amount_out, accepted.price, accepted.fee) == (
        quote.amount_in,
        quote.amount_out,
        quote.price,
        quote.fee,
    )

    # --- 4. Wait for settlement -------------------------------------------
    # Accept returns ACCEPTED/PROCESSING with the balances untouched; they move
    # asynchronously. Polling here is what keeps step 5 deterministic.
    settled = wait_for_settlement(account.client, quote.uuid, settings)
    assert settled.state == SETTLED, f"conversion did not succeed: {settled.state}"
    assert settled.amount_out == quote.amount_out, "settled amount differs from the quote"
    assert settled.amount_in == quote.amount_in

    # --- 5. Balances -------------------------------------------------------
    account.refresh()
    balances_after = account.balances()

    assert balances_after[scenario.source] == balances_before[scenario.source] - quote.amount_in, (
        f"{scenario.source}: {balances_before[scenario.source]} -> "
        f"{balances_after[scenario.source]}, expected a debit of exactly {quote.amount_in}"
    )
    assert balances_after[scenario.target] == balances_before[scenario.target] + quote.amount_out, (
        f"{scenario.target}: {balances_before[scenario.target]} -> "
        f"{balances_after[scenario.target]}, expected a credit of exactly {quote.amount_out}"
    )

    # The fee is taken out of the proceeds, not charged separately on top of
    # the debit — this is what distinguishes the two possible fee models.
    debit = balances_before[scenario.source] - balances_after[scenario.source]
    assert debit == quote.amount_in, (
        f"source wallet was debited {debit}, expected {quote.amount_in} "
        f"with the {quote.fee} fee absorbed into amountOut"
    )

    # Wallets not involved in the trade must not move.
    for code in set(balances_before) - {scenario.source, scenario.target}:
        assert balances_after[code] == balances_before[code], (
            f"{code} wallet changed during a {scenario.source}->{scenario.target} conversion"
        )


@pytest.mark.parametrize("scenario", CORE_CONVERSIONS, ids=str)
def test_settled_quote_is_immutable_when_read_back(account, settings, scenario):
    """A completed conversion must still report the same numbers afterwards.

    Re-reading a quote is how a client reconciles a trade it has already made,
    so the record has to be stable. Kept separate from the flow test above so
    that a reconciliation regression is not hidden behind a balance failure.
    """
    source = account.wallet(scenario.source)
    target = account.wallet(scenario.target)

    created = account.client.create_quote(
        quote_request(
            source_currency=scenario.source,
            target_currency=scenario.target,
            source_wallet_id=source.id,
            target_wallet_id=target.id,
            amount_in=scenario.amount,
            reference=f"immutability-{scenario}",
        )
    )
    assert created.status_code == 201, created.describe()
    quote = Quote.model_validate(created.json)

    accept = account.client.accept_quote(quote.uuid)
    assert accept.status_code == 200, accept.describe()
    wait_for_settlement(account.client, quote.uuid, settings)

    reread = account.client.get_quote(quote.uuid)
    assert reread.status_code == 200, reread.describe()
    final = Quote.model_validate(reread.json)

    assert final.uuid == quote.uuid
    assert final.state == SETTLED
    assert (final.amount_in, final.amount_out, final.price, final.fee) == (
        quote.amount_in,
        quote.amount_out,
        quote.price,
        quote.fee,
    )
    assert final.date_created == quote.date_created
    assert final.last_updated >= quote.last_updated
