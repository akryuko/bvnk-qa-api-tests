"""Runtime configuration for the test suite.

Everything an environment might need to change lives here rather than being
scattered through the tests: the base URL, timeouts, and the two business rules
the simulator documents (a 0.01% service fee and a 20 second quote acceptance
window).

The business rules are configuration rather than hardcoded literals on purpose.
They are the *expected* values the tests assert against, so if BVNK changes the
fee, exactly one line changes and every assertion follows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

try:  # optional convenience, the suite works fine without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


DEFAULT_BASE_URL = "https://qa-simulator.shared.bvnk.com"


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    """Immutable settings, built once per test session."""

    #: Root of the API under test. Override with BVNK_BASE_URL.
    base_url: str = DEFAULT_BASE_URL

    #: Per-request socket timeout, seconds.
    request_timeout: float = 15.0

    #: Service fee charged on every conversion, as a fraction of amountIn.
    #: The API reports this as fees.percentage.service = "0.01", meaning 0.01%.
    service_fee_rate: Decimal = Decimal("0.0001")

    #: Seconds a PENDING quote may be accepted for, per the API's documentation.
    acceptance_window_seconds: int = 20

    #: Settlement is asynchronous: accept returns ACCEPTED/PROCESSING and the
    #: balances move a moment later. How long to wait for a terminal status.
    settlement_timeout: float = 30.0
    settlement_poll_interval: float = 0.25

    #: How long to keep polling past a quote's acceptanceExpiryDate before
    #: concluding it never expired. The API goes on reporting PENDING for a
    #: second or three after the deadline it published, so the transition is
    #: waited for rather than assumed. See flows.wait_for_expiry.
    expiry_timeout: float = 15.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            base_url=_env("BVNK_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            request_timeout=float(_env("BVNK_REQUEST_TIMEOUT", "15")),
            service_fee_rate=Decimal(_env("BVNK_SERVICE_FEE_RATE", "0.0001")),
            acceptance_window_seconds=int(_env("BVNK_ACCEPTANCE_WINDOW", "20")),
            settlement_timeout=float(_env("BVNK_SETTLEMENT_TIMEOUT", "30")),
            settlement_poll_interval=float(_env("BVNK_SETTLEMENT_POLL_INTERVAL", "0.25")),
            expiry_timeout=float(_env("BVNK_EXPIRY_TIMEOUT", "15")),
        )
