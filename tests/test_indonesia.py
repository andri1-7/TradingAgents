"""Indonesia support; all vendor responses in unit tests are local fixtures."""

import pytest

from tradingagents.dataflows.symbols import normalize_symbol


@pytest.mark.parametrize("raw", ["IDX:BBCA", "bei:bbca", " idx:tlkm "])
def test_explicit_exchange_prefix(raw):
    assert normalize_symbol(raw) == raw.strip().split(":")[1].upper() + ".JK"


@pytest.mark.parametrize("raw", ["BBCA", "AAPL", "META", "BBCA.JK", "^JKSE"])
def test_unqualified_symbols_are_not_guessed(raw):
    assert normalize_symbol(raw) == raw


def test_indonesia_profile_isolated_from_other_markets():
    from copy import deepcopy

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.indonesia import build_indonesia_config

    original = deepcopy(DEFAULT_CONFIG)
    config = build_indonesia_config()
    assert config["output_language"] == "Indonesian"
    assert config["market"] == "IDX"
    assert config["currency"] == "IDR"
    assert config["market_timezone"] == "Asia/Jakarta"
    assert config["benchmark_ticker"] == "^JKSE"
    for category in ("core_stock_apis", "technical_indicators", "fundamental_data", "news_data"):
        assert config["data_vendors"][category] == "yfinance"
    assert "Bank Indonesia" in " ".join(config["global_news_queries"])
    config["data_vendors"]["fundamental_data"] = "changed"
    assert original == DEFAULT_CONFIG


def test_idx_context_reaches_prompts_without_us_assumptions():
    from tradingagents.agents.context import get_instrument_context_from_state

    context = get_instrument_context_from_state({"company_of_interest": "BBCA.JK"})
    for term in ("IDX", "IDR", "Asia/Jakarta", "^JKSE", "SEC", "insider", "unavailable", "long-only", "fees", "liquidity", "lot"):
        assert term in context
    assert "IDX" not in get_instrument_context_from_state({"company_of_interest": "AAPL"})


def test_idx_statements_skip_sec_and_insiders_are_explicitly_unsupported(monkeypatch):
    from tradingagents.dataflows import router

    calls = []
    def yahoo(*args):
        calls.append(args)
        return "Yahoo statement"
    def forbidden(*args):
        pytest.fail("US SEC or insider vendor must not run for IDX")
    monkeypatch.setitem(router.VENDOR_METHODS, "get_balance_sheet", {"sec_edgar": forbidden, "yfinance": yahoo})
    monkeypatch.setitem(router.VENDOR_METHODS, "get_insider_transactions", {"yfinance": forbidden})
    assert router.route_to_vendor("get_balance_sheet", "BBCA.JK", "annual", "2026-01-15") == "Yahoo statement"
    assert calls == [("BBCA.JK", "annual", "2026-01-15")]
    result = router.route_to_vendor("get_insider_transactions", "IDX:BBCA", "2026-01-15")
    assert result.startswith("DATA_UNAVAILABLE:")
    assert "not evidence" in result


def test_check_data_entrypoint_uses_real_ohlcv_path_without_llm(monkeypatch, capsys):
    import json

    import pandas as pd

    from tradingagents import indonesia
    from tradingagents.dataflows.config import get_config
    from tradingagents.dataflows.vendors.yahoo import ohlcv

    calls = []
    def load(symbol, as_of_date, fill_gaps=True):
        calls.append((symbol, as_of_date, fill_gaps, get_config()["output_language"]))
        return pd.DataFrame({"Date": pd.to_datetime(["2026-01-14", "2026-01-15"]), "Close": [9000, 9100]})
    monkeypatch.setattr(ohlcv, "load_ohlcv", load)
    assert indonesia.main(["--ticker", "BBCA", "--date", "2026-01-15", "--check-data"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ticker"] == "BBCA.JK"
    assert result["currency"] == "IDR"
    assert result["as_of"] == "2026-01-15"
    assert result["prices"]["latest_date"] == "2026-01-15"
    assert result["prices"]["close"] == 9100
    assert result["benchmark"]["ticker"] == "^JKSE"
    assert [c[:3] for c in calls] == [("BBCA.JK", "2026-01-15", False), ("^JKSE", "2026-01-15", False)]
    assert all(c[3] == "Indonesian" for c in calls)


@pytest.mark.parametrize("symbol", ["BBCA.JK", "^JKSE"])
@pytest.mark.parametrize(
    "close, valid",
    [(9100.0, True), (0.0, False), (-1.0, False),
     (float("inf"), False), (float("-inf"), False), (float("nan"), False)],
)
def test_check_data_requires_finite_close(symbol, close, valid, monkeypatch, capsys):
    import json

    import pandas as pd

    from tradingagents.indonesia import main

    def load(ticker, *args, **kwargs):
        return pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-15"]),
            "Close": [close if ticker == symbol else 9100.0],
        })

    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.ohlcv.load_ohlcv", load)
    status = main(["--ticker", "BBCA", "--date", "2026-01-15", "--check-data"])
    captured = capsys.readouterr()
    if valid:
        assert status == 0
        result = json.loads(captured.out)
        key = "prices" if symbol == "BBCA.JK" else "benchmark"
        assert result[key]["close"] == close
        assert captured.err == ""
    else:
        assert status == 1
        assert captured.out == ""
        assert "DATA_UNAVAILABLE" in captured.err


def test_analysis_entrypoint_runs_graph_with_idx_profile(monkeypatch, capsys):
    from tradingagents import indonesia
    from tradingagents.graph import trading_graph

    calls = []
    class Graph:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def propagate(self, ticker, trade_date):
            calls.append((ticker, trade_date))
            return {"final_trade_decision": "Contoh laporan"}, "HOLD"
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", Graph)
    assert indonesia.main(["--ticker", "BEI:BBCA", "--date", "2026-01-15"]) == 0
    assert calls[0]["config"]["benchmark_ticker"] == "^JKSE"
    assert calls[0]["config"]["output_language"] == "Indonesian"
    assert calls[0]["selected_analysts"] == ("market", "news", "fundamentals")
    assert calls[1] == ("BBCA.JK", "2026-01-15")
    assert "Contoh laporan" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["2026-1-15", "bad", "2999-01-01"])
def test_entrypoint_rejects_invalid_or_future_dates(value):
    from tradingagents.indonesia import main

    with pytest.raises(SystemExit) as exc:
        main(["--ticker", "BBCA", "--date", value, "--check-data"])
    assert exc.value.code == 2


def test_generic_idx_benchmark_uses_ihsg():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["benchmark_map"].get(".JK") == "^JKSE"
    assert DEFAULT_CONFIG["benchmark_map"][""] == "SPY"


def test_check_data_reports_missing_rows_without_fabricating(monkeypatch, capsys):
    import pandas as pd

    from tradingagents.indonesia import main

    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.ohlcv.load_ohlcv", lambda *a, **k: pd.DataFrame())
    assert main(["--ticker", "BBCA", "--date", "2026-01-15", "--check-data"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "DATA_UNAVAILABLE" in captured.err
