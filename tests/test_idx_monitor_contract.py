"""Offline release contracts: no market, model, or Telegram network calls.

These are release gates, not xfails: missing outage isolation/startup receipts must
remain visible to deployment review. Only temporary SQLite state is written.
"""

import ast
import inspect
import json
import sqlite3
from datetime import datetime, timedelta
from importlib.resources import files
from types import SimpleNamespace

import pytest

from tradingagents.idx_strategies import monitor, telegram_delivery
from tradingagents.idx_strategies.sessions import load_sessions


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("release contract attempted real network access")

    monkeypatch.setattr("requests.sessions.Session.request", denied)
    monkeypatch.setattr("socket.create_connection", denied)


@pytest.fixture
def harness(tmp_path):
    args = SimpleNamespace(
        db=str(tmp_path / "scan.db"),
        state_db=str(tmp_path / "state.db"),
        output_dir=str(tmp_path / "reports"),
        interval=300,
        ai_max_per_day=3,
        notify_startup=False,
    )
    calendar = load_sessions(files("tradingagents").joinpath("assets/idx_sessions_2026.json"))
    now = [datetime.fromisoformat("2026-10-28T10:00:00+07:00")]
    return args, calendar, now


def candidate(symbol="BBCA.JK"):
    return {
        "symbol": symbol,
        "strategy": "day",
        "session_date": "2026-10-28",
        "rubric_version": "idx-shadow-v1",
        "status": "SETUP",
        "entry_deadline": "2026-10-28T15:30:00+07:00",
    }


def cycle(harness, **overrides):
    args, calendar, now = harness
    options = {
        "scanner": lambda *a, **k: {},
        "settler": lambda *a, **k: {},
        "analyzer": lambda row: {},
        "sender": lambda *a, **k: None,
        "clock": lambda: now[0],
    }
    options.update(overrides)
    return monitor.run_cycle(args, calendar, **options)


@pytest.mark.parametrize("error", [ValueError, OSError, RuntimeError])
def test_calendar_outage_returns_fail_closed_without_restart_or_paid_calls(harness, error):
    args, _, now = harness

    class UnavailableCalendar:
        sessions = ()

        def get(self, day):
            raise error("calendar provider unavailable")

    calls = []
    for offset in (0, 300):
        now[0] = datetime.fromisoformat("2026-10-28T10:00:00+07:00") + timedelta(seconds=offset)
        result = monitor.run_cycle(
            args,
            UnavailableCalendar(),
            clock=lambda: now[0],
            scanner=lambda *a, **k: calls.append("scan") or {},
            settler=lambda *a, **k: calls.append("settle") or {},
            analyzer=lambda row: calls.append("paid") or {},
            sender=lambda *a, **k: calls.append("send"),
        )
        assert result["status"] != "OPEN"
    assert calls == []


def test_scan_and_settlement_outages_are_throttled_across_restarts(harness):
    args, _, now = harness
    calls = []

    def unavailable(kind):
        def invoke(*a, **k):
            calls.append((kind, now[0].isoformat()))
            raise OSError("provider unavailable")

        return invoke

    start = now[0]
    for offset in (0, 1, 299, 300):
        now[0] = start + timedelta(seconds=offset)
        result = cycle(harness, scanner=unavailable("scan"), settler=unavailable("settle"))
        assert result["status"] == "OPEN"
    assert [kind for kind, stamp in calls] == ["scan", "settle", "scan", "settle"]
    assert calls[0][1] != calls[2][1]
    with sqlite3.connect(args.state_db) as db:
        assert db.execute("select count(*) from jobs").fetchone()[0] == 0


@pytest.mark.parametrize("outcome", ["success", "failure", "interrupted"])
def test_daily_quota_persists_every_attempt_including_interrupted_reservations(harness, outcome):
    args, _, now = harness
    args.ai_max_per_day = 99  # Hard release ceiling remains three.
    attempts = []

    class SimulatedProcessStop(BaseException):
        pass

    def analyze(row):
        attempts.append(row["symbol"])
        if outcome == "failure":
            raise RuntimeError("model failed")
        if outcome == "interrupted":
            raise SimulatedProcessStop()
        return {"sol": {"status": "ok"}, "jev": {"status": "ok"}}

    for index in range(5):
        now[0] += timedelta(minutes=5)

        def scan(*a, i=index, **k):
            return {"assessments": [candidate(f"TEST{i}.JK")]}

        if outcome == "interrupted" and index < 3:
            with pytest.raises(SimulatedProcessStop):
                cycle(harness, scanner=scan, analyzer=analyze)
        else:
            cycle(harness, scanner=scan, analyzer=analyze)
    assert attempts == ["TEST0.JK", "TEST1.JK", "TEST2.JK"]
    with sqlite3.connect(args.state_db) as db:
        rows = db.execute("select reserved_day, status from jobs").fetchall()
    assert len(rows) == 3
    assert {row[0] for row in rows} == {"2026-10-28"}
    expected = {"success": "EXPIRED", "failure": "FAILED", "interrupted": "RESERVED"}[outcome]
    assert {row[1] for row in rows} == {expected}


