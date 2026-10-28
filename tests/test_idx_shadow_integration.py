"""Offline CLI→SQLite→artifact contracts using entirely synthetic market data.

The calendar below is deliberately NOT an official IDX schedule.  Providers and
clocks are injected; no historical prices, paid inference, or network is used.
"""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tradingagents.idx_strategies import cli
from tradingagents.idx_strategies.models import Bar
from tradingagents.idx_strategies.sessions import load_sessions

DAY = date(2026, 10, 26)


def instant(time, day=DAY):
    return datetime.fromisoformat(f"{day.isoformat()}T{time}+07:00")


@pytest.fixture
def calendar(tmp_path):
    path = tmp_path / "synthetic-sessions.json"
    path.write_text(
        json.dumps(
            {
                "source_url": "https://synthetic.invalid/not-official",
                "retrieved_at": "2026-10-25T00:00:00+00:00",
                "timezone": "Asia/Jakarta",
                "sessions": [
                    {
                        "date": day.isoformat(),
                        "intervals": [
                            [
                                instant("09:00:00", day).isoformat(),
                                instant("15:00:00", day).isoformat(),
                            ]
                        ],
                    }
                    for day in [
                        *(DAY - timedelta(days=i) for i in range(21, 0, -1)),
                        DAY,
                        date(2026, 10, 28),
                    ]
                ],
            }
        )
    )
    return load_sessions(path)


def arguments(tmp_path, **changes):
    values = {
        "db": str(tmp_path / "shadow.sqlite"),
        "output": str(tmp_path / "scan.json"),
        "strategy": "day",
        "limit": 2,
        "buy_fee": "0",
        "sell_fee": "0",
        "buy_slippage": "0",
        "sell_slippage": "0",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def registry(monkeypatch, symbols):
    import tradingagents.idx_registry as module

    monkeypatch.setattr(
        module,
        "load_registry",
        lambda: {
            "issuers": [
                {
                    "symbol": symbol.removesuffix(".JK"),
                    "yahoo_symbol": symbol,
                    "name": "Synthetic issuer",
                }
                for symbol in symbols
            ]
        },
    )


def signal_bars(symbol):
    rows = []
    for i in range(24):
        prices = ("99", "100", "98.5", "99.5") if i < 6 else ("100.1", "101", "100", "100.5")
        if i == 23:
            prices = ("100.1", "101.5", "100", "101")
        start = instant("09:00:00") + timedelta(minutes=5 * i)
        rows.append(
            Bar(
                symbol,
                start,
                start + timedelta(minutes=5),
                D(prices[0]),
                D(prices[1]),
                D(prices[2]),
                D(prices[3]),
                D(200 if i == 23 else 100),
            )
        )
    return rows


def daily(symbol, observed_at):
    # Twenty-one completed synthetic dates: raw close × volume clears IDR10bn.
    return {
        "status": "OK",
        "price_basis": "raw",
        "corporate_actions": [],
        "bars": [
            {"date": (DAY - timedelta(days=i)).isoformat(), "close": "100", "volume": "200000000"}
            for i in range(21, 0, -1)
        ],
    }


def provider(calls, *, fail=(), extra=()):
    def fetch(symbol, start, end):
        calls.append((symbol, start, end))
        if symbol in fail:
            return {"status": "PROVIDER_ERROR", "bars": []}
        return {
            "status": "OK",
            "price_basis": "raw",
            "corporate_actions": [],
            "bars": signal_bars(symbol) + [replace(b, symbol=symbol) for b in extra],
        }

    return fetch


def scan(args, calendar, calls, *, now=None, fail=(), extra=(), fetch_daily=daily):
    return cli.scan(
        args,
        calendar,
        clock=lambda: now or instant("11:00:02"),
        fetch_intraday=provider(calls, fail=fail, extra=extra),
        fetch_daily=fetch_daily,
    )


def artifact(args):
    with open(args.output, encoding="utf-8") as stream:
        return json.load(stream)


def sql(args, statement):
    with sqlite3.connect(args.db) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(statement)]


