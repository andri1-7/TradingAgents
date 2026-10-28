"""Durable research monitor. No orders; inference never changes rule eligibility."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")


def _connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS outbox (
          event TEXT, chat TEXT, payload TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, error TEXT, PRIMARY KEY(event,chat));
        CREATE TABLE IF NOT EXISTS cycles (day TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ticks (kind TEXT PRIMARY KEY, stamp REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
          symbol TEXT, strategy TEXT, session_date TEXT, rubric TEXT,
          reserved_day TEXT NOT NULL, status TEXT NOT NULL, error TEXT, result TEXT,
          PRIMARY KEY(symbol,strategy,session_date,rubric));
    """)
    if "receipt" not in {row[1] for row in db.execute("PRAGMA table_info(outbox)")}:
        db.execute("ALTER TABLE outbox ADD COLUMN receipt TEXT")
        db.commit()
    return db


def _claim_tick(db, kind, now, interval):
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT stamp FROM ticks WHERE kind=?", (kind,)).fetchone()
        if row and now.timestamp() - row[0] < interval:
            return False
        db.execute("INSERT OR REPLACE INTO ticks VALUES (?,?)", (kind, now.timestamp()))
    return True


def _invoke(fn, args, calendar, clock):
    Path(args.output).unlink(missing_ok=True)
    result = fn(args, calendar, clock=clock)
    if isinstance(result, dict):
        return result
    # Existing CLI writes a report and returns an exit code.
    return json.loads(Path(args.output).read_text())


def _reserve(db, row, now, cap):
    key = tuple(row[k] for k in ("symbol", "strategy", "session_date", "rubric_version"))
    day = now.astimezone(JAKARTA).date().isoformat()
    with db:
        db.execute("BEGIN IMMEDIATE")
        used = db.execute("SELECT count(*) FROM jobs WHERE reserved_day=?", (day,)).fetchone()[0]
        if used >= min(3, max(0, cap)):
            return None
        cursor = db.execute(
            "INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,NULL,NULL)", (*key, day, "RESERVED")
        )
        return key if cursor.rowcount else None


def _enqueue(db, event, chats, payload):
    with db:
        for chat in set(map(str, chats)):
            db.execute(
                "INSERT OR IGNORE INTO outbox(event,chat,payload,status) VALUES (?,?,?,?)",
                (event, chat, json.dumps(payload), "PENDING"),
            )


def _deliver(db, sender, clock):
    if sender is None:
        return
    # Serialize concurrent workers. A crash after Telegram accepts but before COMMIT
    # remains ambiguous and may duplicate on retry; Telegram has no idempotency key.
    for event, chat in db.execute(
        "SELECT event,chat FROM outbox WHERE status='PENDING'"
    ).fetchall():
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload,status FROM outbox WHERE event=? AND chat=?", (event, chat)
            ).fetchone()
            if row[1] != "PENDING":
                continue
            try:
                payload = json.loads(row[0])
                if payload.get("kind") == "analysis":
                    candidate = payload.get("candidate", {})
                    try:
                        expired = clock() >= datetime.fromisoformat(candidate["entry_deadline"])
                    except (ValueError, KeyError, TypeError):
                        expired = True
                    if expired:
                        candidate.update(status="EXPIRED", actionable=False)
                receipt = sender(int(chat), payload)
                if receipt is False or (
                    isinstance(receipt, dict) and receipt.get("ok") is not True
                ):
                    raise RuntimeError("delivery_rejected")
                db.execute(
                    "UPDATE outbox SET status='SENT', attempts=attempts+1,error=NULL,receipt=? WHERE event=? AND chat=?",
                    (
                        json.dumps(
                            {
                                "chat_id": int(chat),
                                "sent_at": clock().isoformat(),
                                "response": receipt,
                            },
                            default=str,
                        ),
                        event,
                        chat,
                    ),
                )
            except Exception as exc:
                db.execute(
                    "UPDATE outbox SET attempts=attempts+1,error=? WHERE event=? AND chat=?",
                    (type(exc).__name__, event, chat),
                )


