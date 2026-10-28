"""Fault-injection durability regressions; synthetic clocks only."""

from datetime import datetime

import pytest

from tradingagents.idx_strategies.store import Store


def test_crash_after_setup_commit_cannot_be_settled(tmp_path):
    path = tmp_path / "s.db"
    store = Store(path)
    row = {
        "symbol": "BBCA.JK",
        "strategy": "day",
        "session_date": "2026-10-28",
        "observed_at": "2026-10-28T10:04:59+07:00",
        "status": "SETUP",
        "rubric_version": "v1",
        "entry_deadline": "2026-10-28T10:10:00+07:00",
        "calendar_hash": "verified-test",
        "reasons": [],
    }

    def clock():
        if store.observations()[0]["status"] == "SETUP":
            raise KeyboardInterrupt("simulated crash before admission certificate")
        return datetime.fromisoformat(row["observed_at"])

    with pytest.raises(KeyboardInterrupt):
        store.admit_observation(row, clock)
    store.close()
    reopened = Store(path)
    assert reopened.pending() == []
    assert reopened.observations()[0].get("admission_verified") is not True
    reopened.close()


def test_daily_calendar_must_cover_21_completed_sessions():
    from datetime import date, timedelta

    from tradingagents.idx_strategies.cli import _daily_context
    from tradingagents.idx_strategies.sessions import Calendar, Session

    now = datetime.fromisoformat("2026-10-28T11:00:00+07:00")
    start = datetime.fromisoformat("2026-10-27T09:00:00+07:00")
    cal = Calendar(
        (Session(date(2026, 10, 27), ((start, start + timedelta(hours=3)),)),), "synthetic", now
    )
    rows = [
        {
            "date": (now.date() - timedelta(days=i)).isoformat(),
            "close": "100",
            "volume": "200000000",
        }
        for i in range(21, 0, -1)
    ]
    result = _daily_context({"status": "OK", "bars": rows, "corporate_actions": []}, now, cal)
    assert result["eligible"] is False
    assert result["reason"] == "daily_calendar_history_insufficient"
