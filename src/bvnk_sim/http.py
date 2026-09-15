"""Thin HTTP transport layer.

Two design decisions worth stating:

*Nothing raises on a non-2xx status.* Every call returns an ``ApiResponse`` and
the test asserts the status it expects. A client that raised on 4xx would make
the negative tests — half the value of this suite — awkward to write, and would
hide the response body exactly when it is most interesting.

*Failure messages carry the whole request.* ``ApiResponse.describe()`` renders
the method, URL, status, duration and body, so a failed assertion tells you
what the API actually did without a rerun under a debugger.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger("bvnk.http")

#: Bodies longer than this are truncated in failure messages and logs.
_MAX_BODY_CHARS = 2000


#: Any 64 hex character run is an access token from /init. Matching on shape
#: rather than on the surrounding key catches it wherever it appears — in the
#: /init response body, echoed back by /echo, or quoted inside an error.
_TOKEN_PATTERN = re.compile(r"\b[0-9a-fA-F]{64}\b")


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Never let a bearer token reach a log file or an HTML report."""
    safe = dict(headers)
    if "Authorization" in safe:
        value = safe["Authorization"]
        safe["Authorization"] = f"{value[:13]}...<redacted>" if len(value) > 13 else "<redacted>"
    return safe


def redact_secrets(text: str) -> str:
    """Mask access tokens in a response body before it is logged or reported.

    Redacting the Authorization *header* is not enough: ``GET /init`` returns a
    live token in its response body, and every response body is logged and
    embedded in the HTML report. Without this, that report is a committed file
    full of working credentials.

    These particular tokens are throwaway ones for simulated accounts, so the
    risk is low. Publishing credentials because nobody thought about where the
    logs end up is the habit worth not having.
    """
    return _TOKEN_PATTERN.sub("<redacted-token>", text)


def _clip(text: str) -> str:
    safe = redact_secrets(text)
    return safe if len(safe) <= _MAX_BODY_CHARS else safe[:_MAX_BODY_CHARS] + " ...<truncated>"


@dataclass(frozen=True)
class ApiResponse:
    """An HTTP response, plus enough request context to debug a failure."""

    method: str
    url: str
    status_code: int
    elapsed_ms: float
    headers: Mapping[str, str]
    text: str
    json: Any | None
    request_body: Any | None = None

    @property
    def detail(self) -> str | None:
        """FastAPI puts its error message in ``detail``; None if absent."""
        if isinstance(self.json, dict):
            value = self.json.get("detail")
            if isinstance(value, str):
                return value
        return None

    def describe(self) -> str:
        lines = [
            "",
            f"  {self.method} {self.url}",
            f"  -> {self.status_code} in {self.elapsed_ms:.0f}ms",
        ]
        if self.request_body is not None:
            lines.append(f"  request body: {_clip(json.dumps(self.request_body, default=str))}")
        lines.append(f"  response body: {_clip(self.text)}")
        return "\n".join(lines)


class HttpClient:
    """A ``requests`` session bound to one base URL and one bearer token."""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        token: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = token
        self.session = session or requests.Session()

    def with_token(self, token: str | None) -> HttpClient:
        """A client for the same host with different credentials.

        Returns a new instance sharing the underlying connection pool, so
        swapping credentials mid-test costs nothing.
        """
        return HttpClient(self.base_url, self.timeout, token, self.session)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
        authenticate: bool = True,
    ) -> ApiResponse:
        url = f"{self.base_url}{path}"
        final_headers: dict[str, str] = {"Accept": "application/json"}
        if authenticate and self.token:
            final_headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            final_headers["Content-Type"] = "application/json"
        if headers:
            final_headers.update(headers)

        LOGGER.info(
            "%s %s params=%s headers=%s", method, url, params, _redact_headers(final_headers)
        )
        response = self.session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=final_headers,
            timeout=self.timeout,
        )

        try:
            payload = response.json()
        except ValueError:
            payload = None

        LOGGER.info(
            "%s %s -> %s in %.0fms | %s",
            method,
            url,
            response.status_code,
            response.elapsed.total_seconds() * 1000,
            _clip(response.text),
        )

        return ApiResponse(
            method=method,
            url=url,
            status_code=response.status_code,
            elapsed_ms=response.elapsed.total_seconds() * 1000,
            headers=response.headers,
            text=response.text,
            json=payload,
            request_body=json_body,
        )
