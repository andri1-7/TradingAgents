"""IDX prompts must keep structured numbers independent of report locale."""

import pytest

from tradingagents.agents.context import build_instrument_context


@pytest.mark.parametrize("ticker", ["BBCA.JK", "bbri.jk"])
def test_idx_context_requires_canonical_structured_numbers(ticker):
    context = build_instrument_context(ticker)

    assert "Structured numeric price/quantity fields must be JSON numbers" in context
    assert "'.' decimal separator" in context
    assert "no thousands separators or IDR/Rp prefixes" in context
    assert "9000.5, not 9.000,50" in context
    assert "Human-readable reports may localize numbers" in context
    assert "structured values must remain canonical" in context


def test_non_idx_context_does_not_add_idx_numeric_instruction():
    context = build_instrument_context("AAPL")

    assert "Structured numeric price/quantity fields" not in context
