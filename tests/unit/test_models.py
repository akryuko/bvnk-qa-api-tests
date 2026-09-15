"""Offline checks that the response models match reality.

Every model is validated against a response captured verbatim from the live
API. Because the models use ``extra="forbid"``, this catches the mistake that
would otherwise only appear as a mysterious E2E failure: a field the models
forgot, or one whose name was guessed from the OpenAPI schema rather than
observed on the wire.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from bvnk_sim import EchoResponse, HealthMetrics, InitResponse, Quote, Wallet
from bvnk_sim.models import PaymentStatus, QuoteStatus

pytestmark = pytest.mark.unit

RECORDED = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "recorded_responses.json").read_text()
)


def test_init_response_parses():
    init = InitResponse.model_validate(RECORDED["init"])
    assert init.token_type == "bearer"
    assert len(init.access_token) == 64
    assert init.expiry > 0


def test_health_response_parses():
    health = HealthMetrics.model_validate(RECORDED["health"])
    assert health.total_authenticated_requests == 109


def test_echo_response_parses():
    echo = EchoResponse.model_validate(RECORDED["echo"])
    assert echo.request_payload == {"k": 1}


def test_wallet_parses_with_amounts_as_decimals():
    wallet = Wallet.model_validate(RECORDED["wallet"])

    assert wallet.id == 19
    assert wallet.code == "ETH"
    assert wallet.status == "ACTIVE"
    assert wallet.balance == Decimal("3.70000")
    assert isinstance(wallet.balance, Decimal)
    assert wallet.currency.quantity_precision == 8
    assert wallet.currency.protocols[0].network_code == "ETHEREUM"


@pytest.mark.parametrize("key", ["quote_pending", "quote_accepted"])
def test_quote_parses_in_every_recorded_state(key):
    quote = Quote.model_validate(RECORDED[key])

    assert quote.uuid == UUID("3642869f-386c-49ea-99c5-df16c4727377")
    assert quote.from_currency == "ETH"
    assert quote.to_currency == "TRX"
    assert quote.amount_in == Decimal("0.25000000")
    assert quote.fee == Decimal("0.000025")
    assert quote.fees.value.service == quote.fee
    assert quote.acceptance_window_seconds == 20


def test_quote_states_are_read_correctly():
    pending = Quote.model_validate(RECORDED["quote_pending"])
    accepted = Quote.model_validate(RECORDED["quote_accepted"])

    assert pending.state == (QuoteStatus.PENDING, PaymentStatus.PENDING)
    assert pending.acceptance_date is None

    assert accepted.state == (QuoteStatus.ACCEPTED, PaymentStatus.PROCESSING)
    assert accepted.acceptance_date == 1789462305
    assert accepted.acceptance_date <= accepted.acceptance_expiry_date


def test_an_unexpected_field_is_rejected():
    """Proves the contract check has teeth.

    If this ever stops raising, ``extra="forbid"`` has been lost somewhere and
    the models have quietly become a subset of the API rather than a contract.
    """
    payload = dict(RECORDED["wallet"], unexpectedNewField="surprise")

    with pytest.raises(Exception) as failure:
        Wallet.model_validate(payload)
    assert "unexpectedNewField" in str(failure.value)


def test_a_missing_field_is_rejected():
    payload = {k: v for k, v in RECORDED["quote_pending"].items() if k != "amountOut"}

    with pytest.raises(Exception) as failure:
        Quote.model_validate(payload)
    assert "amountOut" in str(failure.value)
