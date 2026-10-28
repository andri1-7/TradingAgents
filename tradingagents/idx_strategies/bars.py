"""Strict closed 5-minute bars: reject (never silently filter) open/future data."""

from datetime import timedelta
from decimal import Decimal

from .models import Bar

FIVE_MINUTES = timedelta(minutes=5)


def _aware(value):
    return value.tzinfo is not None and value.utcoffset() is not None


def validate_bars(bars, observed_at, expected_intervals=None) -> list[Bar]:
    """Sort and collapse exact duplicates; fail closed on any invalid input.

    expected_intervals, when supplied, is a sequence of continuous [start,end)
    windows of CLOSED bars required by the caller, excluding lunch/holidays.
    """
    if not _aware(observed_at):
        raise ValueError("naive observation timestamp")
    result = {}
    symbols = set()
    for bar in bars:
        if not _aware(bar.start) or not _aware(bar.end):
            raise ValueError("naive bar timestamp")
        if bar.start.second or bar.start.microsecond or bar.start.minute % 5:
            raise ValueError("off-grid bar timestamp")
        if bar.end - bar.start != FIVE_MINUTES:
            raise ValueError("unsupported bar duration")
        if bar.end > observed_at:
            raise ValueError("open or future bar")
        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(isinstance(x, Decimal) and x.is_finite() and x > 0 for x in prices):
            raise ValueError("invalid OHLC")
        if not isinstance(bar.volume, Decimal) or not bar.volume.is_finite() or bar.volume < 0:
            raise ValueError("invalid volume")
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError("inconsistent OHLC")
        symbols.add(bar.symbol)
        if len(symbols) > 1:
            raise ValueError("mixed symbols")
        if bar.start in result and result[bar.start] != bar:
            raise ValueError("conflicting duplicate bar")
        result[bar.start] = bar
    if not result:
        raise ValueError("empty history: no trades or unavailable data; cause unknown")
    if expected_intervals is not None:
        required = set()
        previous_end = None
        for start, end in expected_intervals:
            if (
                not _aware(start)
                or not _aware(end)
                or end <= start
                or start.second
                or start.microsecond
                or start.minute % 5
                or (end - start) % FIVE_MINUTES
                or end > observed_at
                or (previous_end is not None and start < previous_end)
            ):
                raise ValueError("invalid expected interval")
            previous_end = end
            while start < end:
                required.add(start)
                start += FIVE_MINUTES
        if required - result.keys():
            raise ValueError("missing required bars; no interpolation")
    return sorted(result.values(), key=lambda b: b.start)