def observations(args):
    from tradingagents.idx_strategies.store import Store

    store = Store(args.db)
    try:
        return store.observations()
    finally:
        store.close()


@pytest.mark.parametrize("reverse_registry", [False, True])
def test_rotation_survives_reopen_and_scan_artifact_reconciles_database(
    tmp_path, monkeypatch, calendar, reverse_registry
):
    symbols = ["AAAA.JK", "BBBB.JK", "CCCC.JK", "DDDD.JK", "EEEE.JK"]
    registry(monkeypatch, list(reversed(symbols)) if reverse_registry else symbols)
    args = arguments(tmp_path, strategy="both")
    calls = []
    for expected in (symbols[:2], symbols[2:4], symbols[4:]):
        before = len(calls)
        assert scan(args, calendar, calls) == 0
        payload = artifact(args)
        assert [row[0] for row in calls[before:]] == expected
        assert payload["requested"] == payload["valid"] == len(expected)
        assert payload["failed"] == payload["excluded"] == 0
        assert len(payload["assessments"]) == 2 * len(expected)
        assert sum(payload["statuses"].values()) == 2 * len(expected)
        assert payload["coverage"]["registry_count"] == len(symbols)
        assert payload["coverage"]["request_budget"] == 2
        assert len(payload["shortlist"]) <= 3
        from tradingagents.idx_strategies.store import Store

        store = Store(args.db)
        try:
            (stored,) = [row for row in store.scans() if row["id"] == payload["scan_id"]]
        finally:
            store.close()
        assert {key: stored[key] for key in ("requested", "valid", "failed", "excluded")} == {
            key: payload[key] for key in ("requested", "valid", "failed", "excluded")
        }
    assert [row[0] for row in calls] == symbols
    assert len(sql(args, "SELECT * FROM assessments")) == 10
    assert len(sql(args, "SELECT * FROM provider_snapshots")) == 5
    # A new Store is opened on every scan, including the wrapped batch.
    assert scan(args, calendar, calls) == 0
    assert [row[0] for row in calls[-2:]] == symbols[:2]


def test_failed_symbol_consumes_slot_but_is_not_lost_from_assessments(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK", "BBBB.JK", "CCCC.JK"])
    args, calls = arguments(tmp_path), []
    assert scan(args, calendar, calls, fail={"AAAA.JK"}) == 1
    payload = artifact(args)
    assert (payload["requested"], payload["valid"], payload["failed"]) == (2, 1, 1)
    assert {r["symbol"]: r["status"] for r in payload["assessments"]} == {
        "AAAA.JK": "PROVIDER_ERROR",
        "BBBB.JK": "SETUP",
    }
    assert len(sql(args, "SELECT * FROM assessments")) == 2
    assert scan(args, calendar, calls) == 0
    assert calls[-1][0] == "CCCC.JK"


def test_provider_wide_failure_preserves_rotation_for_retry(tmp_path, monkeypatch, calendar):
    registry(monkeypatch, ["AAAA.JK", "BBBB.JK", "CCCC.JK"])
    args, calls = arguments(tmp_path), []
    assert scan(args, calendar, calls, fail={"AAAA.JK", "BBBB.JK"}) == 1
    assert artifact(args)["failed"] == 2
    assert len(sql(args, "SELECT * FROM assessments")) == 2
    assert scan(args, calendar, calls) == 0
    assert [call[0] for call in calls] == ["AAAA.JK", "BBBB.JK"] * 2


def test_missing_costs_blocks_candidate_without_hiding_technical_assessment(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path, buy_fee=None, sell_fee=None, buy_slippage=None, sell_slippage=None)
    assert scan(args, calendar, []) == 0
    payload = artifact(args)
    assert payload["coverage"]["costs_supplied"] is False
    assert payload["shortlist"] == []
    (row,) = payload["assessments"]
    assert row["status"] == "INSUFFICIENT_DATA"
    assert "costs_required" in row["reasons"]
    assert row["evidence"]["net_eligibility"] == "unknown"
    assert not observations(args)
    assert len(sql(args, "SELECT * FROM assessments")) == 1


@pytest.mark.parametrize("time", ["08:30:00", "15:30:00"])
def test_outside_session_never_creates_retrospective_setup(tmp_path, monkeypatch, calendar, time):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path, strategy="both")
    assert scan(args, calendar, [], now=instant(time)) == 0
    payload = artifact(args)
    assert payload["shortlist"] == []
    assert len(payload["assessments"]) == 2
    assert all(
        row["status"] == "NO_SETUP" and "outside_decision_window" in row["reasons"]
        for row in payload["assessments"]
    )
    assert not observations(args)


