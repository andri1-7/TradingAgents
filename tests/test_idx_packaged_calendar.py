from datetime import date
from importlib.resources import files

from tradingagents.idx_strategies.sessions import load_sessions


def test_sourced_calendar_covers_history_and_next_session():
    path = files("tradingagents").joinpath("assets/idx_sessions_2026.json")
    calendar = load_sessions(path)
    today = date(2026, 10, 28)
    assert len([s for s in calendar.sessions if s.date < today]) >= 21
    assert calendar.get(today).open.isoformat() == "2026-10-28T09:00:00+07:00"
    assert calendar.next_session(today).date == date(2026, 10, 29)
    friday = calendar.get(date(2026, 10, 30))
    assert friday.intervals[0][1].hour == 11
    assert friday.intervals[0][1].minute == 30
    assert friday.intervals[1][0].hour == 14
    assert all(s.date.weekday() < 5 for s in calendar.sessions)
