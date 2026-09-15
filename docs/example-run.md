# Example run

A full run against the live simulator at `https://qa-simulator.shared.bvnk.com`,
2026-09-16, Windows 11 / Python 3.11.1.

The self-contained HTML report from this run is [`example-run.html`](example-run.html) —
open it in a browser for per-test detail and captured request/response logs.
[`example-run-junit.xml`](example-run-junit.xml) is the same run in JUnit format, for CI
consumption.

```
$ pytest
================================================= test session starts =================================================
platform win32 -- Python 3.11.1, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\users\aliaksandr\pycharmprojects\bvnk-qa-api-tests
configfile: pyproject.toml
testpaths: tests
plugins: html-4.2.0, metadata-3.1.1
collected 81 items

tests\contract\test_account_isolation.py ....                                                                    [  4%]
tests\contract\test_auth.py ..................                                                                   [ 27%]
tests\contract\test_echo_and_health.py ........                                                                  [ 37%]
tests\contract\test_wallets.py .......                                                                           [ 45%]
tests\e2e\test_conversions.py ......                                                                             [ 53%]
tests\e2e\test_quote_lifecycle.py .....                                                                          [ 59%]
tests\negative\test_quote_validation.py .............                                                            [ 75%]
tests\unit\test_models.py .........                                                                              [ 86%]
tests\unit\test_money.py .......                                                                                 [ 95%]
tests\unit\test_redaction.py ....                                                                                [100%]

------------- generated xml file: C:\users\aliaksandr\pycharmprojects\bvnk-qa-api-tests\reports\junit.xml -------------
------ Generated html report: file:///C:/users/aliaksandr/pycharmprojects/bvnk-qa-api-tests/reports/report.html -------
============================================ 81 passed in 68.82s (0:01:08) ============================================
```

## Breakdown

| Suite | Tests | What it covers |
|---|---:|---|
| `e2e/test_conversions.py` | 6 | The three headline conversions, each checked end to end and then re-read for immutability |
| `e2e/test_quote_lifecycle.py` | 5 | Expiry, double acceptance, no fund movement on quoting, quote listing, reverse quoting |
| `contract/test_auth.py` | 18 | Seven protected endpoints against missing, unknown and malformed credentials |
| `contract/test_account_isolation.py` | 4 | Another account's wallets and quotes are not readable, usable or acceptable |
| `contract/test_wallets.py` | 7 | Wallet content, currency metadata, pagination, 404 and 422 paths |
| `contract/test_echo_and_health.py` | 8 | Payload echo across five body types, token expiry cross-check, health metrics |
| `negative/test_quote_validation.py` | 13 | Missing fields, amount rules, insufficient funds, currency mismatch, malformed UUIDs |
| `unit/test_money.py` | 7 | Fee and truncation arithmetic replayed against three real conversions |
| `unit/test_models.py` | 9 | Response models validated against recorded payloads |
| `unit/test_redaction.py` | 4 | Access tokens are masked before anything is logged or reported |

Of the 69 seconds, about 22 are `test_quote_expires_after_the_documented_window_and_cannot_be_accepted`
waiting out a real quote expiry. `pytest -m "not slow"` skips it.

The captured request and response logs in the HTML report have access tokens masked by
`http.redact_secrets`, so the report is safe to commit and share.
