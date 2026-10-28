"""Offline, point-in-time tests for the narrowly allowlisted issuer evidence."""
import importlib
import importlib.util

import pytest

from tradingagents.dataflows.errors import VendorUnavailableError


@pytest.mark.parametrize("as_of_date", ["2026-07-28", "2026-07-29", "2020-01-01"])
def test_before_conservative_boundary_withholds_without_quote_leak(as_of_date):
    with pytest.raises(VendorUnavailableError) as error:
        provider().get_issuer_fundamentals("BBCA", as_of_date)
    assert "withheld" in str(error.value).lower()
    assert "Rp" not in str(error.value)
    assert "29,5" not in str(error.value)


@pytest.mark.parametrize("ticker", ["BBRI", "BBRI.JK", "https://example.org", "BBCA.US", ""])
def test_non_allowlisted_tickers_have_no_coverage(ticker):
    with pytest.raises(VendorUnavailableError, match="coverage"):
        provider().get_issuer_fundamentals(ticker, "2026-07-30")


@pytest.mark.parametrize("ticker", ["BBCA", "BBCA.JK", "bbca.jk"])
def test_supported_aliases_return_same_issuer(ticker):
    assert provider().get_issuer_fundamentals(ticker, "2026-07-30") == provider().get_issuer_fundamentals("BBCA", "2026-07-30")


@pytest.mark.parametrize("as_of_date", [None, "", "2026-7-30", "2026-07-30T00:00:00", "2026-02-30"])
def test_missing_or_invalid_date_fails_closed(as_of_date):
    with pytest.raises(VendorUnavailableError, match="YYYY-MM-DD"):
        provider().get_issuer_fundamentals("BBCA", as_of_date)


def test_provider_exposes_no_statement_endpoints():
    module = provider()
    for endpoint in ("get_balance_sheet", "get_income_statement", "get_cashflow"):
        assert not hasattr(module, endpoint)


def test_runtime_never_needs_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("issuer evidence must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert SOURCE in provider().get_issuer_fundamentals("BBCA", "2026-07-30")
    with pytest.raises(VendorUnavailableError):
        provider().get_issuer_fundamentals("https://example.org", "2026-07-30")


SOURCE = (
    "https://bca.co.id/id/tentang-bca/media-riset/pressroom/siaran-pers/"
    "2026/07/29/07/10/pertama-kali-kredit-tembus-rp1000-triliun-bca-komit-dukung-perekonomian-nasional"
)


def provider():
    name = "tradingagents.dataflows.vendors.issuer_evidence"
    assert importlib.util.find_spec(name) is not None, "dated issuer evidence provider is missing"
    return importlib.import_module(name)


def test_bbca_official_excerpt_retains_units_and_provenance():
    result = provider().get_issuer_fundamentals("BBCA", "2026-07-30")
    assert isinstance(result, str)
    assert SOURCE in result
    assert "Total laba BCA dan entitas anak pada semester I 2026 mencapai Rp29,5 triliun." in result
    assert "available_after: 2026-07-30" in result
    assert "Asia/Jakarta" in result
    assert "availability_basis:" in result
    assert "2026-07-29" in result and "2026-07-28" in result
    assert "not verified first publication" in result
    assert "press release" in result
    assert "not a financial statement" in result
    assert len(result) < 5000