def _close_summary(db, calendar, now, chats):
    for session in calendar.sessions:
        if now < session.close + timedelta(minutes=30):
            continue
        day = session.date.isoformat()
        rows = db.execute("SELECT payload FROM cycles WHERE day=?", (day,)).fetchall()
        if not rows:
            continue
        counts = {
            "scans": 0,
            "requested": 0,
            "valid": 0,
            "provider_errors": 0,
            "settled": 0,
            "settlement_errors": 0,
            "runtime_errors": 0,
        }
        for (raw,) in rows:
            cycle = json.loads(raw)
            for key in counts:
                counts[key] += cycle.get(key, 0)
        counts["ai_reserved"] = db.execute(
            "SELECT count(*) FROM jobs WHERE reserved_day=?", (day,)
        ).fetchone()[0]
        counts["ai_failed"] = db.execute(
            "SELECT count(*) FROM jobs WHERE reserved_day=? AND status='FAILED'", (day,)
        ).fetchone()[0]
        cards = []
        for symbol, strategy, status, raw in db.execute(
            "SELECT symbol,strategy,status,result FROM jobs WHERE reserved_day=? ORDER BY symbol,strategy LIMIT 3",
            (day,),
        ):
            saved = json.loads(raw) if raw else {}
            cards.append(
                {
                    "symbol": symbol,
                    "strategy": strategy,
                    "status": status,
                    "actionable": False,
                    "analysis": _normalize_analysis(saved.get("analysis", {})),
                }
            )
        _enqueue(
            db,
            "close:" + day,
            chats,
            {"kind": "daily_close", "session_date": day, "counts": counts, "cards": cards},
        )


