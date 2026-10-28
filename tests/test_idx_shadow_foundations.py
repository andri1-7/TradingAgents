"""Synthetic research contracts; no exchange schedule or market-data claims."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from tradingagents.idx_strategies.bars import validate_bars
from tradingagents.idx_strategies.models import Bar, Costs, Status, net_reference_return


def bar(start=None, **kwargs):
    start = start or datetime.fromisoformat('2026-10-26T09:00:00+07:00')
    return replace(Bar('BBCA.JK', start, start + timedelta(minutes=5),
                       D(100), D(110), D(90), D(105), D(10)), **kwargs)


def test_exact_types_and_costs():
    assert net_reference_return(D(100), D(110), Costs(*[D(0)] * 4)) == D('0.1')
    assert net_reference_return(D(100), D(100), Costs(*[D('.001')] * 4)) < 0
    assert Status.SETUP == 'SETUP'
    with pytest.raises(FrozenInstanceError):
        bar().close = D(9)


@pytest.mark.parametrize('entry,exit,cost', [('NaN','100','0'), ('Infinity','100','0'),
    ('0','100','0'), ('100','0','0'), ('100','100','-0.1'), ('100','100','1'),
    ('100','100','NaN'), ('100','100','Infinity')])
def test_invalid_costs(entry, exit, cost):
    with pytest.raises(ValueError):
        net_reference_return(D(entry), D(exit), Costs(*[D(cost)] * 4))


def test_expected_coverage_excludes_lunch_but_never_fills_missing():
    a = bar()
    b = bar(datetime.fromisoformat('2026-10-26T13:30:00+07:00'))
    intervals = [(a.start, a.end), (b.start, b.end)]
    assert validate_bars([a, b], b.end, intervals) == [a, b]
    with pytest.raises(ValueError, match='missing'):
        validate_bars([a], b.end, intervals)
    with pytest.raises(ValueError, match='empty'):
        validate_bars([], b.end)
    with pytest.raises(ValueError, match='interval'):
        validate_bars([a], b.end, [(a.start, a.end + timedelta(minutes=1))])


def test_closed_bars_sorted_exact_duplicates_collapsed():
    a = bar()
    b = bar(a.end)
    assert validate_bars([b, a, a], b.end) == [a, b]


@pytest.mark.parametrize('change', [
    {'start': datetime(2026, 10, 26, 9)},
    {'end': datetime(2026, 10, 26, 9, 5)},
    {'start': datetime.fromisoformat('2026-10-26T09:01:00+07:00')},
    {'open': D('NaN')}, {'high': D('Infinity')}, {'low': D(0)},
    {'volume': D(-1)}, {'close': D(111)}, {'high': D(89)},
    {'end': datetime.fromisoformat('2026-10-26T09:10:00+07:00')},
])
def test_invalid_bars_rejected(change):
    with pytest.raises(ValueError):
        validate_bars([bar(**change)], bar().end)


def test_future_open_conflicting_and_mixed_symbols_rejected():
    a = bar()
    for rows, clock in [([a], a.start), ([a, replace(a, close=D(106))], a.end),
                        ([a, bar(a.end, symbol='UNTR.JK')], a.end + timedelta(minutes=5))]:
        with pytest.raises(ValueError):
            validate_bars(rows, clock)

