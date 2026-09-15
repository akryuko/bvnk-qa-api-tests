"""A small client for the BVNK QA currency-conversion simulator.

Layers, bottom up:

* ``config``  — settings from the environment
* ``http``    — transport; returns responses, never raises on status
* ``client``  — one method per endpoint, no opinion on correctness
* ``models``  — the response contract, as pydantic models
* ``money``   — Decimal arithmetic and the tolerance policy
* ``flows``   — account setup, settlement polling, expected conversion maths

Tests import from here; nothing in this package imports pytest.
"""

from .client import SimulatorClient, quote_request
from .config import Settings
from .flows import (
    Account,
    ConversionExpectation,
    expected_conversion,
    wait_for_expiry,
    wait_for_settlement,
)
from .http import ApiResponse, HttpClient
from .models import (
    SETTLED,
    Currency,
    EchoResponse,
    HealthMetrics,
    InitResponse,
    PaymentStatus,
    Quote,
    QuoteStatus,
    Wallet,
)

__all__ = [
    "SETTLED",
    "Account",
    "ApiResponse",
    "ConversionExpectation",
    "Currency",
    "EchoResponse",
    "HealthMetrics",
    "HttpClient",
    "InitResponse",
    "PaymentStatus",
    "Quote",
    "QuoteStatus",
    "Settings",
    "SimulatorClient",
    "Wallet",
    "expected_conversion",
    "quote_request",
    "wait_for_expiry",
    "wait_for_settlement",
]
