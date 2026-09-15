"""Offline checks on the money helpers.

These need no network: they replay three conversions actually observed against
the live simulator and assert that the helpers reproduce them. Their job is to
make sure a failing E2E assertion means "the API is wrong", not "our arithmetic
is wrong" — the two are easy to confuse when a test is red at 2am.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bvnk_sim.money import (
    amount_out_tolerance,
    expected_amount_out,
    service_fee,
    to_decimal,
    truncate,
)

pytestmark = pytest.mark.unit

FEE_RATE = Decimal("0.0001")

# (label, amountIn, price, fee, amountOut, destination precision, price precision)
# Captured from the live API on 2026-09-15.
OBSERVED_CONVERSIONS = [
    ("1 ETH -> TRX", "1.00000000", "12594.59459459", "0.0001", "12593.335135", 6, 8),
    ("420 TRX -> USDT", "420.000000", "0.22559653", "0.042", "94.741067", 6, 8),
    ("987 TRX -> ETH", "987.000000", "0.00007595", "0.0987", "0.07495453", 8, 8),
]


@pytest.mark.parametrize(
    "label,amount_in,price,fee,amount_out,dest_dp,price_dp",
    OBSERVED_CONVERSIONS,
    ids=[case[0] for case in OBSERVED_CONVERSIONS],
)
def test_helpers_reproduce_a_real_conversion(
    label, amount_in, price, fee, amount_out, dest_dp, price_dp
):
    amount_in = to_decimal(amount_in)
    expected_fee = service_fee(amount_in, FEE_RATE)
    assert expected_fee == to_decimal(fee)

    recomputed = expected_amount_out(amount_in, expected_fee, to_decimal(price), dest_dp)
    tolerance = amount_out_tolerance(amount_in - expected_fee, price_dp, dest_dp)

    difference = abs(recomputed - to_decimal(amount_out))
    assert difference <= tolerance, (
        f"{label}: recomputed {recomputed} vs actual {amount_out}, "
        f"off by {difference} with {tolerance} allowed"
    )


def test_tolerance_is_tight_enough_to_catch_a_missing_fee():
    """A tolerance that accepts everything would make the amountOut check useless.

    On 1 ETH -> TRX, dropping the fee shifts amountOut by 1.26 TRX while the
    tolerance allows about 1e-6, so the check has six orders of magnitude of
    headroom.
    """
    amount_in = Decimal("1.00000000")
    price = Decimal("12594.59459459")
    fee = service_fee(amount_in, FEE_RATE)

    with_fee = expected_amount_out(amount_in, fee, price, 6)
    without_fee = expected_amount_out(amount_in, Decimal(0), price, 6)
    tolerance = amount_out_tolerance(amount_in - fee, 8, 6)

    assert abs(with_fee - without_fee) > tolerance * 1000


def test_price_resolution_limits_what_the_amount_out_check_can_prove():
    """A known limitation, asserted so that it stays known.

    ``price`` is reported to 8 *decimal places*, not 8 significant figures. On
    987 TRX -> ETH the rate is 0.00007595, which is only four significant
    figures, so the uncertainty it carries (9.9e-6) is larger than the fee's
    entire effect on amountOut (7.5e-6). No tolerance can be both correct and
    tight enough to detect a missing fee on that pair.

    This is why ``quote.fee`` is asserted directly and exactly in the E2E
    tests, rather than being inferred from amountOut. If someone later tightens
    ``amount_out_tolerance`` to "make the check stronger", this test fails and
    explains why that cannot work.
    """
    amount_in = Decimal("987.000000")
    price = Decimal("0.00007595")
    fee = service_fee(amount_in, FEE_RATE)

    fee_effect = abs(
        expected_amount_out(amount_in, fee, price, 8)
        - expected_amount_out(amount_in, Decimal(0), price, 8)
    )
    tolerance = amount_out_tolerance(amount_in - fee, 8, 8)

    assert fee_effect < tolerance, (
        "the price is now precise enough to detect the fee via amountOut on this "
        "pair — the limitation documented here no longer holds, so revisit it"
    )


def test_truncation_matches_the_apis_rounding_behaviour():
    """The API truncates towards zero rather than rounding half-up.

    420 TRX -> USDT: the exact product is 94.74106760..., and the API returns
    94.741067, not 94.741068.
    """
    exact = (Decimal("420.000000") - Decimal("0.042")) * Decimal("0.22559653")
    assert truncate(exact, 6) == Decimal("94.741067")
    assert round(exact, 6) == Decimal("94.741068")


def test_amounts_are_never_built_from_floats():
    """A float amount is a bug in the caller, not something to silently accept."""
    with pytest.raises(TypeError):
        to_decimal(1.1)

    assert to_decimal("0.1") + to_decimal("0.2") == to_decimal("0.3")