def test_future_intraday_and_current_daily_rows_cannot_change_scan(tmp_path, monkeypatch, calendar):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path)
    assert scan(args, calendar, []) == 0
    baseline = artifact(args)["assessments"]
    last = signal_bars("AAAA.JK")[-1]
    future = replace(
        last,
        start=instant("11:00:00"),
        end=instant("11:05:00"),
        open=D(500),
        high=D(999),
        low=D(1),
        close=D(900),
        volume=D(999999),
    )

    def contaminated_daily(symbol, now):
        envelope = daily(symbol, now)
        envelope["bars"].append({"date": DAY.isoformat(), "close": "0.01", "volume": "0"})
        envelope["bars"].append({"date": "2026-10-28", "close": "999999", "volume": "999999"})
        return envelope

    assert scan(args, calendar, [], extra=[future], fetch_daily=contaminated_daily) == 0
    assert artifact(args)["assessments"] == baseline
    assert len(observations(args)) == 1


def test_observation_is_durable_before_future_entry_and_repeated_scan_is_idempotent(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path)
    for _ in range(2):
        assert scan(args, calendar, []) == 0
        (card,) = artifact(args)["shortlist"]
        assert card["label"] == "WATCH"
        assert card["status"] == "SETUP"
        assert card["evidence"]["provisional_reference"] is True
        assert card["reference_price"] == "101"
        assert card["stop"] == "100"
        assert card["target"] == "102.5"
        assert card["observed_at"] == instant("11:00:02").isoformat()
    (row,) = observations(args)
    assert row["status"] == "SETUP"
    assert not row.get("entry")
    assert len(sql(args, "SELECT * FROM scans")) == 2
    assert len(sql(args, "SELECT * FROM assessments")) == 2


def test_slow_fetch_cannot_backdate_setup_before_receipt_deadline(tmp_path, monkeypatch, calendar):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path)
    times = iter([instant("11:00:02"), instant("11:00:02")])
    assert (
        cli.scan(
            args,
            calendar,
            clock=lambda: next(times, instant("11:11:00")),
            fetch_intraday=provider([]),
            fetch_daily=daily,
        )
        == 0
    )
    payload = artifact(args)
    assert payload["shortlist"] == []
    assert all(row["status"] != "SETUP" for row in payload["assessments"])
    assert not observations(args)


def settlement_bars(symbol):
    # The already-open 11:00 bar must NOT become an entry; 11:05 is eligible.
    result = []
    start = instant("11:00:00")
    while start <= instant("14:45:00"):
        result.append(
            Bar(
                symbol,
                start,
                start + timedelta(minutes=5),
                D(101),
                D("101.25"),
                D("100.5"),
                D(101),
                D(100),
            )
        )
        start += timedelta(minutes=5)
    return result


