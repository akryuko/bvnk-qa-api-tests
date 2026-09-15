# BVNK QA Simulator — API test suite

End-to-end and contract tests for a crypto currency-conversion API — the publicly
reachable simulator at `https://qa-simulator.shared.bvnk.com`, which mints throwaway
funded accounts on demand and prices live trades between ETH, TRX and USDT.

81 tests: 11 end-to-end flows covering three conversion scenarios and the quote
lifecycle, 37 contract checks, 13 rejection paths, and 20 offline checks of the money
arithmetic, response models and log redaction.

## Quick start

Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest
```

No configuration is needed — the suite points at the live simulator by default and
creates its own throwaway accounts. A full run takes about 70 seconds, roughly a third
of which is the single test that waits out a quote expiry.

```bash
pytest -m e2e                  # just the conversion journeys
pytest -m "not slow"           # skip the one test that waits out a 20s quote expiry
pytest -m unit                 # offline only, no network
BVNK_BASE_URL=http://localhost:8000 pytest    # point at another environment
```

Every run writes `reports/report.html` (self-contained, open it in a browser) and
`reports/junit.xml`. Those are build output and gitignored; a committed sample of a full
passing run lives in [`docs/example-run.md`](docs/example-run.md).

## Headline scenarios

| Scenario | Test |
|---|---|
| Convert 1 ETH for TRX | `test_conversion_settles_and_moves_exactly_the_quoted_amounts[1-ETH-to-TRX]` |
| Convert 420 TRX for USDT | `test_conversion_settles_and_moves_exactly_the_quoted_amounts[420-TRX-to-USDT]` |
| Convert 987 TRX for ETH | `test_conversion_settles_and_moves_exactly_the_quoted_amounts[987-TRX-to-ETH]` |
| A quote goes stale | `test_quote_expires_after_the_documented_window_and_cannot_be_accepted` |
| A quote is used twice | `test_quote_cannot_be_accepted_twice` |

The last two are there because they are the failure modes that cost real money: a quote
honoured after its price is stale, and a conversion applied twice.

## What each conversion test checks

Each of the three runs the full journey and asserts at every step, not just at the end.

1. **Preconditions** — the source wallet exists, is `ACTIVE`, and holds enough. A
   missing precondition should say so, not surface as a confusing `412` later.
2. **The quote** — `201`, the whole body validated against a schema, status
   `PENDING/PENDING`, currencies and amount echoed back, a positive price, and a
   20-second acceptance window.
3. **The money** — the fee is exactly 0.01% of `amountIn`, `fees.value.service` agrees
   with `fee`, the processing fee is zero, and `amountOut` is consistent with
   `(amountIn − fee) × price`.
4. **Acceptance** — `200`, status moves to `ACCEPTED`, `acceptanceDate` lands inside the
   window, and none of the amounts are re-priced on acceptance.
5. **Settlement** — polled until `PAYMENT_OUT_PROCESSED/SUCCESS`.
6. **Balances** — the source wallet is debited *exactly* `amountIn`, the destination
   credited *exactly* `amountOut`, and the third wallet is untouched.

## How it is put together

```
src/bvnk_sim/          the client library — no pytest imports anywhere in here
  config.py            settings from the environment, with working defaults
  http.py              transport; returns responses, never raises on status
  client.py            one method per endpoint, no opinion on correctness
  models.py            the response contract as pydantic models
  money.py             Decimal arithmetic and the tolerance policy
  flows.py             account setup, settlement polling, expected conversion maths
tests/
  e2e/                 full conversion journeys
  contract/            schemas, status codes, auth, isolation
  negative/            input validation and rejection paths
  unit/                offline checks of the maths, the models and token redaction
  fixtures/            responses captured verbatim from the live API
  scenarios.py         the conversion table the E2E tests are parametrised from
