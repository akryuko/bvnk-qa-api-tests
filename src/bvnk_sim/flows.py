"""Domain-level operations built on top of the raw client.

These are the things a test wants to say once rather than spell out five times:
"give me a funded account", "wait until this conversion has actually settled",
"here is what amountOut should be".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from .client import SimulatorClient
from .config import Settings
from .models import IN_FLIGHT, InitResponse, Quote, QuoteStatus, Wallet
from .money import amount_out_tolerance, expected_amount_out, service_fee


@dataclass
class Account:
    """A freshly initialised account and its wallets.

    Wallet ids are allocated globally by the simulator and increment across
    accounts — the first account sees ids 1-3, the next 4-6, and so on. So ids
    are always looked up by currency code here, never hardcoded.

    Another account's wallet id is refused, with the status depending on how it
    is used: reading it directly gives 404, naming it as a conversion target
    gives 400. ``tests/contract/test_account_isolation.py`` covers both.
    """

    client: SimulatorClient
    token: str
    token_expiry: int
    wallets: dict[str, Wallet] = field(default_factory=dict)

    @classmethod
    def create(cls, client: SimulatorClient) -> Account:
        response = client.init_account()
        assert response.status_code == 200, f"/init failed{response.describe()}"
        init = InitResponse.model_validate(response.json)

        account = cls(
            client=client.as_token(init.access_token),
            token=init.access_token,
            token_expiry=init.expiry,
        )
        account.refresh()
        return account

    def refresh(self) -> None:
        """Re-read every wallet, so balances reflect the latest settlement."""
        response = self.client.list_wallets(offset=0, max_count=50)
        assert response.status_code == 200, f"listing wallets failed{response.describe()}"
        wallets = [Wallet.model_validate(item) for item in response.json]
        self.wallets = {wallet.code: wallet for wallet in wallets}

    def wallet(self, currency_code: str) -> Wallet:
        try:
            return self.wallets[currency_code]
        except KeyError:  # pragma: no cover - a setup failure, not a test failure
            raise AssertionError(
                f"account has no {currency_code} wallet; it has {sorted(self.wallets)}"
            ) from None

    def balances(self) -> dict[str, Decimal]:
        """Current balance of every wallet, keyed by currency code."""
        return {code: wallet.balance for code, wallet in self.wallets.items()}


def wait_for_settlement(
    client: SimulatorClient,
    quote_uuid: UUID | str,
    settings: Settings,
) -> Quote:
    """Poll a quote until its payment reaches a terminal state.

    Accepting a quote returns 200 with ACCEPTED/PROCESSING and the wallet
    balances have *not* moved yet — settlement happens asynchronously a moment
    later. Asserting on balances straight after accept is the single easiest
    way to write a flaky test against this API, so every flow goes through here.
    """
    deadline = time.monotonic() + settings.settlement_timeout
    attempts = 0
    quote: Quote | None = None

    while time.monotonic() < deadline:
        attempts += 1
        response = client.get_quote(quote_uuid)
        assert response.status_code == 200, f"re-reading quote failed{response.describe()}"
        quote = Quote.model_validate(response.json)
        if quote.payment_status not in IN_FLIGHT:
            return quote
        time.sleep(settings.settlement_poll_interval)

    raise AssertionError(
        f"quote {quote_uuid} did not settle within {settings.settlement_timeout}s "
        f"({attempts} polls); last seen state was {quote.state if quote else 'unknown'}"
    )


def wait_for_expiry(
    client: SimulatorClient,
    quote: Quote,
    settings: Settings,
) -> Quote:
    """Wait until the API actually reports a pending quote as expired.

    The obvious implementation — sleep until ``acceptanceExpiryDate`` and then
    assert — is a race, because the API goes on reporting PENDING for a short
    while after the deadline it published. Measured against the live simulator,
    the status flipped about 2.8 seconds late; a two second grace period was
    enough to fail the test intermittently.

    So this sleeps through the published deadline (nothing can change before
    it) and then polls for the transition, the same way settlement is waited
    for. That makes the test deterministic without making it slower, and it
    stays correct if the lag changes.
    """
    time.sleep(max(0.0, quote.acceptance_expiry_date - time.time()))

    deadline = time.monotonic() + settings.expiry_timeout

    while True:
        response = client.get_quote(quote.uuid)
        assert response.status_code == 200, f"re-reading quote failed{response.describe()}"
        latest = Quote.model_validate(response.json)
        if latest.quote_status == QuoteStatus.EXPIRED:
            return latest
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"quote {quote.uuid} was still {latest.quote_status} "
                f"{time.time() - quote.acceptance_expiry_date:.1f}s after its "
                f"acceptanceExpiryDate, having waited {settings.expiry_timeout}s"
            )
        time.sleep(settings.settlement_poll_interval)


@dataclass(frozen=True)
class ConversionExpectation:
    """What the numbers on a quote should be, recomputed independently."""

    fee: Decimal
    amount_out: Decimal
    tolerance: Decimal


def expected_conversion(
    quote: Quote,
    destination_precision: int,
    price_precision: int,
    settings: Settings,
) -> ConversionExpectation:
    """Recompute a quote's fee and output from its inputs.

    Deliberately derived from the quote's own ``amountIn`` and ``price`` rather
    than from a fixed expected rate: the simulator's rates fluctuate, and a
    test that hardcodes a rate tests nothing except how recently it was written.
    """
    fee = service_fee(quote.amount_in, settings.service_fee_rate)
    amount_out = expected_amount_out(
        quote.amount_in, fee, quote.price, destination_precision
    )
    tolerance = amount_out_tolerance(
        quote.amount_in - fee, price_precision, destination_precision
    )
    return ConversionExpectation(fee=fee, amount_out=amount_out, tolerance=tolerance)
