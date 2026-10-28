"""Operator-supplied continuous sessions; never infer weekdays or holidays."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")


class MissingSession(ValueError):
    """Required session was not supplied by the operator."""


@dataclass(frozen=True)
class Session:
    date: date
    intervals: tuple[tuple[datetime, datetime], ...]

    @property
    def open(self):
        return self.intervals[0][0]

    @property
    def close(self):
        return self.intervals[-1][1]


@dataclass(frozen=True)
class Calendar:
    sessions: tuple[Session, ...]
    source_url: str
    retrieved_at: datetime
    timezone: str = "Asia/Jakarta"

    def get(self, day):
        for session in self.sessions:
            if session.date == day:
                return session
        raise MissingSession(f"missing session: {day}")

    def next_session(self, day):
        for session in self.sessions:
            if session.date > day:
                return session
        raise MissingSession(f"missing next session after {day}")


def _trading_offset(session, minutes, reverse=False):
    remaining = timedelta(minutes=minutes)
    intervals = reversed(session.intervals) if reverse else session.intervals
    for start, end in intervals:
        duration = end - start
        if remaining <= duration:
            return end - remaining if reverse else start + remaining
        remaining -= duration
    raise ValueError("session too short for policy window")


def decision_windows(session, strategy, next_session=None):
    """Research policy; deadlines leave one 5m future entry before time exit.

    Day decisions run from opening-range completion until 5 trading minutes
    before exit. Overnight observation is at exactly close minus 30 trading
    minutes; entry grace is the following 5 trading minutes.
    """
    if strategy == "day":
        start = _trading_offset(session, 30)
        exit_at = _trading_offset(session, 15, reverse=True)
        deadline = _trading_offset(session, 20, reverse=True)
        end = _trading_offset(session, 25, reverse=True)
        if end < start:
            raise ValueError("session too short for day decision and entry")
    elif strategy == "overnight":
        if next_session is None:
            raise MissingSession("overnight requires supplied next session")
        if next_session.date <= session.date:
            raise ValueError("next session must be later")
        start = end = _trading_offset(session, 30, reverse=True)
        deadline = _trading_offset(session, 25, reverse=True)
        exit_at = _trading_offset(next_session, 30)
    else:
        raise ValueError("unsupported strategy")
    return {
        "decision_start": start,
        "decision_end": end,
        "entry_deadline": deadline,
        "planned_exit": exit_at,
    }


def _timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("naive calendar timestamp")
    return result


def load_sessions(path) -> Calendar:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        if data["timezone"] != "Asia/Jakarta" or not data["source_url"].strip():
            raise ValueError("calendar source and Asia/Jakarta timezone required")
        retrieved = _timestamp(data["retrieved_at"])
        sessions = []
        seen = set()
        for row in data["sessions"]:
            day = date.fromisoformat(row["date"])
            if day in seen:
                raise ValueError("duplicate session")
            seen.add(day)
            intervals = []
            for pair in row["intervals"]:
                if len(pair) != 2:
                    raise ValueError("interval requires two timestamps")
                start, end = map(_timestamp, pair)
                for stamp in (start, end):
                    if (
                        stamp.utcoffset() != stamp.astimezone(JAKARTA).utcoffset()
                        or stamp.second
                        or stamp.microsecond
                        or stamp.minute % 5
                    ):
                        raise ValueError("calendar requires Jakarta-local aligned 5m boundaries")
                    if stamp.astimezone(JAKARTA).date() != day or stamp.date() != day:
                        raise ValueError("non-Jakarta session date")
                if end <= start or (intervals and start < intervals[-1][1]):
                    raise ValueError("overlapping or reversed interval")
                intervals.append((start.astimezone(JAKARTA), end.astimezone(JAKARTA)))
            if not intervals:
                raise ValueError("empty continuous intervals")
            sessions.append(Session(day, tuple(intervals)))
        if not sessions:
            raise ValueError("empty calendar")
        return Calendar(
            tuple(sorted(sessions, key=lambda s: s.date)), data["source_url"], retrieved
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid session schema") from exc