docs/                  a committed sample run: console log, HTML report, JUnit XML
```

The split that matters is between the client and the tests. The client knows *what the
API looks like*; the tests know *what is correct*. Adding an endpoint means one method
in `client.py` and one model in `models.py`, and every existing test keeps working.

## Design decisions

Each of these came out of watching the API behave, and each one changes whether the
suite is trustworthy.

**Every test gets its own account.** `/init` is cheap and returns a fresh account with
funded wallets, so each test creates one. A shared account would mean tests observing
each other's balances, an ordering dependency between them, and no way to parallelise.

**Wallet IDs are discovered, never hardcoded.** The simulator allocates wallet IDs
globally — the first account gets 1–3, the next 4–6, and so on. A suite that hardcodes
`fromWallet: 1` passes on a fresh database and fails forever after.

**State changes are polled for, never slept on.** Two places where this matters.
Accepting a quote returns `200` with `ACCEPTED/PROCESSING` and *the balances have not
moved yet*; they land asynchronously, usually under a second but sometimes longer. And a
quote goes on reporting `PENDING` for a second or three after the `acceptanceExpiryDate`
the API itself published — measured at 2.8s, and a 2-second grace period was enough to
make the expiry test fail intermittently before it was rewritten. `wait_for_settlement`
and `wait_for_expiry` both wait for the observable transition, with a timeout, which is
deterministic where a computed `sleep` is a race.

**Nothing is asserted against a fixed exchange rate.** Rates fluctuate: ETH→TRX was
observed at 12594.59, 12026.32, 12702.70 and 13083.33 within two minutes. Every
expectation is recomputed from what the quote itself returned.

**Amounts are `Decimal` everywhere, and balances are compared exactly.** Settlement
moves precisely `amountIn` and `amountOut`, so those comparisons are exact. Two traps
here: `0.1 + 0.2 != 0.3` in float, and the API changes a balance's *string* precision
after a trade — `"46500.00"` becomes `"46080.000000"` — so string comparison would fail
on numerically identical values. `money.to_decimal` refuses to build an amount from a
float at all.

**The `amountOut` tolerance is derived, not guessed.** `price` is reported quantised to
8 decimal places, so recomputing `amountOut` from it cannot be exact. The tolerance is
the sum of the two real error sources: the price's own last-place uncertainty scaled by
the net input, plus one unit of the destination currency's precision. On 987 TRX→ETH the
recomputation is off by 6.3e-7 and the bound allows 9.9e-6.

That bound has a limit worth stating plainly. Because `price` is quantised to 8 *decimal
places* rather than 8 *significant figures*, a small rate like `0.00007595` carries more
uncertainty (9.9e-6) than the fee's entire effect on `amountOut` (7.5e-6). On that pair
no tolerance can be both correct and tight enough to detect a missing fee. This is why
the fee is asserted directly and exactly against `quote.fee` rather than inferred from
`amountOut`. Both facts are pinned down in `tests/unit/test_money.py` so that nobody
"strengthens" the tolerance later without discovering why it cannot work.

**Responses are validated as whole objects.** Indexing into a dict checks one field on
one call; validating against a model turns every request into a contract check. The
models use `extra="forbid"`, so an added field fails loudly rather than passing silently
— a deliberate choice for a contract suite, and a one-line change to `"ignore"` if you
would rather tolerate additive changes.

**The HTTP layer never raises on status.** Every call returns an `ApiResponse` and the
test asserts the status it expects, which is what makes the 13 negative tests read the
same way as the happy path. `ApiResponse.describe()` puts the method, URL, status,
timing and both bodies into the failure message.

**Tokens are scrubbed from response bodies, not just from headers.** `GET /init`
returns a live bearer token *in its body*, and every body is logged and embedded in the
HTML report — so redacting the `Authorization` header alone would still put working
credentials into a file that gets committed and shared. `http.redact_secrets` masks
anything token-shaped wherever it appears, including a token echoed back by `/echo` or
quoted inside an error, and `tests/unit/test_redaction.py` fails if that protection is
ever removed.

**The suite fails fast when the API is down.** A session fixture checks `/health` once
and exits with a single clear message rather than producing dozens of confusing
failures. Not a hypothetical concern — see the note on the endpoint at the bottom.

## Findings

Behaviour I ran into that looks unintended. None of these break the conversion flows,
so none of them fail the suite; they are written up here rather than as failing tests.
All are reproducible against the live simulator.

| # | Behaviour | Expected | Actual |
|---|---|---|---|
| 1 | `POST /api/v1/quote` with `amountIn: -5` | rejected | `201`, quote for `amountOut: -60125.565789` |
| 2 | `POST /api/v1/quote` with `amountIn: 0` | a validation error about the amount | `400 One of 'amountIn' or 'amountOut' must be specified but not both.` — a falsy check treats `0` as absent |
| 3 | Same-currency quote, ETH→ETH | rejected | `201` at price 1.0, `amountOut` 0.9999 — the caller loses 0.01% for nothing |
| 4 | `payInMethod: "bank"` (not a supported method) | rejected | `201`, the value is not validated |
| 5 | `useMaximum: true` with no amount | quote for the full balance | `400`, the documented flag appears unimplemented |
| 6 | `GET /api/wallet?offset=-1` | `422` | `200` |
| 7 | `amountInNet` on any quote | `amountIn − fee` | equal to `amountIn`, so net and gross are identical despite a non-zero fee |
| 8 | `paymentReceiptDate` after `paymentStatus: SUCCESS` | a timestamp | `null` |
| 9 | Reading a quote just after its `acceptanceExpiryDate` | `EXPIRED` | `PENDING` for ~2.8s longer, so the published deadline and the reported status disagree |

Worth flagging separately, because it is a design question rather than a bug: **a
pending quote does not reserve funds.** `available` is unchanged while a quote is
`PENDING`, so an account can hold several open quotes worth more than it owns. Whether
they can all then be accepted is worth a conversation.
`test_creating_a_quote_does_not_move_funds` pins the current behaviour down.

Two observations that are not defects but shaped the code:

- The API mixes naming conventions. `/init`, `/echo` and `/health` return snake_case;
  wallets and quotes return camelCase. `models.py` has two base classes as a result.
- `GET /api/v1/quote` (list all quotes) exists and works, but is easy to miss — it is
  in the OpenAPI schema and nowhere in the prose. It is covered here.

Cross-account isolation, which is where I expected to find something given the
guessable wallet IDs, is solid: another account's wallet, quote read, and quote
acceptance all return `404` rather than `403`, correctly declining to confirm that the
ID exists. Four tests in `tests/contract/test_account_isolation.py` cover it.

## What I would add next

- **CI.** A GitHub Actions workflow running the suite on push and publishing the HTML
  report as an artifact. Left out deliberately to keep the repo small.
- **Parallel execution.** `pytest-xdist` would work today without changes — the
  per-test account isolation was designed for it — but it is not worth the dependency
  at this size.
- **A recorded-response mode.** The captured fixtures in `tests/fixtures/` already
  support the offline model tests; extending them to stub the whole API would let the
  suite run in environments with no egress.
- **The open question behind finding 9.** A quote still reads as `PENDING` for a couple
  of seconds after its stated expiry. Whether it can also still be *accepted* in that
  window is the thing that decides whether finding 9 is a cosmetic status lag or an
  exchange honouring a price it has already declared dead. The test here waits for the
  status to flip before attempting acceptance, so it does not answer that question; the
  test that would is an accept attempt timed to land inside the gap.
- **Load and concurrency.** Two clients accepting the same quote simultaneously, and
  several open quotes that together exceed the balance, are the interesting races —
  particularly given that pending quotes reserve nothing, as noted above.

## A note on the base URL

This simulator has moved hosts at least once: an earlier deployment
(`bvnksimulator.pythonanywhere.com`) stopped serving entirely, returning the hosting
provider's default placeholder on every path. That is why the base URL is configuration
rather than a constant — pointing the suite at a different deployment is one environment
variable, not a code change — and why a session fixture checks `/health` before anything
else, so an unreachable host produces one clear message instead of eighty confusing
failures.