def test_analysis_finishing_after_entry_deadline_cannot_become_actionable_buy(harness):
    args, _, now = harness
    row = candidate()
    row["entry_deadline"] = (now[0] + timedelta(seconds=1)).isoformat()
    sent = []

    def analyze(candidate_row):
        now[0] += timedelta(seconds=2)
        return {"recommendation": "BUY", "actionable": True}

    cycle(
        harness,
        scanner=lambda *a, **k: {"assessments": [row]},
        analyzer=analyze,
        sender=lambda *a: sent.append(a),
        chats=[123],
    )
    with sqlite3.connect(args.state_db) as db:
        status, raw = db.execute("select status, result from jobs").fetchone()
    result = json.loads(raw)
    assert status == result["status"] == "EXPIRED"
    assert result["actionable"] is False
    assert result.get("recommendation") != "BUY"
    assert datetime.fromisoformat(result["completed_at"]) >= datetime.fromisoformat(
        row["entry_deadline"]
    )
    assert sent == []


def test_already_expired_candidate_never_consumes_paid_attempt(harness):
    args, _, now = harness
    row = candidate()
    row["entry_deadline"] = now[0].isoformat()
    attempts = []
    cycle(
        harness,
        scanner=lambda *a, **k: {"assessments": [row]},
        analyzer=lambda row: attempts.append(row) or {},
    )
    assert attempts == []
    with sqlite3.connect(args.state_db) as db:
        assert db.execute("select count(*) from jobs").fetchone()[0] == 0


def test_closed_market_startup_network_receipt_is_labelled_not_live_candidate(harness):
    args, _, now = harness
    args.notify_startup = True
    now[0] = datetime.fromisoformat("2026-10-28T20:00:00+07:00")
    sent = []

    def sender(chat, payload):
        sent.append((chat, payload))
        return {"ok": True, "chat_id": chat, "message_id": 101}

    for offset in (0, 300):
        now[0] += timedelta(seconds=offset)
        result = cycle(harness, sender=sender, chats=[123, 123])
        assert result["status"] == "CLOSED"
    assert len(sent) == 1, "startup receipt must be delivered once despite restart/idle cycles"
    chat, payload = sent[0]
    assert chat == 123
    assert payload["kind"] == "startup"
    assert not payload.get("candidates")
    assert not payload.get("cards")
    assert payload.get("actionable", False) is False


def test_main_loop_runs_two_idle_cycles_at_distinct_times_without_polling(
    harness, monkeypatch, capsys
):
    args, _, now = harness
    now[0] = datetime.fromisoformat("2026-10-28T20:00:00+07:00")
    original = monitor.run_cycle
    starts, sleeps = [], []

    class StopLoop(BaseException):
        pass

    def run(args, calendar, **kwargs):
        starts.append(now[0])
        return original(
            args,
            calendar,
            clock=lambda: now[0],
            scanner=lambda *a, **k: {},
            settler=lambda *a, **k: {},
        )

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)
        if len(sleeps) == 2:
            raise StopLoop()

    monkeypatch.setattr(monitor, "run_cycle", run)
    monkeypatch.setattr("time.sleep", sleep)
    with pytest.raises(StopLoop):
        monitor.main(
            [
                "--db",
                args.db,
                "--state-db",
                args.state_db,
                "--output-dir",
                args.output_dir,
                "--interval",
                "300",
            ]
        )
    assert len(starts) == 2
    assert starts[1] - starts[0] == timedelta(seconds=300)
    assert sleeps == [300, 300]
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == 2
    assert all(record["status"] == "CLOSED" for record in records)


def test_failed_startup_receipt_is_not_marked_sent(harness):
    args, _, now = harness
    args.notify_startup = True
    now[0] = datetime.fromisoformat("2026-10-28T20:00:00+07:00")
    cycle(
        harness,
        chats=[123],
        sender=lambda *a: {"ok": False, "error": "transport_error_delivery_unknown"},
    )
    with sqlite3.connect(args.state_db) as db:
        (status,) = db.execute("select status from outbox where chat=123").fetchone()
    assert status != "SENT", "negative Telegram receipt must not become delivery evidence"


def test_shared_telegram_bot_only_sends_and_validates_network_receipt(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"chat": {"id": 123}, "message_id": 101}}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(telegram_delivery.requests, "post", post)
    receipt = telegram_delivery.send_text(
        "STARTUP connectivity receipt; not live candidates", "fake-token", 123
    )
    assert receipt == {"ok": True, "chat_id": 123, "message_id": 101}
    assert len(calls) == 1
    assert calls[0][0] == "https://api.telegram.org/botfake-token/sendMessage"
    assert calls[0][1]["allow_redirects"] is False
    forbidden = {"getUpdates", "setWebhook", "deleteWebhook", "run_polling", "start_polling"}
    for module in (monitor, telegram_delivery):
        tree = ast.parse(inspect.getsource(module))
        tokens = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        tokens |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not tokens.intersection(forbidden)
        assert not any(endpoint in text for endpoint in forbidden for text in literals)
