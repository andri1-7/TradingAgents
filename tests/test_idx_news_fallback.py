"""Transport failures must advance the configured IDX news chain."""
import pytest
import requests


def test_failed_rss_raises_typed_vendor_error(monkeypatch):
    from tradingagents.dataflows.errors import VendorUnavailableError
    from tradingagents.dataflows.vendors.idx_news import get_idx_news
    def fail(*args, **kwargs):
        raise requests.Timeout()
    monkeypatch.setattr('tradingagents.dataflows.vendors.idx_news.requests.get', fail)
    with pytest.raises(VendorUnavailableError):
        get_idx_news('BBCA.JK', '2026-10-19', '2026-10-26')