def run_cycle(
    args,
    calendar,
    *,
    scanner=None,
    settler=None,
    analyzer=None,
    sender=None,
    clock=None,
    chats=(),
    revalidator=None,
):
    clock = clock or (lambda: datetime.now(UTC))
    now = clock()
    db = _connect(args.state_db)
    result = {"status": "CLOSED", "analyzed": 0, "errors": []}
    try:
        if getattr(args, "notify_startup", False):
            _enqueue(
                db,
                "startup:v1",
                chats,
                {
                    "kind": "startup",
                    "mode": "research_only",
                    "ai_daily_cap": min(3, args.ai_max_per_day),
                },
            )
        try:
            session = calendar.get(now.astimezone(JAKARTA).date())
        except (ValueError, OSError, RuntimeError) as exc:
            day = now.astimezone(JAKARTA).date()
            if (
                isinstance(exc, (OSError, RuntimeError))
                or not calendar.sessions
                or day < calendar.sessions[0].date
                or day > calendar.sessions[-1].date
            ):
                result.update(status="CALENDAR_UNAVAILABLE", errors=["MissingSession"])
                _enqueue(
                    db,
                    "calendar_health:"
                    + (calendar.sessions[-1].date.isoformat() if calendar.sessions else "empty"),
                    chats,
                    {"kind": "calendar_health"},
                )
            return result
        active = any(start <= now < end for start, end in session.intervals)
        live = session.open <= now <= session.close + timedelta(minutes=30)
        if scanner is None or settler is None:
            from . import cli

            scanner = scanner or cli.scan
            settler = settler or cli.settle
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        common = {
            "db": args.db,
            "limit": 25,
            "strategy": "both",
            "cost_profile": "stockbit",
            "buy_fee": None,
            "sell_fee": None,
            "buy_slippage": None,
            "sell_slippage": None,
        }
        interval = max(300, getattr(args, "interval", 300))
        payload = {}
        metrics = {}
        if active and _claim_tick(db, "scan", now, interval):
            scan_args = SimpleNamespace(**common, output=str(Path(args.output_dir) / "scan.json"))
            try:
                payload = _invoke(scanner, scan_args, calendar, clock)
                metrics.update(
                    scans=1,
                    requested=payload.get("requested", 0),
                    valid=payload.get("valid", 0),
                    provider_errors=payload.get("failed", 0),
                )
            except Exception as exc:
                result["errors"].append(type(exc).__name__)
        if live and _claim_tick(db, "settle", now, interval):
            settle_args = SimpleNamespace(
                **common, output=str(Path(args.output_dir) / "settle.json")
            )
            try:
                settled = _invoke(settler, settle_args, calendar, clock)
                metrics.update(
                    settled=len(settled.get("updated", [])),
                    settlement_errors=settled.get("failed", 0),
                )
            except Exception as exc:
                result["errors"].append(type(exc).__name__)
        attempted = False
        for row in [r for r in payload.get("assessments", []) if r.get("status") == "SETUP"][:3]:
            if attempted:
                break
            try:
                if clock() >= datetime.fromisoformat(row["entry_deadline"]):
                    continue
                key = _reserve(db, row, clock(), args.ai_max_per_day)
                if not key:
                    continue
                attempted = True
                try:
                    if analyzer is None:
                        from .ai_runner import run_analysis

                        analyzer = run_analysis
                    analysis = analyzer(row)
                    if analysis.get("status") == "unavailable":
                        error = analysis.get("error_class", "analysis_unavailable")
                        error = (
                            error
                            if error
                            in ("analysis_timeout", "analysis_unavailable", "invalid_candidate")
                            else "analysis_unavailable"
                        )
                        with db:
                            db.execute(
                                "UPDATE jobs SET status=?,error=?,result=? WHERE symbol=? AND strategy=? AND session_date=? AND rubric=?",
                                (
                                    "FAILED",
                                    error,
                                    json.dumps({"analysis": analysis}, default=str),
                                    *key,
                                ),
                            )
                        result["errors"].append(error)
                        continue
                    # No exact-ticker fresh rule verification adapter yet: fail closed.
                    safe = {
                        "analysis": analysis,
                        "status": "EXPIRED",
                        "actionable": False,
                        "reason": "fresh_exact_ticker_setup_unverified",
                        "completed_at": clock().isoformat(),
                    }
                    verified_row = dict(row)
                    if clock() < datetime.fromisoformat(row["entry_deadline"]):
                        try:
                            if revalidator is None:
                                from .revalidation import revalidate_candidate

                                revalidator = revalidate_candidate
                            verification = revalidator(row, calendar, clock=clock)
                            fresh = verification.get("assessment", {})
                            if (
                                verification.get("valid") is True
                                and fresh.get("symbol") == row["symbol"]
                                and fresh.get("strategy") == row["strategy"]
                                and clock() < datetime.fromisoformat(row["entry_deadline"])
                            ):
                                verified_row = {**fresh, "entry_deadline": row["entry_deadline"]}
                                safe.update(
                                    status="WATCH_REVALIDATED",
                                    reason="fresh_exact_ticker_setup_verified",
                                )
                        except Exception as exc:
                            result["errors"].append(type(exc).__name__)
                    verified_row.update(status=safe["status"], actionable=False)
                    if clock() < datetime.fromisoformat(row["entry_deadline"]):
                        _enqueue(
                            db,
                            "analysis:" + ":".join(key),
                            chats,
                            {
                                "kind": "analysis",
                                "candidate": verified_row,
                                "analysis": _normalize_analysis(analysis),
                            },
                        )
                    with db:
                        db.execute(
                            "UPDATE jobs SET status=?,result=? WHERE symbol=? AND strategy=? AND session_date=? AND rubric=?",
                            (safe["status"], json.dumps(safe, default=str), *key),
                        )
                    result["analyzed"] += 1
                except Exception as exc:
                    with db:
                        db.execute(
                            "UPDATE jobs SET status=?,error=? WHERE symbol=? AND strategy=? AND session_date=? AND rubric=?",
                            ("FAILED", type(exc).__name__, *key),
                        )
                    result["errors"].append(type(exc).__name__)
            except (ValueError, KeyError, TypeError) as exc:
                result["errors"].append(type(exc).__name__)
        if metrics or result["errors"]:
            metrics["runtime_errors"] = len(result["errors"])
            with db:
                db.execute(
                    "INSERT INTO cycles VALUES (?,?)",
                    (session.date.isoformat(), json.dumps(metrics)),
                )
        result["status"] = "OPEN" if active else "CLOSED"
        return result
    finally:
        _close_summary(db, calendar, clock(), chats)
        _deliver(db, sender, clock)
        db.close()


