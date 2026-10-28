"""Synthetic strategy fixtures; not real IDX data or verified session hours."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tradingagents.idx_strategies import rules


def synthetic_session():
    opening = datetime.fromisoformat("2026-10-26T09:00:00+07:00")
    closing = opening + timedelta(hours=6)
    return SimpleNamespace(
        date=date(2026, 10, 26), open=opening, close=closing, intervals=((opening, closing),)
    )


def synthetic_bars():
    session = synthetic_session()
    result = []
    for i in range(24):
        # First six bars define 100 opening-range high, then breakout.
        o, h, low, c = ("99", "100", "98.5", "99.5") if i < 6 else ("100.1", "101", "100", "100.5")
        if i == 23:
            o, h, low, c = "100.1", "101.5", "100", "101"
        start = session.open + timedelta(minutes=5 * i)
        result.append(
            SimpleNamespace(
                symbol="TEST.JK",
                start=start,
                end=start + timedelta(minutes=5),
                open=D(o),
                high=D(h),
                low=D(low),
                close=D(c),
                volume=D("200" if i == 23 else "100"),
            )
        )
    return result


def day(**changes):
    bars = synthetic_bars()
    args = {
        "symbol": "TEST.JK",
        "bars": bars,
        "session": synthetic_session(),
        "observed_at": bars[-1].end,
        "daily_context": {"eligible": True, "ema20": "100", "corporate_action_ambiguity": False},
        "costs": SimpleNamespace(
            buy_fee=D(0), sell_fee=D(0), buy_slippage=D(0), sell_slippage=D(0)
        ),
    }
    args.update(changes)
    return rules.assess_day(**args)


def test_day_requires_completed_breakout_then_later_retest():
    result = day()
    assert result["status"] == "SETUP"
    assert result["strategy"] == "day"
    assert result["reference_price"] == "101"
    assert result["stop"] == "100"
    assert result["target"] == "102.5"
    assert result["signal_time"] == synthetic_bars()[-1].end.isoformat()


@pytest.mark.parametrize(
    "case,expected,reason",
    [
        ("fees", "INSUFFICIENT_DATA", "costs_required"),
        ("early", "NO_SETUP", "outside_decision_window"),
        ("late", "NO_SETUP", "outside_decision_window"),
        ("stale", "INSUFFICIENT_DATA", "stale_signal"),
        ("gap", "INSUFFICIENT_DATA", "missing_required_bars"),
        ("volume", "NO_SETUP", "relative_volume_below_1_5"),
        ("risk", "NO_SETUP", "invalid_risk_distance"),
        ("context", "INSUFFICIENT_DATA", "daily_context_required"),
        ("ineligible", "NO_SETUP", "daily_ineligible"),
        ("action", "NO_SETUP", "corporate_action_ambiguity"),
        ("breakout_only", "NO_SETUP", "valid_later_retest_required"),
        ("no_prior_breakout", "NO_SETUP", "prior_breakout_required"),
        ("history", "INSUFFICIENT_DATA", "preceding_20_bars_required"),
    ],
)
def test_day_conservative_gates(case, expected, reason):
    bars = synthetic_bars()
    kwargs = {"bars": bars}
    if case == "fees":
        kwargs["costs"] = None
    if case == "early":
        kwargs["observed_at"] = synthetic_session().open + timedelta(minutes=25)
    if case == "late":
        kwargs["observed_at"] = synthetic_session().close - timedelta(minutes=29)
    if case == "stale":
        kwargs["observed_at"] = bars[-1].end + timedelta(minutes=6)
    if case == "gap":
        del bars[10]
    if case == "volume":
        bars[-1].volume = D(100)
    if case == "risk":
        bars[-1].close = bars[-1].high = D(103)
    if case == "context":
        kwargs["daily_context"] = None
    if case == "ineligible":
        kwargs["daily_context"] = {"eligible": False}
    if case == "action":
        kwargs["daily_context"] = {"eligible": True, "corporate_action_ambiguity": True}
    if case == "breakout_only":
        bars[-1].low = bars[-1].open = D("100.5")
    if case == "no_prior_breakout":
        for bar in bars[6:-1]:
            bar.close = D(100)
    if case == "history":
        kwargs.update(bars=bars[:20], observed_at=bars[19].end)
    result = day(**kwargs)
    assert result["status"] == expected
    assert reason in result["reasons"]


def test_supplied_costs_solve_net_reward_and_keep_gross_reference():
    costs = SimpleNamespace(
        buy_fee=D(".001"), sell_fee=D(".002"), buy_slippage=D(".001"), sell_slippage=D(".001")
    )
    result = day(costs=costs)
    entry, stop, target = (D(result[k]) for k in ("reference_price", "stop", "target"))
    paid = entry * (1 + costs.buy_slippage) * (1 + costs.buy_fee)
    sell_factor = (1 - costs.sell_slippage) * (1 - costs.sell_fee)
    loss = paid - stop * sell_factor
    assert abs((target * sell_factor - paid) / loss - D("1.5")) < D("1e-23")
    assert result["evidence"]["gross_1_5r_target"] == "102.5"
    assert result["evidence"]["net_eligibility"] == "verified_provisional_reference"
    json.dumps(result)


def test_naive_observation_fails_closed_without_exception():
    result = day(observed_at=synthetic_bars()[-1].end.replace(tzinfo=None))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "aware_observation_required" in result["reasons"]


def test_day_vwap_gate_rejects_retest_below_session_vwap():
    bars = synthetic_bars()
    for bar in bars[6:-1]:
        bar.high = D(110)
    result = day(bars=bars)
    assert result["status"] == "NO_SETUP"
    assert "close_not_above_vwap" in result["reasons"]


def test_lunch_break_is_not_a_missing_required_bar():
    bars = synthetic_bars()
    session = synthetic_session()
    lunch_start = bars[12].start
    lunch_end = lunch_start + timedelta(minutes=60)
    session.intervals = ((session.open, lunch_start), (lunch_end, session.close))
    for bar in bars[12:]:
        bar.start += timedelta(minutes=60)
        bar.end += timedelta(minutes=60)
    assert day(bars=bars, session=session, observed_at=bars[-1].end)["status"] == "SETUP"


def test_future_and_other_session_bars_do_not_change_day_assessment():
    bars = synthetic_bars()
    extra = SimpleNamespace(**vars(bars[-1]))
    extra.start, extra.end = bars[-1].end, bars[-1].end + timedelta(minutes=5)
    extra.close = D(1000)
    assert day(bars=bars + [extra]) == day()
