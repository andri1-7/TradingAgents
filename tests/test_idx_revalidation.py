"""Synthetic research-only exact-symbol revalidation; no network or orders."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest


def fixture():
    opening = datetime.fromisoformat("2026-10-26T09:00:00+07:00")
    session = SimpleNamespace(
        date=opening.date(),
        open=opening,
        close=opening + timedelta(hours=6),
        intervals=((opening, opening + timedelta(hours=6)),),
    )
    history = [
        SimpleNamespace(
            date=(opening - timedelta(days=i)).date(),
            close=opening - timedelta(days=i) + timedelta(hours=6),
        )
        for i in range(21, 0, -1)
    ]
    calendar = SimpleNamespace(sessions=history + [session], get=lambda day: session)
    bars = []
    for i in range(24):
        o, h, low, c = ("99", "100", "98.5", "99.5") if i < 6 else ("100.1", "101", "100", "100.5")
        if i == 23:
            o, h, low, c = "100.1", "101.5", "100", "101"
        start = opening + timedelta(minutes=5 * i)
        bars.append(
            SimpleNamespace(
                symbol="TEST.JK",
                start=start,
                end=start + timedelta(minutes=5),
                open=D(o),
                high=D(h),
                low=D(low),
                close=D(c),
                volume=D(200 if i == 23 else 100),
            )
        )
    daily = {
        "status": "OK",
        "bars": [
            {"date": s.date.isoformat(), "close": "100", "volume": "200000000"} for s in history
        ],
    }
    candidate = {
        "symbol": "TEST.JK",
        "strategy": "day",
        "status": "SETUP",
        "signal_time": bars[-1].end.isoformat(),
        "reference_price": "101",
        "stop": "100",
        "entry_deadline": (bars[-1].end + timedelta(minutes=10)).isoformat(),
        "costs": dict.fromkeys(("buy_fee", "sell_fee", "buy_slippage", "sell_slippage"), "0"),
    }
    return candidate, calendar, bars, daily


def run(candidate=None, *, times=None, intraday=None, daily=None):
    from tradingagents.idx_strategies.revalidation import revalidate_candidate

    original, calendar, bars, envelope = fixture()
    calls = []
    clock = iter(times or [bars[-1].end + timedelta(seconds=32)] * 2)

    def fetch_i(symbol, start, cutoff):
        calls.append((symbol, start, cutoff))
        return intraday if intraday is not None else {"status": "OK", "bars": bars}

    def fetch_d(symbol, observed):
        calls.append((symbol, observed))
        return daily if daily is not None else envelope

    result = revalidate_candidate(
        candidate or original,
        calendar,
        clock=lambda: next(clock),
        fetch_intraday=fetch_i,
        fetch_daily=fetch_d,
    )
    return result, calls


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "lunch",
        "costs",
        "partial_costs",
        "invalid_costs",
        "future",
        "wrong_day",
        "wrong_status",
        "bad_strategy",
    ],
)
def test_invalid_original_evidence_never_fetches(case):
    candidate, calendar, bars, _ = fixture()
    now = bars[-1].end + timedelta(seconds=32)
    if case == "expired":
        now = datetime.fromisoformat(candidate["entry_deadline"])
    elif case == "lunch":
        calendar.get = lambda day: SimpleNamespace(
            **{**vars(calendar.sessions[-1]), "intervals": ((bars[0].start, bars[-1].end),)}
        )
    elif case == "costs":
        candidate.pop("costs")
    elif case == "partial_costs":
        candidate["costs"].pop("sell_slippage")
    elif case == "invalid_costs":
        candidate["costs"]["sell_fee"] = "NaN"
    elif case == "future":
        candidate["signal_time"] = (now + timedelta(minutes=1)).isoformat()
    elif case == "wrong_day":
        candidate["signal_time"] = (now - timedelta(days=1)).isoformat()
    elif case == "wrong_status":
        candidate["status"] = "NO_SETUP"
    else:
        candidate["strategy"] = "both"
    from tradingagents.idx_strategies.revalidation import revalidate_candidate

    def forbidden(*args):
        pytest.fail("invalid candidates must not consume provider requests")

    result = revalidate_candidate(
        candidate, calendar, clock=lambda: now, fetch_intraday=forbidden, fetch_daily=forbidden
    )
    assert result["valid"] is False
    assert result["assessment"] is None


@pytest.mark.parametrize(
    "case",
    [
        "deadline",
        "lunch",
        "backward_clock",
        "provider",
        "exception",
        "stale",
        "future_bar",
        "wrong_symbol",
        "stop_risk",
        "stop_breached",
    ],
)
def test_response_fails_closed(case):
    from tradingagents.idx_strategies.revalidation import revalidate_candidate

    candidate, calendar, bars, daily = fixture()
    started = bars[-1].end + timedelta(seconds=32)
    received = started
    if case == "deadline":
        received = datetime.fromisoformat(candidate["entry_deadline"])
    elif case == "lunch":
        session = calendar.sessions[-1]
        session.intervals = ((session.open, started + timedelta(seconds=1)),)
        received = started + timedelta(seconds=2)
    elif case == "backward_clock":
        received = started - timedelta(seconds=1)
    elif case == "stale":
        received = started + timedelta(minutes=6)
    elif case == "future_bar":
        bars[-1].end = started + timedelta(minutes=1)
    elif case == "wrong_symbol":
        for bar in bars:
            bar.symbol = "OTHER.JK"
    elif case == "stop_risk":
        candidate["stop"] = "97"
    elif case == "stop_breached":
        candidate["stop"] = "101.5"

    def fetch(*args):
        if case == "exception":
            raise RuntimeError("provider timeout")
        return {"status": "ERROR" if case == "provider" else "OK", "bars": bars}

    stamps = iter([started, received])
    result = revalidate_candidate(
        candidate,
        calendar,
        clock=lambda: next(stamps),
        fetch_intraday=fetch,
        fetch_daily=lambda *args: daily,
    )
    assert result["valid"] is False
    assert result["checked_at"] == received.isoformat()


def test_new_signal_uses_latest_assessment_without_extending_original_deadline():
    candidate, _, bars, _ = fixture()
    last = SimpleNamespace(**vars(bars[-1]))
    last.start += timedelta(minutes=5)
    last.end += timedelta(minutes=5)
    last.volume = D(300)
    result, _ = run(
        candidate,
        times=[last.end + timedelta(seconds=1)] * 2,
        intraday={"status": "OK", "bars": bars + [last]},
    )
    assert result["valid"] is True
    assert result["assessment"]["signal_time"] == last.end.isoformat()
    assert result["assessment"]["entry_deadline"] == candidate["entry_deadline"]


@pytest.mark.parametrize("failure", [False, True])
def test_overnight_uses_exact_strategy_and_requires_next_session(failure):
    from tradingagents.idx_strategies.revalidation import revalidate_candidate

    candidate, calendar, bars, daily = fixture()
    session = calendar.sessions[-1]
    session.close = bars[-1].end + timedelta(minutes=30)
    session.intervals = ((session.open, session.close),)
    following = SimpleNamespace(
        date=session.date + timedelta(days=1), open=session.open + timedelta(days=1)
    )

    def next_session(day):
        assert day == session.date
        if failure:
            raise ValueError("calendar ends")
        return following

    calendar.next_session = next_session
    candidate["strategy"] = "overnight"
    result = revalidate_candidate(
        candidate,
        calendar,
        clock=lambda: bars[-1].end,
        fetch_intraday=lambda *args: {"status": "OK", "bars": bars},
        fetch_daily=lambda *args: daily,
    )
    assert result["valid"] is (not failure)
    if not failure:
        assert result["assessment"]["strategy"] == "overnight"
        assert (
            result["assessment"]["entry_deadline"]
            == (bars[-1].end + timedelta(minutes=5)).isoformat()
        )


def test_fresh_exact_symbol_reassessed_with_original_costs_and_deadline():
    candidate, _, bars, _ = fixture()
    result, calls = run()
    assert result["valid"] is True
    assert result["assessment"]["status"] == "SETUP"
    assert result["assessment"]["symbol"] == candidate["symbol"]
    assert result["assessment"]["strategy"] == candidate["strategy"]
    assert result["assessment"]["entry_deadline"] == candidate["entry_deadline"]
    assert result["assessment"]["target"] == "102.5"
    assert result["checked_at"] == (bars[-1].end + timedelta(seconds=32)).isoformat()
    assert calls[0] == ("TEST.JK", bars[0].start, bars[-1].end)
    assert calls[1][0] == "TEST.JK"
