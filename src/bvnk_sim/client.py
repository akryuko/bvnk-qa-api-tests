"""One method per API endpoint.

The client knows the shape of the API — paths, verbs, query parameters — and
nothing about what is correct. Every method returns an ``ApiResponse``; the
tests decide what a good answer looks like. That split is what lets the same
client serve both the happy-path E2E flows and the negative tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

from .http import ApiResponse, HttpClient


class SimulatorClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    # -- credentials -------------------------------------------------------

    def as_token(self, token: str | None) -> SimulatorClient:
        """A client authenticating with a different token.

        Passing ``None`` gives one that sends no Authorization header at all.
        """
        return SimulatorClient(self.http.with_token(token))

    # -- unauthenticated ---------------------------------------------------

    def init_account(self) -> ApiResponse:
        """GET /init — mint a fresh account and a 24h bearer token."""
        return self.http.request("GET", "/init", authenticate=False)

    def health(self) -> ApiResponse:
        """GET /health — uptime and request counters."""
        return self.http.request("GET", "/health", authenticate=False)

    # -- authenticated -----------------------------------------------------

    def echo(self, payload: Any, headers: Mapping[str, str] | None = None) -> ApiResponse:
        """POST /echo — confirms auth and reflects the request body back."""
        return self.http.request("POST", "/echo", json_body=payload, headers=headers)

    def list_wallets(
        self,
        offset: int | None = None,
        max_count: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        """GET /api/wallet — the account's wallets, paginated."""
        params: dict[str, Any] = {}
        if offset is not None:
            params["offset"] = offset
        if max_count is not None:
            params["max_count"] = max_count
        return self.http.request("GET", "/api/wallet", params=params or None, headers=headers)

    def get_wallet(self, wallet_id: int | str) -> ApiResponse:
        """GET /api/wallet/{wallet_id} — a single wallet."""
        return self.http.request("GET", f"/api/wallet/{wallet_id}")

    def list_quotes(self) -> ApiResponse:
        """GET /api/v1/quote — every quote this account has created."""
        return self.http.request("GET", "/api/v1/quote")

    def create_quote(self, body: Mapping[str, Any]) -> ApiResponse:
        """POST /api/v1/quote — price a conversion. 201 on success."""
        return self.http.request("POST", "/api/v1/quote", json_body=dict(body))

    def get_quote(self, quote_uuid: UUID | str) -> ApiResponse:
        """GET /api/v1/quote/{uuid} — re-read a quote and its current status."""
        return self.http.request("GET", f"/api/v1/quote/{quote_uuid}")

    def accept_quote(self, quote_uuid: UUID | str) -> ApiResponse:
        """PUT /api/v1/quote/accept/{uuid} — execute the conversion."""
        return self.http.request("PUT", f"/api/v1/quote/accept/{quote_uuid}")


def quote_request(
    *,
    source_currency: str,
    target_currency: str,
    source_wallet_id: int,
    target_wallet_id: int,
    amount_in: Decimal | str | int | None = None,
    amount_out: Decimal | str | int | None = None,
    reference: str = "qa-suite",
    **overrides: Any,
) -> dict[str, Any]:
    """Build a create-quote body.

    A plain dict rather than a model, because the negative tests need to send
    bodies the API should reject — a typed request object would stop them at
    the client instead of at the API, which is the thing under test.

    Amounts are serialised as strings: the API accepts both a JSON number and a
    string, and the string form is the only one that survives a round trip
    without float rounding.
    """
    body: dict[str, Any] = {
        "from": source_currency,
        "to": target_currency,
        "fromWallet": source_wallet_id,
        "toWallet": target_wallet_id,
        "useMaximum": False,
        "useMinimum": False,
        "reference": reference,
        "payInMethod": "wallet",
        "payOutMethod": "wallet",
    }
    if amount_in is not None:
        body["amountIn"] = str(amount_in)
    if amount_out is not None:
        body["amountOut"] = str(amount_out)
    body.update(overrides)
    return body
