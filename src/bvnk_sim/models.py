"""Pydantic models describing the API's response contract.

Why model the responses at all, when a test could just index into a dict?
Because ``response.json["amountOut"]`` only checks that one field on one call.
Validating the whole payload against a model turns every request in the suite
into a contract check: a renamed field, a changed type, a null where a value
used to be, or a new undocumented field all fail immediately and point at the
exact attribute, instead of surfacing later as a confusing assertion error.

Two deliberate choices:

* ``extra="forbid"`` — an unexpected field is a contract change and the suite
  says so. If BVNK adds a field intentionally, the fix is one line here, and
  the failure has told you the API moved. Relax it to ``"ignore"`` if you would
  rather the suite tolerate additive changes.
* Amounts are ``Decimal``. See ``money.py`` for why never float.

The API mixes naming conventions: ``/init``, ``/echo`` and ``/health`` return
snake_case, while the wallet and quote payloads are camelCase. Rather than
pretend otherwise, there are two base models.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SnakeModel(BaseModel):
    """Base for the snake_case endpoints (/init, /echo, /health)."""

    model_config = ConfigDict(extra="forbid")


class CamelModel(BaseModel):
    """Base for the camelCase endpoints (wallets, quotes)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# --------------------------------------------------------------------------
# Status vocabulary
#
# Kept as plain constants rather than an Enum on the model: an unknown status
# from the API should fail an explicit assertion with a readable message, not
# blow up during response parsing.
# --------------------------------------------------------------------------


class QuoteStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    PAYMENT_OUT_PROCESSED = "PAYMENT_OUT_PROCESSED"


class PaymentStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    EXPIRED = "EXPIRED"


#: Statuses that mean the conversion is finished and balances have moved.
SETTLED = (QuoteStatus.PAYMENT_OUT_PROCESSED, PaymentStatus.SUCCESS)

#: Payment statuses that mean settlement is still in flight.
IN_FLIGHT = (PaymentStatus.PENDING, PaymentStatus.PROCESSING)


# --------------------------------------------------------------------------
# /init, /echo, /health
# --------------------------------------------------------------------------


class InitResponse(SnakeModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - a scheme name, not a secret
    expiry: int  # epoch seconds


class EchoResponse(SnakeModel):
    auth_token_expiry_time: str  # "YYYY-MM-DD HH:MM:SS"
    request_payload: Any


class HealthMetrics(SnakeModel):
    uptime: str
    approximate_db_size: str
    total_authenticated_requests: int


# --------------------------------------------------------------------------
# Wallets
# --------------------------------------------------------------------------


class Protocol(CamelModel):
    code: str
    network: str
    network_code: str


class CurrencyOptions(CamelModel):
    address: str
    explorer: str
    transaction: str
    confirmations: int


class Currency(CamelModel):
    id: int
    code: str
    fiat: bool
    icon: str
    name: str
    withdrawal_parameters: list[Any]
    options: CurrencyOptions
    withdrawal_fee: Decimal
    deposit_fee: Decimal
    supports_deposits: bool
    supports_withdrawals: bool
    quantity_precision: int
    price_precision: int
    protocols: list[Protocol]


class Wallet(CamelModel):
    id: int
    description: str
    currency: Currency
    supports_withdrawals: bool = False
    supports_deposits: bool = False
    custodian_wallet: Any | None = None
    supports_third_party: bool = False
    supports_internal_bvnk_network_transfers: bool = False
    partner: Any | None = None
    is_emoney: bool = False
    supported_transfer_destinations: list[Any] = Field(default_factory=list)
    protocol: str
    address: str
    lookup: Any | None = None
    balance: Decimal
    available: Decimal
    withdrawal_fee: Decimal
    deposit_fee: Decimal
    converted_available: Decimal
    alternatives: list[Any]
    approx_available: Decimal
    approx_balance: Decimal
    approx_converted_available: Decimal
    lsid: str
    status: str

    @property
    def code(self) -> str:
        """Convenience accessor for the wallet's currency code."""
        return self.currency.code


# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------


class FeeValue(CamelModel):
    service: Decimal
    processing: Decimal


class Fees(CamelModel):
    percentage: FeeValue
    value: FeeValue


class AccountMethod(CamelModel):
    id: int
    display: Any | None = None


class PayInMethod(CamelModel):
    id: int
    code: str = "wallet"
    settlement_currency: str
    requested_currency: Any | None = None
    estimated_exchange_rate: Any | None = None
    account_methods: list[Any] = Field(default_factory=list)


class PayOutMethod(CamelModel):
    id: int
    code: str = "wallet"
    currency: str
    account_methods: list[AccountMethod]


class MethodRef(CamelModel):
    id: int
    display: Any | None = None


class Quote(CamelModel):
    id: int
    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    amount_in: Decimal
    amount_due: Decimal
    amount_out: Decimal
    price: Decimal
    quote_status: str
    payment_status: str
    acceptance_expiry_date: int  # epoch seconds
    acceptance_date: int | None = None
    payment_expiry_date: int
    payment_receipt_date: int | None = None
    pay_in_legs: list[Any]
    pay_in_method: PayInMethod
    pay_out_method: PayOutMethod
    uuid: UUID
    pay_out_instruction: Any | None = None
    pay_in_instruction: Any | None = None
    use_pay_in_method: MethodRef
    use_pay_out_method: MethodRef
    fee: Decimal
    processing_fee: Decimal
    type: str
    net_price: Decimal
    gross_price: Decimal
    amount_in_gross: Decimal
    amount_in_net: Decimal
    fees: Fees
    date_created: int
    last_updated: int

    @property
    def state(self) -> tuple[str, str]:
        """(quoteStatus, paymentStatus) — handy for a single readable assert."""
        return self.quote_status, self.payment_status

    @property
    def acceptance_window_seconds(self) -> int:
        return self.acceptance_expiry_date - self.date_created
