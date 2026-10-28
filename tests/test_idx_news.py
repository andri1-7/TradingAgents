"""Deterministic public RSS metadata checks; network only mocked at transport."""
import importlib
import importlib.util

import pytest


def provider():
    assert importlib.util.find_spec("tradingagents.dataflows.vendors.idx_news") is not None
    return importlib.import_module("tradingagents.dataflows.vendors.idx_news")


def rss_item(title="BBCA earnings", published="Thu, 08 May 2025 09:00:00 GMT", link="https://news.google.com/rss/articles/example"):
    return (f"<item><title>{title}</title><link>{link}</link><pubDate>{published}</pubDate>"
            '<source url="https://publisher.example">Publisher</source>'
            '<description>UNFETCHED ARTICLE CONTENT</description></item>')


def feed(monkeypatch, items):
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()
        def close(self):
            pass
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(provider().requests, "get", get)
    return calls


def test_dated_metadata_preserves_provenance_without_inventing_content(monkeypatch):
    feed(monkeypatch, [rss_item()])
    out = provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert "BBCA earnings" in out
    assert "2025-05-08T09:00:00+00:00" in out
    assert "Thu, 08 May 2025 09:00:00 GMT" in out
    assert "https://news.google.com/rss/articles/example" in out
    assert "https://publisher.example" in out
    assert "RSS metadata only" in out
    assert "UNFETCHED ARTICLE CONTENT" not in out


@pytest.mark.parametrize("published", [
    "", "garbage", "Fri, 09 May 2025 09:00:00",  # missing timezone
    "Sat, 10 May 2025 00:00:00 GMT",  # future UTC
    "Fri, 09 May 2025 17:00:00 GMT",  # next day Jakarta
    "Wed, 30 Apr 2025 23:59:59 GMT",  # before UTC start
])
def test_unknown_or_outside_conservative_window_unavailable(monkeypatch, published):
    feed(monkeypatch, [rss_item(published=published)])
    out = provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert "unavailable" in out
    assert "not evidence of no news" in out
    assert "BBCA earnings" not in out


def test_utc_jakarta_intersection_boundary(monkeypatch):
    feed(monkeypatch, [rss_item(published="Fri, 09 May 2025 16:59:59 GMT")])
    assert "BBCA earnings" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


def test_query_is_exact_dated_indonesia_and_single_bounded_request(monkeypatch):
    calls = feed(monkeypatch, [rss_item()])
    provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert len(calls) == 1
    url, args = calls[0]
    assert url == "https://news.google.com/rss/search"
    assert args["params"] == {
        "q": '("BBCA" OR "Bank Central Asia") Indonesia after:2025-04-30 before:2025-05-10',
        "hl": "id", "gl": "ID", "ceid": "ID:id",
    }
    assert args["timeout"] == (3, 8)
    assert args["stream"] is True


@pytest.mark.parametrize("ticker", ["BBCA", "IDX:BBCA", "BBCA.JK ", "bbca.jk", "AAPL", "BBCA.JK OR scam", "BBCA.JK.JK"])
def test_noncanonical_symbol_rejected_without_network(monkeypatch, ticker):
    calls = feed(monkeypatch, [])
    assert "unavailable" in provider()._get_idx_news(ticker, "2025-05-01", "2025-05-09")
    assert calls == []


def test_unknown_company_name_is_not_guessed(monkeypatch):
    calls = feed(monkeypatch, [])
    provider()._get_idx_news("ZZZZ.JK", "2025-05-01", "2025-05-09")
    assert calls[0][1]["params"]["q"] == '"ZZZZ" Indonesia after:2025-04-30 before:2025-05-10'


def test_item_scan_is_bounded(monkeypatch):
    feed(monkeypatch, [rss_item(title="unrelated")] * 100 + [rss_item()])
    assert "unavailable" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


def test_current_sample_never_answers_historical_window(monkeypatch):
    feed(monkeypatch, [rss_item(published="Mon, 19 Oct 2026 07:00:00 GMT")])
    out = provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert "unavailable" in out
    assert "BBCA earnings" not in out


def test_future_publication_never_answers_live_window(monkeypatch):
    feed(monkeypatch, [rss_item(published="Mon, 19 Oct 2099 07:00:00 GMT")])
    assert "unavailable" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2099-12-31")


def test_company_name_without_ticker_is_valid_metadata(monkeypatch):
    feed(monkeypatch, [rss_item(title="Bank Central Asia announces results")])
    assert "Bank Central Asia announces results" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


def test_dtd_is_not_accepted(monkeypatch):
    feed(monkeypatch, ['<!DOCTYPE item [<!ENTITY example "data">]>'])
    assert "unavailable" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


def test_transport_deadline_is_bounded(monkeypatch):
    feed(monkeypatch, [rss_item()])
    ticks = iter([0, 13])
    monkeypatch.setattr(provider().time, "monotonic", lambda: next(ticks))
    assert "budget exceeded" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


@pytest.mark.parametrize("failure", ["timeout", "badxml", "oversize"])
def test_feed_failure_is_explicit_unavailable(monkeypatch, failure):
    mod = provider()
    if failure == "timeout":
        def get(*args, **kwargs):
            raise mod.requests.Timeout("private upstream detail")
        monkeypatch.setattr(mod.requests, "get", get)
    elif failure == "badxml":
        feed(monkeypatch, ["<broken>"])
    else:
        feed(monkeypatch, ["x" * 1_048_577])
    out = mod._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert "unavailable" in out
    assert "private upstream detail" not in out


def test_irrelevant_and_unsafe_rows_do_not_become_news(monkeypatch):
    feed(monkeypatch, [rss_item(title="BBCAA unrelated"), rss_item(link="javascript:alert(1)")])
    out = provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert "unavailable" in out


def test_deduplication_and_output_budget(monkeypatch):
    items = [rss_item(title=f"BBCA result {i}", link=f"https://example.com/{i}") for i in range(30)]
    feed(monkeypatch, [items[0], *items])
    out = provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")
    assert out.count("### BBCA result") == 10
    assert out.count("### BBCA result 0\n") == 1


def test_missing_source_is_tolerated(monkeypatch):
    item = rss_item().replace('<source url="https://publisher.example">Publisher</source>', '')
    feed(monkeypatch, [item])
    assert "BBCA earnings" in provider()._get_idx_news("BBCA.JK", "2025-05-01", "2025-05-09")


@pytest.mark.parametrize("start,end", [("2025-5-01", "2025-05-09"), ("bad", "2025-05-09"), ("2025-05-10", "2025-05-09")])
def test_invalid_dates_rejected_before_network(monkeypatch, start, end):
    calls = feed(monkeypatch, [])
    assert "unavailable" in provider()._get_idx_news("BBCA.JK", start, end)
    assert calls == []
