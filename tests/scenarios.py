"""Conversion scenarios under test.

Separated from the test body so that adding a currency pair is a one-line data
change rather than a copied-and-pasted test function.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Conversion:
    source: str
    target: str
    amount: Decimal

    def __str__(self) -> str:
        return f"{self.amount}-{self.source}-to-{self.target}"


CORE_CONVERSIONS: list[Conversion] = [
    Conversion(source="ETH", target="TRX", amount=Decimal("1")),
    Conversion(source="TRX", target="USDT", amount=Decimal("420")),
    Conversion(source="TRX", target="ETH", amount=Decimal("987")),
]
