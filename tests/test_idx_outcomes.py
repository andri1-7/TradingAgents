"""Synthetic chronological outcome boundaries."""

import json
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from tradingagents.idx_strategies.models import Bar, Costs
from tradingagents.idx_strategies.outcomes import advance_observation
from tradingagents.idx_strategies.sessions import Calendar, Session


def setup():
    t = datetime.fromisoformat("2026-10-28T10:00:01+07:00")
    return {
        "symbol": "BBCA.JK",
        "strategy": "day",
        "status": "SETUP",
        "observed_at": t.isoformat(),
        "entry_deadline": "2026-10-28T10:10:00+07:00",
        "planned_exit": "2026-10-28T10:15:00+07:00",
        "reference_price": "100",
        "stop": "99",
        "target": "102",
    }, t


def bar(start, op="100", hi="101", lo="99.5", cl="100"):
    t = datetime.fromisoformat(start)
    return Bar("BBCA.JK", t, t + timedelta(minutes=5), D(op), D(hi), D(lo), D(cl), D(1000))


def test_missing_first_slot_not_later_fill():
    row, t = setup()
    out = advance_observation(row, [bar("2026-10-28T10:10:00+07:00")], t + timedelta(minutes=20))
    assert out["status"] == "UNOBSERVABLE"
    assert row["status"] == "SETUP"


def test_entry_gap_invalid_risk_rejected():
    row, t = setup()
    out = advance_observation(
        row,
        [bar("2026-10-28T10:05:00+07:00", "103", "104", "102", "103")],
        t + timedelta(minutes=10),
    )
    assert out["status"] == "ENTRY_REJECTED"


def test_time_exit_costs_and_idempotence():
    row, t = setup()
    row["target"] = "103"
    bars = [
        bar("2026-10-28T10:05:00+07:00"),
        bar("2026-10-28T10:10:00+07:00"),
        bar("2026-10-28T10:15:00+07:00", "100.5", "101", "100", "100.5"),
    ]
    out = advance_observation(
        row, bars, t + timedelta(minutes=20), Costs(D(".001"), D(".001"), D(0), D(0))
    )
    assert out["status"] == "EXITED"
    assert D(out["net_return"]) < D(out["gross_return"])
    assert advance_observation(out, [], t + timedelta(days=1)) == out


def test_future_bars_never_enter():
    row, t = setup()
    assert advance_observation(row, [bar("2026-10-28T10:05:00+07:00")], t)["status"] == "SETUP"


def supplied_calendar(*intervals):
    pairs = tuple(tuple(datetime.fromisoformat(value) for value in pair) for pair in intervals)
    return Calendar((Session(pairs[0][0].date(), pairs),), "operator-calendar", pairs[0][0])


@pytest.mark.parametrize("minutes", [0, 2, 4])
@pytest.mark.parametrize("include_history", [False, True])
@pytest.mark.parametrize("with_calendar", [False, True])
def test_entry_open_deadline_waits_for_closed_evidence_then_restart(
    minutes, include_history, with_calendar
):
    row, _ = setup()
    row.update(
        strategy="overnight",
        observed_at="2026-10-28T09:35:02+07:00",
        entry_deadline="2026-10-28T09:40:00+07:00",
    )
    entrybar = bar(row["entry_deadline"])
    history = [bar("2026-10-28T09:35:00+07:00")] if include_history else []
    calendar = (
        supplied_calendar(("2026-10-28T09:00:00+07:00", "2026-10-28T11:00:00+07:00"))
        if with_calendar
        else None
    )
    pending = advance_observation(
        row, history + [entrybar], entrybar.start + timedelta(minutes=minutes), calendar=calendar
    )
    assert pending == row
    restarted = json.loads(json.dumps(pending))
    entered = advance_observation(restarted, history + [entrybar], entrybar.end, calendar=calendar)
    assert entered["status"] == "ENTERED"
    assert entered["entry"]["time"] == row["entry_deadline"]


@pytest.mark.parametrize("include_history", [False, True])
def test_entry_open_deadline_rejects_missing_evidence_at_close(include_history):
    row, _ = setup()
    row.update(observed_at="2026-10-28T09:35:02+07:00", entry_deadline="2026-10-28T09:40:00+07:00")
    history = [bar("2026-10-28T09:35:00+07:00")] if include_history else []
    out = advance_observation(row, history, datetime.fromisoformat("2026-10-28T09:45:00+07:00"))
    assert out["status"] == "UNOBSERVABLE"
    assert "entry" not in out


def test_empty_history_rejects_missing_first_entry_after_close_before_deadline():
    row, _ = setup()
    row["entry_deadline"] = "2026-10-28T10:20:00+07:00"
    out = advance_observation(row, [], datetime.fromisoformat("2026-10-28T10:10:00+07:00"))
    assert out["status"] == "UNOBSERVABLE"
    assert out["outcome_reason"] == "missing_first_entry_bar"


@pytest.mark.parametrize("interval_end", ["10:10:00", "10:12:00"])
@pytest.mark.parametrize("status", ["SETUP", "ENTERED"])
def test_every_traversed_bar_must_fit_continuous_session(interval_end, status):
    row, _ = setup()
    row["status"] = status
    if status == "ENTERED":
        row["entry"] = {"time": "2026-10-28T10:05:00+07:00", "price": "100"}
    calendar = supplied_calendar(
        ("2026-10-28T09:00:00+07:00", f"2026-10-28T{interval_end}+07:00"),
        ("2026-10-28T13:00:00+07:00", "2026-10-28T16:00:00+07:00"),
    )
    bars = [
        bar("2026-10-28T10:05:00+07:00"),
        bar("2026-10-28T10:10:00+07:00", "98", "98.5", "97", "98"),
    ]
    out = advance_observation(row, bars, bars[-1].end, calendar=calendar)
    assert out["status"] == "UNOBSERVABLE"
    assert out["outcome_reason"] == "bar_outside_continuous_session"
    assert "exit" not in out
    assert "gross_return" not in out


def test_supplied_lunch_gap_allows_valid_afternoon_time_exit():
    row, _ = setup()
    row["planned_exit"] = "2026-10-28T13:00:00+07:00"
    calendar = supplied_calendar(
        ("2026-10-28T09:00:00+07:00", "2026-10-28T10:10:00+07:00"),
        ("2026-10-28T13:00:00+07:00", "2026-10-28T16:00:00+07:00"),
    )
    bars = [bar("2026-10-28T10:05:00+07:00"), bar(row["planned_exit"])]
    out = advance_observation(row, bars, bars[-1].end, calendar=calendar)
    assert out["status"] == "EXITED"
    assert out["exit"]["basis"] == "time_exit"
    assert out["exit"]["time"] == row["planned_exit"]
