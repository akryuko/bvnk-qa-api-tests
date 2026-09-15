"""Shared fixtures.

The important decision here is the scope of ``account``: every test that needs
funds gets its **own** freshly initialised account. ``/init`` is cheap, and the
alternative — one shared account for the whole run — would mean tests observing
each other's balance changes, an ordering dependency between them, and no way
to run the suite in parallel. Isolation costs one HTTP call per test and buys
all of that back.
"""

from __future__ import annotations

import logging

import pytest

from bvnk_sim import Account, HttpClient, Settings, SimulatorClient


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def http(settings: Settings):
    client = HttpClient(base_url=settings.base_url, timeout=settings.request_timeout)
    yield client
    client.session.close()


@pytest.fixture(scope="session")
def api_is_reachable(http: HttpClient, settings: Settings) -> None:
    """Fail the run once, clearly, if the API is not up.

    Without this the suite reports two dozen confusing failures when the real
    problem is that the host is unreachable — which is exactly what happened
    with the simulator's previous URL.

    Requested by ``anonymous_client`` rather than autouse, so the offline unit
    tests still run with no network at all.
    """
    try:
        response = http.request("GET", "/health", authenticate=False)
    except Exception as exc:
        pytest.exit(f"Cannot reach {settings.base_url}: {exc}", returncode=3)

    if response.status_code != 200:
        pytest.exit(
            f"{settings.base_url}/health returned {response.status_code}, expected 200."
            f"{response.describe()}",
            returncode=3,
        )
    logging.getLogger("bvnk").info("API reachable at %s", settings.base_url)


@pytest.fixture(scope="session")
def anonymous_client(http: HttpClient, api_is_reachable: None) -> SimulatorClient:
    """A client with no credentials — used for /init, /health and auth tests."""
    return SimulatorClient(http)


@pytest.fixture
def account(anonymous_client: SimulatorClient) -> Account:
    """A fresh account with funded ETH, TRX and USDT wallets."""
    return Account.create(anonymous_client)


@pytest.fixture
def other_account(anonymous_client: SimulatorClient) -> Account:
    """A second, unrelated account — for cross-account isolation tests."""
    return Account.create(anonymous_client)


def pytest_configure(config: pytest.Config) -> None:
    """Record the environment under test in the HTML report header."""
    try:
        from pytest_metadata.plugin import metadata_key

        config.stash[metadata_key]["Base URL"] = Settings.from_env().base_url
    except Exception as exc:
        logging.getLogger("bvnk").debug("could not add report metadata: %s", exc)
