"""Explicit Indonesia/IDX run profile; generic ticker defaults remain unchanged."""

from copy import deepcopy

from tradingagents.default_config import build_default_config


def build_indonesia_config() -> dict:
    """Keep environment LLM settings, with isolated Indonesian data/report defaults."""
    config = deepcopy(build_default_config())
    config.update(
        market="IDX", currency="IDR", market_timezone="Asia/Jakarta",
        benchmark_ticker="^JKSE", output_language="Indonesian",
        global_news_queries=[
            "Bank Indonesia suku bunga rupiah inflasi",
            "Bursa Efek Indonesia IHSG ekonomi Indonesia",
            "Indonesia komoditas ekspor kebijakan fiskal",
        ],
    )
    for category in ("core_stock_apis", "technical_indicators", "fundamental_data", "news_data"):
        config["data_vendors"][category] = "yfinance"
    return config


def main(argv=None) -> int:
    """Check IDX OHLCV without constructing an LLM client."""
    import argparse
    import json
    import math
    import re
    import sys
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows.symbols import normalize_symbol
    from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

    parser = argparse.ArgumentParser(description="Analisis saham Indonesia (IDX / BEI)")
    parser.add_argument("--ticker", required=True, help="BBCA, BBCA.JK, IDX:BBCA, BEI:BBCA")
    parser.add_argument("--date", required=True, help="Tanggal analisis YYYY-MM-DD (sesi Jakarta)")
    parser.add_argument("--check-data", action="store_true", help="Periksa OHLCV tanpa LLM")
    args = parser.parse_args(argv)
    ticker = normalize_symbol(args.ticker)
    if re.fullmatch(r"[A-Z]{4}", ticker):
        ticker += ".JK"  # This entrypoint explicitly selects IDX, unlike the generic normalizer.
    if not re.fullmatch(r"[A-Z]{4}\.JK", ticker):
        parser.error("Gunakan kode saham IDX empat huruf, misalnya BBCA atau BBCA.JK")
    try:
        parsed_date = date.fromisoformat(args.date)
        if parsed_date.isoformat() != args.date:
            raise ValueError("format")
    except ValueError:
        parser.error("Tanggal harus YYYY-MM-DD")
    if parsed_date > datetime.now(ZoneInfo("Asia/Jakarta")).date():
        parser.error("Tanggal tidak boleh di masa depan")
    config = build_indonesia_config()
    with run_config(config):
        if not args.check_data:
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            graph = TradingAgentsGraph(
                selected_analysts=("market", "news", "fundamentals"), config=config,
            )
            state, rating = graph.propagate(ticker, args.date)
            print(state["final_trade_decision"])
            print(f"Rating: {rating}")
            return 0
        result = {
            "ticker": ticker, "as_of": args.date, "currency": "IDR",
            "timezone": "Asia/Jakarta", "source": "yfinance (may use local cache)",
        }
        try:
            for key, symbol in (("prices", ticker), ("benchmark", "^JKSE")):
                frame = load_ohlcv(symbol, args.date, fill_gaps=False)
                if frame.empty:
                    raise ValueError(f"Tidak ada data: {symbol}")
                latest = frame.iloc[-1]
                close = float(latest["Close"])
                if not math.isfinite(close) or close <= 0:
                    raise ValueError(f"Close harus finite dan positif: {symbol}")
                result[key] = {
                    "ticker": symbol, "rows": len(frame),
                    "latest_date": latest["Date"].strftime("%Y-%m-%d"),
                    "close": close,
                }
            output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        except Exception as exc:
            print(f"DATA_UNAVAILABLE: {exc}", file=sys.stderr)
            return 1
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
