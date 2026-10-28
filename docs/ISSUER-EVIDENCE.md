# Dated official issuer evidence (BBCA only)

`tradingagents.dataflows.vendors.issuer_evidence.get_issuer_fundamentals(ticker, as_of_date)` returns a text excerpt for **company-overview enrichment through `get_fundamentals` only**. It is not a replacement for historical fundamentals coverage, and does not expand coverage to other IDX issuers.

## Source and availability convention

Official BCA press release:

https://bca.co.id/id/tentang-bca/media-riset/pressroom/siaran-pers/2026/07/29/07/10/pertama-kali-kredit-tembus-rp1000-triliun-bca-komit-dukung-perekonomian-nasional

The actual page was retrieved through `web_extract` during implementation. Its displayed date and URL path indicate **2026-07-29**; its body begins **Jakarta, 28 Juli 2026**. These are conflicting source date signals, **not verified first publication** or proof from an independent historical archive. The allowlisted asset uses a deliberately conservative `available_after: 2026-07-30`, interpreted as usable **from that Jakarta calendar date inclusive** (`Asia/Jakarta`). Before that date the provider raises `VendorUnavailableError` and includes no source figures in its error.

The returned `availability_basis` explicitly preserves this limitation. Do not represent the convention as a verified historical publication timestamp.

## Contract and limits

- Supported inputs: `BBCA` and `BBCA.JK`, case insensitive. No other issuer is covered, including `BBRI`/`BBRI.JK`.
- Require an explicit, valid, canonical `YYYY-MM-DD` analysis date. Missing/malformed dates fail closed with `VendorUnavailableError`; there is no implicit current-date fallback.
- Return only five curated exact source sentences, retaining Indonesian punctuation and units, plus source URL, source type, availability boundary and basis. The checked-in response is below 5,000 characters.
- The quoted `Rp29,5 triliun` is explicitly total profit of BCA and subsidiaries for semester I 2026. It is not relabeled annual profit, quarterly profit, attributable net income, or EPS. No numeric conversion, extrapolation or valuation reconstruction is performed.
- This is a press release, **not a financial statement**. It must not service annual/quarterly balance-sheet, income-statement or cash-flow APIs.
- No historical P/E, EPS, market cap, price-to-book or other Yahoo snapshot is reconstructed. Existing Yahoo historical guards must remain unchanged.
- No network calls occur at runtime; no URL argument, arbitrary fetch, API key or LLM is used. Source data comes exclusively from the checked-in `assets/issuer_evidence.json` allowlist. Updates require source verification and review, not automatic scraping.
- This provider exposes no statement functions. Router registration is separate and must be restricted to the company-overview `get_fundamentals` method; do not install it as a general replacement vendor.

## Example

```python
from tradingagents.dataflows.vendors.issuer_evidence import get_issuer_fundamentals

text = get_issuer_fundamentals("BBCA.JK", "2026-07-30")
# Contains the exact official excerpts and their provenance/date caveat.
# "2026-07-29" instead raises VendorUnavailableError without financial figures.
```

## Offline verification

```sh
/root/projects/TradingAgents/.venv/bin/python -m pytest tests/test_issuer_evidence.py -q
```

Tests cover boundary inclusion, earlier-date non-disclosure, unsupported issuers and URL inputs, ticker aliases, invalid/missing dates, provenance/units, bounded output, no statement endpoints, and runtime independence from network access.
