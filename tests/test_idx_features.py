"""Exact synthetic indicator examples; callers supply only completed history."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from tradingagents.idx_strategies.features import ema, relative_volume, vwap
from tradingagents.idx_strategies.models import Bar


def bars(volumes):
    start = datetime.fromisoformat('2026-10-26T09:00:00+07:00')
    return [Bar('BBCA.JK', start + timedelta(minutes=5*i), start + timedelta(minutes=5*(i+1)),
                D(3), D(6), D(3), D(3), D(v)) for i, v in enumerate(volumes)]


def test_exact_typical_price_vwap():
    rows = bars([1, 3])
    rows[1] = replace(rows[1], high=D(12), low=D(6), close=D(6))
    assert vwap(rows) == D(7)
    with pytest.raises(ValueError):
        vwap(bars([0]))
    with pytest.raises(ValueError):
        vwap([])


def test_volume_baseline_excludes_current_uses_preceding20():
    assert relative_volume(bars([1000] + [10]*20 + [20])) == D(2)
    with pytest.raises(ValueError):
        relative_volume(bars([10]*20))
    with pytest.raises(ValueError):
        relative_volume(bars([0]*20 + [20]))


def test_ema_seed_sma20_then_recurrence_completed_daily_only():
    # Function consumes completed closes, not current daily bars or timestamps.
    completed = [D(10)]*20 + [D(31)]
    assert ema(completed, span=20) == D(12)
    with pytest.raises(ValueError):
        ema(completed[:20], span=20)
    with pytest.raises(ValueError):
        ema([D('NaN')]*21, span=20)
    with pytest.raises(ValueError):
        ema(completed, span=0)
