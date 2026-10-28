"""Bounded raw-price Yahoo adapter; no retries, model calls or secret reads."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import yfinance as yf

from tradingagents.idx_strategies.bars import validate_bars
from tradingagents.idx_strategies.models import Bar


def _symbol(symbol):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z]{4}\.JK", symbol):
        raise ValueError("expected exact canonical XXXX.JK symbol")


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("explicit aware timestamp required")


def fetch_intraday(symbol, start, end, interval="5m") -> dict:
    _symbol(symbol)
    _aware(start)
    _aware(end)
    if end <= start:
        raise ValueError("end must follow start")
    if interval != "5m":
        raise ValueError("unsupported interval: only 5m")
    envelope = {
        "source": "yahoo",
        "symbol": symbol,
        "requested_range": {"start": start, "end": end},
        "interval": interval,
        "price_basis": "raw",
        "timestamp_convention": "interval_start",
        "corporate_actions": [],
        "bars": [],
        "status": "PROVIDER_ERROR",
    }
    try:
        frame = yf.Ticker(symbol).history(
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            actions=True,
            raise_errors=True,
        )
    except Exception as exc:
        # Never copy vendor exception text (may contain credentials/URLs).
        envelope["retrieved_at"] = datetime.now(UTC)
        envelope["error_category"] = (
            "RATE_LIMIT" if type(exc).__name__ == "YFRateLimitError" else "REQUEST_FAILED"
        )
        return envelope
    envelope["retrieved_at"] = datetime.now(UTC)
    if frame is None or frame.empty:
        envelope["status"] = "EMPTY_HISTORY"
        envelope["reason"] = "No rows; suspended trading is not established by an empty response"
        return envelope
    try:
        rows = []
        actions = []
        for timestamp, row in frame.iterrows():
            stamp = timestamp.to_pydatetime()
            _aware(stamp)
            stamp = stamp.astimezone(ZoneInfo("Asia/Jakarta"))
            if not start <= stamp < end:
                raise ValueError("vendor row outside requested range")
            for column, kind in [("Dividends", "dividend"), ("Stock Splits", "split")]:
                action = Decimal(str(row.get(column, 0)))
                if not action.is_finite() or action < 0:
                    raise ValueError("invalid corporate action")
                if action:
                    actions.append({"at": stamp, "kind": kind, "value": action})
            rows.append(
                Bar(
                    symbol,
                    stamp,
                    stamp + timedelta(minutes=5),
                    *(Decimal(str(row[c])) for c in ["Open", "High", "Low", "Close", "Volume"]),
                )
            )
        envelope["bars"] = validate_bars(rows, envelope["retrieved_at"])
        envelope["corporate_actions"] = actions
        envelope["action_coverage"] = (
            "reported" if {"Dividends", "Stock Splits"} <= set(frame.columns) else "unknown"
        )
        envelope["status"] = "OK"
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        envelope["status"] = "INVALID_DATA"
        envelope["reason"] = "Invalid, open, future or out-of-range vendor bars"
    return envelope


def fetch_daily(symbol, as_of) -> dict:
    """Raw daily dictionaries dated strictly before as_of's Jakarta date.

    No persistent cache: every result carries its own fetch time and range.
    Ninety calendar days is a request bound, not a guarantee of 21 sessions.
    """
    _symbol(symbol)
    _aware(as_of)
    cutoff = as_of.astimezone(ZoneInfo("Asia/Jakarta")).date()
    start = as_of - timedelta(days=90)
    envelope = {
        "source": "yahoo",
        "symbol": symbol,
        "interval": "1d",
        "price_basis": "raw",
        "requested_range": {"start": start, "end": as_of},
        "corporate_actions": [],
        "bars": [],
        "status": "PROVIDER_ERROR",
    }
    try:
        frame = yf.Ticker(symbol).history(
            start=start,
            end=as_of,
            interval="1d",
            auto_adjust=False,
            actions=True,
            raise_errors=True,
        )
    except Exception as exc:
        envelope["retrieved_at"] = datetime.now(UTC)
        envelope["error_category"] = (
            "RATE_LIMIT" if type(exc).__name__ == "YFRateLimitError" else "REQUEST_FAILED"
        )
        return envelope
    envelope["retrieved_at"] = datetime.now(UTC)
    if frame is None or frame.empty:
        envelope["status"] = "EMPTY_HISTORY"
        return envelope
    try:
        rows, actions, seen = [], [], set()
        for timestamp, row in frame.iterrows():
            stamp = timestamp.to_pydatetime()
            _aware(stamp)
            day = stamp.astimezone(ZoneInfo("Asia/Jakarta")).date()
            if day >= cutoff:
                continue
            if day < start.astimezone(ZoneInfo("Asia/Jakarta")).date():
                raise ValueError("daily row outside requested range")
            if day in seen:
                raise ValueError("duplicate daily date")
            seen.add(day)
            close, volume = (Decimal(str(row[c])) for c in ["Close", "Volume"])
            if not close.is_finite() or close <= 0 or not volume.is_finite() or volume < 0:
                raise ValueError("invalid daily data")
            row_actions = []
            for column, kind in [("Dividends", "dividend"), ("Stock Splits", "split")]:
                value = Decimal(str(row.get(column, 0)))
                if not value.is_finite() or value < 0:
                    raise ValueError("invalid daily action")
                if value:
                    row_actions.append({"date": day, "kind": kind, "value": value})
            actions.extend(row_actions)
            rows.append(
                {"date": day, "close": close, "volume": volume, "corporate_actions": row_actions}
            )
        envelope["bars"] = sorted(rows, key=lambda r: r["date"])
        envelope["corporate_actions"] = actions
        envelope["action_coverage"] = (
            "reported" if {"Dividends", "Stock Splits"} <= set(frame.columns) else "unknown"
        )
        envelope["status"] = "OK" if rows else "EMPTY_HISTORY"
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        envelope["status"] = "INVALID_DATA"
    return envelope
