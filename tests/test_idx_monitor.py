import json
import sqlite3
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

from tradingagents.idx_strategies.sessions import load_sessions


def setup(tmp_path):
    from tradingagents.idx_strategies import monitor

    args = SimpleNamespace(
        db=str(tmp_path / "scan.db"),
        state_db=str(tmp_path / "state.db"),
        output_dir=str(tmp_path / "reports"),
        interval=300,
        ai_max_per_day=3,
        notify_startup=False,
    )
    calendar = load_sessions(files("tradingagents").joinpath("assets/idx_sessions_2026.json"))
    return monitor, args, calendar


def test_calendar_gates_scans_and_bounds_settlement(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    calls = []
    for stamp in [
        "2026-10-28T08:59:00+07:00",
        "2026-10-28T12:30:00+07:00",
        "2026-10-28T16:20:00+07:00",
        "2026-10-28T17:00:00+07:00",
        "2026-10-31T10:00:00+07:00",
        "2026-11-09T10:00:00+07:00",
    ]:
        monitor.run_cycle(
            args,
            calendar,
            clock=lambda stamp=stamp: datetime.fromisoformat(stamp),
            scanner=lambda a, c, **k: calls.append("scan") or {},
            settler=lambda a, c, **k: calls.append("settle") or {},
        )
    assert calls == ["settle", "settle"]


def candidate(symbol="BBCA.JK", **extra):
    return dict(
        symbol=symbol,
        strategy="day",
        session_date="2026-10-28",
        rubric_version="idx-shadow-v1",
        status="SETUP",
        entry_deadline="2026-10-28T15:30:00+07:00",
        **extra,
    )


def test_restart_throttle_and_atomic_daily_reservations_include_failures(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    now = [datetime.fromisoformat("2026-10-28T10:00:00+07:00")]
    scans, paid = [], []

    def scan(a, c, **kw):
        scans.append((a.limit, a.strategy, a.cost_profile))
        return {"assessments": [candidate(str(i)) for i in range(5)]}

    def analyze(row):
        paid.append(row["symbol"])
        raise RuntimeError("SECRET_TOKEN")

    for offset in [0, 1, 300, 600]:
        now[0] = datetime.fromisoformat("2026-10-28T10:00:00+07:00") + timedelta(seconds=offset)
        monitor.run_cycle(
            args,
            calendar,
            scanner=scan,
            settler=lambda *a, **k: {},
            analyzer=analyze,
            clock=lambda: now[0],
        )
    assert scans == [(25, "both", "stockbit")] * 3
    assert paid == ["0", "1", "2"]
    db = sqlite3.connect(args.state_db)
    assert db.execute("select count(*) from jobs").fetchone()[0] == 3
    assert {r[0] for r in db.execute("select error from jobs")} == {"RuntimeError"}
    assert b"SECRET_TOKEN" not in Path(args.state_db).read_bytes()


def test_outbox_per_chat_retry_and_daily_summary_no_scan_spam(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    args.notify_startup = True
    now = [datetime.fromisoformat("2026-10-28T10:00:00+07:00")]
    sent = []
    failing = [True]

    def sender(chat, payload):
        if chat == 2 and failing[0]:
            raise OSError("SECRET")
        sent.append((chat, payload))

    def cycle():
        return monitor.run_cycle(
            args,
            calendar,
            scanner=lambda *a, **k: {"requested": 25, "valid": 24, "failed": 1},
            settler=lambda *a, **k: {"updated": [], "failed": 0, "pending": 2},
            analyzer=lambda r: {},
            sender=sender,
            chats=[1, 2, 1],
            clock=lambda: now[0],
        )

    cycle()
    assert [x[0] for x in sent] == [1]
    failing[0] = False
    cycle()
    assert [x[0] for x in sent] == [1, 2]
    now[0] += timedelta(minutes=5)
    cycle()
    assert len(sent) == 2
    now[0] = datetime.fromisoformat("2026-10-28T16:40:00+07:00")
    cycle()
    cycle()
    assert len(sent) == 4
    assert sent[2][1]["kind"] == "daily_close"
    assert sent[2][1]["counts"]["requested"] == 50
    assert sent[2][1]["counts"]["provider_errors"] == 2
    assert len(sent[2][1]["cards"]) <= 3
    db = sqlite3.connect(args.state_db)
    assert db.execute("select count(*) from outbox where status='SENT'").fetchone()[0] == 4


def test_analysis_is_supporting_and_always_expired_without_exact_ticker_refresh(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    now = [datetime.fromisoformat("2026-10-28T10:00:00+07:00")]
    calls = []

    def analyzer(row):
        calls.append(row["symbol"])
        now[0] = datetime.fromisoformat("2026-10-28T15:31:00+07:00")
        return {"action": "BUY", "confidence": 1}

    monitor.run_cycle(
        args,
        calendar,
        scanner=lambda *a, **k: {
            "assessments": [candidate(), {**candidate("NO.JK"), "status": "NO_SETUP"}]
        },
        settler=lambda *a, **k: {},
        analyzer=analyzer,
        revalidator=lambda *a, **k: {"valid": False},
        clock=lambda: now[0],
    )
    assert calls == ["BBCA.JK"]
    db = sqlite3.connect(args.state_db)
    status, raw = db.execute("select status,result from jobs").fetchone()
    assert status == "EXPIRED"
    assert json.loads(raw)["actionable"] is False


def test_cli_once_packaged_calendar_and_conservative_defaults(tmp_path, monkeypatch):
    monitor, args, calendar = setup(tmp_path)
    seen = []
    monkeypatch.setattr(monitor, "run_cycle", lambda a, c, **kw: seen.append((a, c)) or {})
    assert (
        monitor.main(
            [
                "--once",
                "--db",
                args.db,
                "--state-db",
                args.state_db,
                "--output-dir",
                args.output_dir,
            ]
        )
        == 0
    )
    parsed, packaged = seen[0]
    assert parsed.interval == 300
    assert parsed.ai_max_per_day == 3
    assert parsed.telegram_env == "/srv/alt-whale-tracker/.env"
    assert packaged.sessions[-1].date.isoformat() == "2026-11-06"


def test_outbox_retains_real_receipt_and_rejects_negative_ack(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    args.notify_startup = True
    replies = [{"ok": False}, {"ok": True, "result": {"message_id": 42, "chat": {"id": 7}}}]

    def cycle():
        monitor.run_cycle(
            args,
            calendar,
            scanner=lambda *a, **k: {},
            settler=lambda *a, **k: {},
            sender=lambda chat, payload: replies.pop(0),
            chats=[7],
            clock=lambda: datetime.fromisoformat("2026-10-31T10:00:00+07:00"),
        )

    cycle()
    db = sqlite3.connect(args.state_db)
    assert db.execute("select status from outbox").fetchone()[0] == "PENDING"
    cycle()
    status, raw = db.execute("select status,receipt from outbox").fetchone()
    receipt = json.loads(raw)
    assert status == "SENT"
    assert receipt["chat_id"] == 7
    assert receipt["response"]["result"]["message_id"] == 42
    assert receipt["sent_at"] == "2026-10-31T10:00:00+07:00"


def test_calendar_out_of_coverage_one_health_notice_and_no_fetch(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    sent = []
    for _ in range(2):
        result = monitor.run_cycle(
            args,
            calendar,
            chats=[1],
            sender=lambda c, p: sent.append(p),
            clock=lambda: datetime.fromisoformat("2026-11-09T10:00:00+07:00"),
            scanner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetch")),
            settler=lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetch")),
        )
    assert result["status"] == "CALENDAR_UNAVAILABLE"
    assert [p["kind"] for p in sent] == ["calendar_health"]


def test_at_most_one_slow_analysis_per_cycle_and_no_cached_starvation(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    paid = []
    monitor.run_cycle(
        args,
        calendar,
        scanner=lambda *a, **k: {"assessments": [candidate(str(i)) for i in range(3)]},
        settler=lambda *a, **k: {},
        analyzer=lambda r: paid.append(r["symbol"]) or {},
        revalidator=lambda *a, **k: {"valid": False},
        clock=lambda: datetime.fromisoformat("2026-10-28T10:00:00+07:00"),
    )
    assert paid == ["0"]


def test_close_card_preserves_separate_sol_jev_support(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    now = [datetime.fromisoformat("2026-10-28T10:00:00+07:00")]
    sent = []

    def cycle(scanner, analyzer):
        monitor.run_cycle(
            args,
            calendar,
            scanner=scanner,
            settler=lambda *a, **k: {},
            analyzer=analyzer,
            sender=lambda c, p: sent.append(p),
            chats=[1],
            revalidator=lambda *a, **k: {"valid": False},
            clock=lambda: now[0],
        )

    cycle(
        lambda *a, **k: {"assessments": [candidate()]},
        lambda r: {
            "status": "OK",
            "rating": "WATCH",
            "reports": {"summary": "sol view"},
            "jev": {"status": "OK", "result": "jev view"},
        },
    )
    now[0] = datetime.fromisoformat("2026-10-28T16:40:00+07:00")
    cycle(lambda *a, **k: {}, lambda r: {})
    close = next(payload for payload in sent if payload["kind"] == "daily_close")
    card = close["cards"][0]
    assert card["analysis"]["sol"]["summary"] == "WATCH"
    assert card["analysis"]["jev"]["summary"] == "jev view"
    assert card["status"] == "EXPIRED"
    assert "Sol:" in monitor._notification_text(close)


def test_exact_ticker_revalidation_and_immediate_support_delivery(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    seen, sent = [], []

    def verify(row, cal, *, clock):
        seen.append(row["symbol"])
        return {
            "valid": True,
            "assessment": {**row, "reference_price": "123"},
            "checked_at": clock().isoformat(),
        }

    monitor.run_cycle(
        args,
        calendar,
        scanner=lambda *a, **k: {"assessments": [candidate()]},
        settler=lambda *a, **k: {},
        analyzer=lambda r: {"status": "OK", "rating": "WATCH"},
        revalidator=verify,
        chats=[1],
        sender=lambda c, p: sent.append(p),
        clock=lambda: datetime.fromisoformat("2026-10-28T10:00:00+07:00"),
    )
    assert seen == ["BBCA.JK"]
    assert sent[0]["kind"] == "analysis"
    assert sent[0]["candidate"]["status"] == "WATCH_REVALIDATED"
    assert sent[0]["candidate"]["reference_price"] == "123"
    assert sent[0]["candidate"]["actionable"] is False
    assert "Sol:" in monitor._notification_text(sent[0])
