"""Synthetic overnight examples, not authentic market evidence."""

from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.test_idx_day_rules import synthetic_bars, synthetic_session
from tradingagents.idx_strategies import rules


def overnight(**changes):
    session = synthetic_session()
    # Synthetic short session makes the decision follow the 24 fixture bars.
    session.close = session.open + timedelta(minutes=150)
    session.intervals = ((session.open, session.close),)
    nxt = synthetic_session()
    nxt.date += timedelta(days=3)
    nxt.open += timedelta(days=3)
    nxt.close += timedelta(days=3)
    nxt.intervals = ((nxt.open, nxt.close),)
    args = {
        "symbol": "TEST.JK",
        "bars": synthetic_bars(),
        "session": session,
        "observed_at": session.close - timedelta(minutes=30),
        "daily_context": {"eligible": True, "ema20": "100", "corporate_action_ambiguity": False},
        "next_session": nxt,
        "costs": SimpleNamespace(
            buy_fee=D(0), sell_fee=D(0), buy_slippage=D(0), sell_slippage=D(0)
        ),
    }
    args.update(changes)
    return rules.assess_overnight(**args)


def test_overnight_trend_volume_strong_close_is_provisional_setup():
    result = overnight()
    assert result["status"] == "SETUP"
    assert result["planned_exit"] == "2026-10-29T09:30:00+07:00"
    assert "event_coverage_unknown" in result["reasons"]
    assert "sector_exposure_unassessed" in result["reasons"]
    assert result["evidence"]["holding_calendar_days"] == 3
    assert 0 <= result["score"] <= 10


@pytest.mark.parametrize(
    "case,status,reason",
    [
        ("calendar", "INSUFFICIENT_DATA", "next_session_required"),
        ("late", "NO_SETUP", "outside_decision_window"),
        ("early", "NO_SETUP", "outside_decision_window"),
        ("extension", "NO_SETUP", "ema_overextension"),
        ("trend", "NO_SETUP", "close_not_above_ema20"),
        ("ema", "INSUFFICIENT_DATA", "daily_ema20_required"),
        ("location", "NO_SETUP", "weak_close_location"),
        ("adverse", "NO_SETUP", "known_adverse_event"),
        ("costs", "INSUFFICIENT_DATA", "costs_required"),
    ],
)
def test_overnight_conservative_gates(case, status, reason):
    kwargs = {}
    if case == "calendar":
        kwargs["next_session"] = None
    if case == "early":
        kwargs["observed_at"] = synthetic_session().open + timedelta(minutes=119)
    if case == "late":
        kwargs["observed_at"] = synthetic_session().open + timedelta(minutes=125)
    if case == "extension":
        kwargs["daily_context"] = {"eligible": True, "ema20": "98"}
    if case == "trend":
        kwargs["daily_context"] = {"eligible": True, "ema20": "102"}
    if case == "ema":
        kwargs["daily_context"] = {"eligible": True}
    if case == "adverse":
        kwargs["adverse_event"] = True
    if case == "costs":
        kwargs["costs"] = None
    if case == "location":
        bars = synthetic_bars()
        bars[8].high = D(105)
        kwargs["bars"] = bars
    result = overnight(**kwargs)
    assert result["status"] == status
    assert reason in result["reasons"]


def test_overnight_uses_decision_cutoff_not_later_or_foreign_bars():
    bars = synthetic_bars()
    future = SimpleNamespace(**vars(bars[-1]))
    future.start, future.end = bars[-1].end, bars[-1].end + timedelta(minutes=5)
    future.close = D(1000)
    foreign = SimpleNamespace(**vars(future))
    foreign.start -= timedelta(days=1)
    foreign.end -= timedelta(days=1)
    now = bars[-1].end + timedelta(minutes=4)
    assert overnight(bars=bars + [future, foreign], observed_at=now) == overnight(observed_at=now)