def main(argv=None):
    import argparse
    import time
    from importlib.resources import files

    from .sessions import load_sessions

    parser = argparse.ArgumentParser(description="Persistent IDX research monitor; no orders")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--db", required=True)
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--sessions", default=str(files("tradingagents").joinpath("assets/idx_sessions_2026.json"))
    )
    parser.add_argument("--telegram-env", default="/srv/alt-whale-tracker/.env")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--ai-max-per-day", type=int, default=3)
    parser.add_argument("--notify-startup", action="store_true")
    args = parser.parse_args(argv)
    if args.interval < 300 or not 0 <= args.ai_max_per_day <= 3:
        parser.error("interval must be >=300; ai-max-per-day must be between 0 and 3")
    if Path(args.db).resolve() == Path(args.state_db).resolve():
        parser.error("db and state-db must be distinct")
    calendar = load_sessions(args.sessions)
    sender, chats = None, ()
    # --notify-startup enables configured Telegram delivery. No polling or bot edits.
    if args.notify_startup:
        from .telegram_delivery import send_text, telegram_config

        token, chats = telegram_config(args.telegram_env)

        def sender(chat, payload):
            text = _notification_text(payload)
            receipt = send_text(text, token, chat)
            if not isinstance(receipt, dict) or receipt.get("ok") is not True:
                raise RuntimeError("telegram_rejected")
            return receipt

    while True:
        try:
            result = run_cycle(args, calendar, sender=sender, chats=chats)
            print(json.dumps(result), flush=True)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(json.dumps({"status": "ERROR", "error": type(exc).__name__}), flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


def _normalize_analysis(analysis):
    sol = analysis.get("sol") or {
        key: analysis.get(key) for key in ("status", "model", "error", "provenance")
    }
    sol.setdefault("summary", analysis.get("rating", "unavailable"))
    sol["model"] = sol.get("model") or "cx/gpt-6.1-sol"
    sol["error"] = sol.get("error") or analysis.get("error_class", "none")
    sol["provenance"] = sol.get("provenance") or (
        "daily context through " + str(analysis.get("daily_as_of_session", "unknown"))
    )
    jev = dict(analysis.get("jev") or {})
    raw = jev.get("result")
    if isinstance(raw, dict):
        jev.setdefault("summary", raw.get("decision", {}).get("choice", "unavailable"))
        jev.setdefault("model", raw.get("resolved_model", raw.get("requested_model", "jev-latest")))
    else:
        jev.setdefault("summary", raw or "unavailable")
    jev.setdefault("error", jev.get("error_class", "none"))
    jev.setdefault("provenance", "TypeSafe independent supporting decision")
    return {"sol": sol, "jev": jev, "errors": analysis.get("errors", [])}


def _notification_text(payload):
    kind = payload["kind"]
    if kind == "analysis":
        from .telegram_delivery import format_support

        return (
            payload["candidate"]["status"]
            + "\n"
            + format_support(payload["candidate"], payload["analysis"])
        )
    if kind == "startup":
        return (
            "IDX monitor aktif: riset day + overnight; Stockbit. "
            "Maksimal 25 ticker per rotasi/5 menit; AI pendukung maksimal "
            f"{payload['ai_daily_cap']} analisis/hari. Bukan perintah transaksi."
        )
    if kind == "calendar_health":
        return (
            "IDX monitor idle: cakupan kalender resmi tidak tersedia; pengambilan data dihentikan."
        )
    counts = payload["counts"]
    lines = [
        f"IDX ringkasan {payload['session_date']}",
        f"Scan {counts['scans']} | ticker {counts['requested']} | valid {counts['valid']}",
        f"Error provider {counts['provider_errors']} | runtime {counts['runtime_errors']} | settlement {counts['settlement_errors']}",
        f"AI reservasi {counts['ai_reserved']} | gagal {counts['ai_failed']} | settlement {counts['settled']}",
    ]
    for card in payload["cards"][:3]:
        lines.append(
            f"{str(card['symbol'])[:20]} {str(card['strategy'])[:20]}: {str(card['status'])[:40]} — tidak actionable"
        )
        view = card.get("analysis", {})
        lines.append(
            " | ".join(
                label + ": " + str(view.get(key, {}).get("summary", "unavailable"))[:160]
                for label, key in (("Sol", "sol"), ("Jev", "jev"))
            )
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
