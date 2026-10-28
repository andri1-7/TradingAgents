# IDX news: public RSS metadata fallback

## Interface and wiring

```python
from tradingagents.dataflows.vendors.idx_news import get_idx_news

report = get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
```

`get_idx_news(ticker: str, start_date: str, end_date: str) -> str` matches the
three-argument news-vendor interface. Router wiring is intentionally separate.
This provider changes no fundamentals guards, financial data, or symbol resolver.

Only exact uppercase canonical `XXXX.JK` identifiers are accepted; normalize
aliases explicitly upstream. The sole curated company-name lookup is
`BBCA.JK -> Bank Central Asia` ([issuer identity](https://www.bca.co.id/en/tentang-bca)).
Other correctly formed symbols use only their exact four-letter code; this is
not proof that a listing exists and never invents an issuer name.

One request searches public Google News RSS with the quoted code OR known
company name, `Indonesia`, and `after:`/`before:` operators, with Indonesian
locale parameters. A result title must independently contain the exact code
with alphanumeric boundaries, or the known company name. Search discovery is
**not** equivalent to exchange-verified ticker tagging: relevance can still be
imperfect, and opinion or evergreen material can occur. No paid key, article
scraping, redirect decoding, CAPTCHA bypass, or issuer-RSS claim is involved.

## Evidence and limits

The report preserves the feed's title, raw `pubDate`, timezone-normalized UTC
publication timestamp, RSS article URL, publisher label, and `<source url>`.
Google's article URLs are frequently redirect URLs, **not verified canonical
publisher article URLs**. `<source url>` identifies the publisher website and
is explicitly not represented as an article URL. Descriptions are omitted: RSS
HTML snippets are not full article text. Neither claims inside headlines nor
publication timestamps are independently verified against publisher pages.

Reports state **RSS metadata only**, retrieval time and publication cutoff.
No full text, summary, sentiment or financial claims are synthesized.

No qualifying dated rows, malformed feed, transport failure or exceeded budget
returns an explicit `IDX news unavailable` string. This is not evidence that no
news occurred, an exhaustive archive, or proof of historically observed data.
Google may revise results, omit historical articles or provide coarse timestamps.
A dated search retrieved today is not a point-in-time archival dataset.

Google's live RSS contains a personal/non-commercial-use restriction. This
implementation does not imply a redistribution or commercial-use license;
review current provider terms before deployment. Do not use it as a licensed
commercial news feed without permission.

## Conservative date semantics

Dates must be exact `YYYY-MM-DD`, in increasing order. All rows require a
parseable timezone-aware publication timestamp, including for live requests.
The start is UTC midnight of `start_date`; the exclusive end is the earliest of:

- UTC midnight immediately after `end_date`;
- Jakarta midnight immediately after `end_date` (17:00 UTC on `end_date`);
- the actual retrieval instant.

This is the **intersection** of inclusive UTC and Jakarta calendar-day windows,
not a promise of close-of-trading-session alignment. It deliberately discards
some valid boundary rows rather than leak a next-day Jakarta article. The
search's `after:` is widened one day to avoid relying on Google's boundary
semantics; exact local timestamp checks are authoritative. Current-only,
future, undated and timezone-less rows cannot answer historical requests.

## Request budgets

One query, no retries/pagination; connect/read timeouts 3/8 seconds; 12-second
monotonic streaming budget; at most 1 MiB decompressed XML, 100 inspected items,
and 10 unique (title, article URL) output rows. DTD/entity declarations and
non-HTTP(S) article links are rejected. The streaming deadline is checked
between reads; a blocking read/DNS/system networking is not a hard process
wall-clock kill. No article endpoint is fetched.

## Live retrieval evidence

Executed with the project's venv on **2026-10-28T00:50:38Z**. These are actual
RSS observations, not synthetic fixtures; publisher articles were not fetched.

`get_idx_news("BBCA.JK", "2026-10-01", "2026-10-27")` returned 10 qualifying
metadata rows with exclusive cutoff `2026-10-27T17:00:00+00:00`. One observed row:

- Title: `Kejadian Langka BBCA dalam 10 Tahun - investor.id`
- Publisher: `investor.id`
- Publisher source URL: <https://investor.id>
- Original RSS publication: `Mon, 19 Oct 2026 23:00:00 GMT`
- UTC publication: `2026-10-19T23:00:00+00:00`
- RSS article URL: <https://news.google.com/rss/articles/CBMieEFVX3lxTE9OQVFOSkEzX2Nxa2dkcFhOZHg4TXFqUlpOZ1BXajUzZDNNcXFzSFJOMlJCNmkyNjdXOGtPaDBRWGYxTDJER0t0ZDIwSHJQZkQ4OHFrbkVXRzBSNXNiMVdZNXdKWDZQeWtlNTYtSXU5MXZoNlYxNXphMw?oc=5>

`get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")` separately returned two
qualifying historical metadata rows, not substituted current rows. One:

- Title: `Beda Arah, Cek Harga Saham BMRI, BBCA, dan BBRI saat Bursa Menghijau Hari Senin (5/5) - kontan.co.id`
- Publisher: `kontan.co.id`
- Publisher source URL: <https://investasi.kontan.co.id>
- Original RSS publication: `Mon, 05 May 2025 07:00:00 GMT`
- UTC publication: `2025-05-05T07:00:00+00:00`
- RSS article URL: <https://news.google.com/rss/articles/CBMitgFBVV95cUxQYV9NSTl0QlI3YXc5RDZCeXI4LXZidWg0N19EM3RFWVg2a2RYLS1BR1J4V2ZSaDVuV0txa21tZTRfazVKQWJzZ2ZtckF3S0FNY2F0UWxPM0FnOHE4SU1udm9PWmNKa3dNWEY5V3J5SG1Nd2ltSFNBUFF3enZpcS1obGo0OGN0ajFYTFdDZS1xdFNVSFdSbmd4TDZ5OHRWQVJ2ZGVZWi0tY2pfQldPRExPN3ZGSmlRUdIBrgFBVV95cUxNY2VCdjBYR21hampQYkpjUVBoVEpHQkR5Ui0xNFVkdFBhSXYyT1Y3VXVfUERuU3p3TDRheTdSVE5xUWxHak1Ld3lUZk5qRWdxb1BJU0RVc3kyc1BOcWs1ZjdIdXRVWGk1dDVtRVdrZUxiTGJhNWJuRzNzNTNDaE5DckpLRTVqZXpuMlREQ0lqWW9XOGdNZXhkYURnT3UyN3VGZ0Fpcll4dnFxdUxBRnc?oc=5>

Public feed endpoint: <https://news.google.com/rss/search>. Reproduce with the
function above; search results may change. Actual initial transport probe
returned HTTP 200 and ordinary RSS XML.

## Tests

```sh
/root/projects/TradingAgents/.venv/bin/python -m pytest tests/test_idx_news.py -q
```

Tests mock only HTTP transport and exercise real XML parsing, exact symbol and
query behavior, provenance, conservative dates, unavailable states, bounds,
relevance, duplicates, missing source fields and unsafe article URLs. Core
behavior was developed through observed failing tests followed by passing runs;
additional regression checks cover existing guards.

Verification in the shared working tree: targeted IDX + existing news lookahead
suite returned `73 passed`; full `tests/` returned `1563 passed, 1 skipped,
1 deselected, 24 warnings, 100 subtests passed`. The skip was missing optional
`langchain_aws`; warnings concerned existing model-name lists. Other concurrent
agents may change shared-tree totals after this run.
