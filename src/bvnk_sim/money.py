"""Decimal money helpers.

Every monetary value in this suite is a ``Decimal``. Floats are never used for
amounts, rates or balances: ``0.1 + 0.2 != 0.3`` in binary floating point, and
a suite that compares crypto balances with floats will eventually fail for
reasons that have nothing to do with the API.

The API returns all amounts as JSON *strings* precisely so that clients can
parse them losslessly, and this module keeps that property intact.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def to_decimal(value: object) -> Decimal:
    """Parse an API amount into a Decimal without going through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):  # pragma: no cover - guarded against on purpose
        raise TypeError(
            "Refusing to build a Decimal from a float; pass the API's string value instead"
        )
    return Decimal(str(value))


def truncate(value: Decimal, decimal_places: int) -> Decimal:
    """Truncate towards zero to ``decimal_places``.

    The simulator truncates rather than rounds when it quantises ``amountOut``
    to the destination currency's precision. Observed on 420 TRX -> USDT:
    the exact product is 94.7410676..., the API returns 94.741067.
    """
    quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def service_fee(amount_in: Decimal, fee_rate: Decimal) -> Decimal:
    """The service fee the API charges on a conversion.

    Verified against the live API: 1 ETH -> fee 0.0001, 420 TRX -> fee 0.042,
    987 TRX -> fee 0.0987, i.e. exactly ``amountIn * 0.0001``.
    """
    return amount_in * fee_rate


def expected_amount_out(
    amount_in: Decimal,
    fee: Decimal,
    price: Decimal,
    destination_precision: int,
) -> Decimal:
    """Recompute ``amountOut`` from the other values the quote reports.

    The fee is taken off the input, and the remainder is converted at the
    quoted price and truncated to the destination currency's precision.
    """
    return truncate((amount_in - fee) * price, destination_precision)


def amount_out_tolerance(
    net_amount_in: Decimal,
    price_precision: int,
    destination_precision: int,
) -> Decimal:
    """How far ``amountOut`` may legitimately differ from our recomputation.

    This is derived, not guessed. Two known sources of error:

    1. ``price`` is reported quantised to ``price_precision`` decimal places,
       so the rate actually used internally may differ from the one we can see
       by up to one unit in its last place. Multiplied by the net input amount
       that is ``net_amount_in * 10**-price_precision``.
    2. ``amountOut`` is truncated to the destination currency's precision,
       worth one more unit in its last place.

    Worth checking against reality: on 987 TRX -> ETH the price is 0.00007595
    (8 dp), so term 1 allows 9.87e-6 while the observed difference was 6.3e-7.

    Note the limit of this check. ``price`` is quantised to 8 *decimal places*,
    not 8 significant figures, so a small rate carries proportionally more
    uncertainty. At 0.00007595 the allowance (9.9e-6) is larger than the fee's
    whole effect on amountOut (7.5e-6), meaning this comparison cannot detect a
    missing fee on that pair no matter how it is written. That is why the fee
    itself is asserted directly against ``quote.fee``, and this function only
    cross-checks that amountOut is consistent with the other reported values.
    ``tests/unit/test_money.py`` pins both facts down.
    """
    price_error = net_amount_in * Decimal(1).scaleb(-price_precision)
    truncation_error = Decimal(1).scaleb(-destination_precision)
    return price_error + truncation_error