def test_settle_uses_all_pending_not_current_rotation_and_rerun_is_idempotent(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK", "BBBB.JK", "CCCC.JK"])
    args = arguments(tmp_path)
    assert scan(args, calendar, []) == 0
    assert {r["symbol"] for r in observations(args)} == {"AAAA.JK", "BBBB.JK"}
    # Change discovery universe: neither old observation is on today's shortlist.
    registry(monkeypatch, ["CCCC.JK"])
    fetched = []

    def fetch(symbol, start, end):
        fetched.append(symbol)
        return {"status": "OK", "bars": settlement_bars(symbol)}

    assert cli.settle(args, calendar, clock=lambda: instant("14:50:00"), fetch_intraday=fetch) == 0
    assert set(fetched) == {"AAAA.JK", "BBBB.JK"}
    assert artifact(args)["pending"] == 0
    assert artifact(args)["failed"] == 0
    settled = observations(args)
    assert len(settled) == 2
    assert {row["status"] for row in settled} == {"EXITED"}
    for row in settled:
        assert row["entry"]["time"] == instant("11:05:00").isoformat()
        assert row["exit"]["time"] == instant("14:45:00").isoformat()
    fetched.clear()
    assert cli.settle(args, calendar, clock=lambda: instant("14:55:00"), fetch_intraday=fetch) == 0
    assert fetched == []
    assert observations(args) == settled
    assert artifact(args)["updated"] == []


def test_evaluate_cli_keeps_strategies_separate_and_never_counts_pending_as_wins(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path)
    assert scan(args, calendar, []) == 0
    assert (
        cli.settle(
            args,
            calendar,
            clock=lambda: instant("14:50:00"),
            fetch_intraday=lambda symbol, *a: {"status": "OK", "bars": settlement_bars(symbol)},
        )
        == 0
    )
    # Retain a genuinely pending overnight observation in the same durable DB.
    from tradingagents.idx_strategies.store import Store

    store = Store(args.db)
    try:
        (day,) = store.observations()
        overnight = {
            key: value
            for key, value in day.items()
            if key not in ("id", "entry", "exit", "gross_return", "net_return")
        }
        overnight.update(
            strategy="overnight",
            status="SETUP",
            observed_at=instant("14:30:02").isoformat(),
            entry_deadline=instant("14:35:00").isoformat(),
            planned_exit=instant("09:30:00", date(2026, 10, 28)).isoformat(),
        )
        store.save_scan(
            {"started_at": overnight["observed_at"], "completed_at": overnight["observed_at"]},
            [overnight],
            [],
            next_offset=None,
        )
    finally:
        store.close()
    args.output = str(tmp_path / "evaluation.json")
    assert cli.main(["evaluate", "--db", args.db, "--output", args.output]) == 0
    payload = artifact(args)
    assert "win_rate" not in payload  # No pooled day/overnight headline.
    assert set(payload["strategies"]) == {"day", "overnight"}
    day = payload["strategies"]["day"]
    overnight = payload["strategies"]["overnight"]
    assert day["statuses"]["EXITED"] == day["observable_closed"] == 1
    assert overnight["statuses"]["SETUP"] == overnight["observations"] == 1
    assert overnight["observable_closed"] == 0
    assert overnight["net_positive_fraction"] is None
    assert overnight["gross_mean"] is overnight["net_mean"] is None
    assert payload["mode"] == "hypothetical_reference_only"
    assert len(observations(args)) == 2


def test_settle_provider_failure_keeps_pending_observations_retryable(
    tmp_path, monkeypatch, calendar
):
    registry(monkeypatch, ["AAAA.JK"])
    args = arguments(tmp_path)
    assert scan(args, calendar, []) == 0
    before = observations(args)
    assert (
        cli.settle(
            args,
            calendar,
            clock=lambda: instant("11:10:00"),
            fetch_intraday=lambda *a: {"status": "PROVIDER_ERROR", "bars": []},
        )
        == 1
    )
    assert observations(args) == before
    assert artifact(args)["failed"] == artifact(args)["pending"] == 1
