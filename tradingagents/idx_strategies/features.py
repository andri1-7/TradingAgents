"""Pure Decimal indicators; caller must enforce completed, contiguous history."""

from decimal import Decimal
from statistics import median


def vwap(bars) -> Decimal:
    if not bars:
        raise ValueError("insufficient bars for VWAP")
    volume = sum((b.volume for b in bars), Decimal(0))
    if volume <= 0:
        raise ValueError("zero total volume")
    return sum((((b.high + b.low + b.close) / 3) * b.volume for b in bars), Decimal(0)) / volume


def relative_volume(bars) -> Decimal:
    if len(bars) < 21:
        raise ValueError("insufficient preceding 20 bars")
    baseline = median(b.volume for b in bars[-21:-1])
    if baseline <= 0:
        raise ValueError("zero preceding volume baseline")
    return bars[-1].volume / baseline


def ema(values: list[Decimal], span=20) -> Decimal:
    """SMA-seeded EMA of completed previous daily closes only.

    Require span+1 completed sessions, as policy specifies; exclusion of the
    current daily session is performed at the dated provider/rules boundary.
    """
    if type(span) is not int or span < 1 or len(values) < span + 1:
        raise ValueError("insufficient completed daily EMA history")
    if not all(isinstance(v, Decimal) and v.is_finite() and v > 0 for v in values):
        raise ValueError("invalid daily close")
    value = sum(values[:span], Decimal(0)) / span
    alpha = Decimal(2) / (span + 1)
    for close in values[span:]:
        value = close * alpha + value * (1 - alpha)
    return value
