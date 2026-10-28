"""On-demand, bounded IDX research. No scheduler, inference, or orders."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.idx_strategies.reporting import json_safe, report, write_artifact

JAKARTA = ZoneInfo("Asia/Jakarta")


def _costs(args):
    from tradingagents.idx_strategies.models import Costs, net_reference_return

    fields = (args.buy_fee, args.sell_fee, args.buy_slippage, args.sell_slippage)
    if all(v is None for v in fields):
        return None
    if any(v is None for v in fields):
        raise ValueError("Supply all four fee/slippage fractions or none")
    costs = Costs(*(Decimal(v) for v in fields))
    net_reference_return(Decimal(100), Decimal(100), costs)
    return costs


def _daily_context(envelope, observed_at, calendar=None):
    from statistics import median

    from tradingagents.idx_strategies.features import ema

    if envelope.get("status") != "OK":
        return {"eligible": False, "reason": "daily_history_unavailable"}
    rows = [
        r
        for r in envelope["bars"]
        if str(r["date"]) < observed_at.astimezone(JAKARTA).date().isoformat()
    ]
    rows.sort(key=lambda r: str(r["date"]))
    if len(rows) < 21:
        return {"eligible": False, "reason": "daily_history_insufficient"}
    if calendar is not None:
        completed_days = [
            s.date.isoformat()
            for s in calendar.sessions
            if s.close < observed_at and s.date < observed_at.astimezone(JAKARTA).date()
        ]
        if len(completed_days) < 21:
            return {"eligible": False, "reason": "daily_calendar_history_insufficient"}
        if str(rows[-1]["date"]) != completed_days[-1]:
            return {"eligible": False, "reason": "daily_calendar_freshness_unverified"}
        required = set(completed_days[-21:])
        if not required.issubset({str(r["date"]) for r in rows}):
            return {"eligible": False, "reason": "daily_calendar_coverage_missing"}
    prices = [Decimal(str(r["close"])) for r in rows]
    turnover = median(Decimal(str(r["close"])) * Decimal(str(r["volume"])) for r in rows[-20:])
    ambiguity = bool(envelope.get("corporate_actions"))
    return {
        "eligible": prices[-1] >= 100 and turnover >= 10_000_000_000 and not ambiguity,
        "reason": "raw_close_turnover_action_gate",
        "ema20": str(ema(prices, 20)),
        "corporate_action_ambiguity": ambiguity,
        "median_turnover20_proxy": str(turnover),
        "last_completed_daily": str(rows[-1]["date"]),
    }


def scan(args, calendar, *, clock=None, fetch_intraday=None, fetch_daily=None):
    from tradingagents.idx_registry import load_registry
    from tradingagents.idx_strategies import provider, rules
    from tradingagents.idx_strategies.store import Store
    from tradingagents.idx_strategies.universe import select_symbols

    clock = clock or (lambda: datetime.now(UTC))
    fetch_intraday = fetch_intraday or provider.fetch_intraday
    fetch_daily = fetch_daily or provider.fetch_daily
    started = clock()
    session = calendar.get(started.astimezone(JAKARTA).date())
    costs = _costs(args)
    store = Store(args.db)
    try:
        issuers = sorted(load_registry()["issuers"], key=lambda row: row["symbol"])
        chosen, next_offset = select_symbols(issuers, store.rotation(), args.limit)
        assessments, snapshots = [], []
        failures = valid = 0
        for issuer in chosen:
            symbol = issuer["yahoo_symbol"] if isinstance(issuer, dict) else issuer
            received = clock()
            try:
                cutoff = min(received, session.close)
                cutoff = cutoff.replace(second=0, microsecond=0, minute=(cutoff.minute // 5) * 5)
                intraday = fetch_intraday(symbol, session.open, cutoff)
                daily = fetch_daily(symbol, received)
                received = clock()  # actual receipt time, never the pre-fetch timestamp
                snapshots.append(
                    {
                        "symbol": symbol,
                        "retrieved_at": received.isoformat(),
                        "payload": json_safe({"intraday": intraday, "daily": daily}),
                    }
                )
                if intraday.get("status") != "OK":
                    raise ValueError("intraday_" + intraday.get("status", "unavailable"))
                context = _daily_context(daily, received, calendar)
                valid += 1
                strategies = ("day", "overnight") if args.strategy == "both" else (args.strategy,)
                for strategy in strategies:
                    try:
                        following = (
                            calendar.next_session(session.date) if strategy == "overnight" else None
                        )
                    except ValueError:
                        following = None
                    fn = rules.assess_day if strategy == "day" else rules.assess_overnight
                    row = fn(
                        symbol=symbol,
                        bars=intraday["bars"],
                        session=session,
                        observed_at=received,
                        daily_context=context,
                        next_session=following,
                        costs=costs,
                    )
                    # Observation cannot precede durable-record preparation.
                    row.update(
                        observed_at=clock().isoformat(),
                        session_date=session.date.isoformat(),
                        rubric_version="idx-shadow-v1",
                    )
                    if costs is not None:
                        row["costs"] = json_safe(costs)
                    assessments.append(json_safe(row))
            except (ValueError, OSError, TypeError, KeyError) as exc:
                failures += 1
                for strategy in (
                    ("day", "overnight") if args.strategy == "both" else (args.strategy,)
                ):
                    assessments.append(
                        {
                            "symbol": symbol,
                            "strategy": strategy,
                            "status": "PROVIDER_ERROR",
                            "reasons": [type(exc).__name__],
                            "score": 0,
                            "observed_at": received.isoformat(),
                            "session_date": session.date.isoformat(),
                            "rubric_version": "idx-shadow-v1",
                        }
                    )
        completed = clock()
        for row in assessments:
            row["observed_at"] = completed.isoformat()
            if row.get("status") == "SETUP":
                deadline = datetime.fromisoformat(row["entry_deadline"])
                if completed >= deadline:
                    row.update(
                        status="UNOBSERVABLE",
                        reasons=[*row.get("reasons", []), "scan_completed_after_entry_deadline"],
                    )
        import hashlib

        calendar_payload = json_safe(
            {
                "source_url": calendar.source_url,
                "retrieved_at": calendar.retrieved_at,
                "sessions": calendar.sessions,
            }
        )
        calendar_hash = hashlib.sha256(
            json.dumps(calendar_payload, sort_keys=True).encode()
        ).hexdigest()
        for row in assessments:
            row["calendar_hash"] = calendar_hash
            row["calendar_snapshot"] = calendar_payload
        scan_row = {
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "source": "yfinance",
            "rubric_version": "idx-shadow-v1",
            "requested": len(chosen),
            "valid": valid,
            "failed": failures,
            "excluded": len(chosen) - valid - failures,
            "coverage": {
                "registry_count": len(issuers),
                "calendar_source": calendar.source_url,
                "costs_supplied": costs is not None,
                "request_budget": args.limit,
                "request_limit_scope": "ticker slots; max two history requests per ticker",
            },
        }
        # First persist the scan without actionable observations. Admission is
        # finalized only after its evidence transaction is durable.
        staged = [
            {**row, "status": "ADMITTING"} if row["status"] == "SETUP" else row
            for row in assessments
        ]
        ident = store.save_scan(
            scan_row,
            staged,
            snapshots,
            next_offset=None if failures == len(chosen) else next_offset,
        )
        for row in assessments:
            if row["status"] == "SETUP":
                row["observed_at"] = clock().isoformat()
                store.admit_observation(row, clock=clock)
        payload = report(
            {
                "scan_id": ident,
                **scan_row,
                "statuses": dict(Counter(r["status"] for r in assessments)),
                "assessments": assessments,
            }
        )
        write_artifact(args.output, payload)
        print(
            json.dumps(
                {
                    "scan_id": ident,
                    "requested": len(chosen),
                    "valid": valid,
                    "failed": failures,
                    "shortlist": payload["shortlist"],
                    "output": args.output,
                },
                ensure_ascii=False,
            )
        )
        return 1 if failures else 0
    finally:
        store.close()


def settle(args, calendar, *, clock=None, fetch_intraday=None):
    from tradingagents.idx_strategies import provider
    from tradingagents.idx_strategies.outcomes import advance_observation
    from tradingagents.idx_strategies.store import Store

    clock = clock or (lambda: datetime.now(UTC))
    fetch_intraday = fetch_intraday or provider.fetch_intraday
    store = Store(args.db)
    results = []
    failures = 0
    try:
        import hashlib

        fingerprint = hashlib.sha256(
            json.dumps(
                json_safe(
                    {
                        "source_url": calendar.source_url,
                        "retrieved_at": calendar.retrieved_at,
                        "sessions": calendar.sessions,
                    }
                ),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for observation in store.pending():
            if observation.get("calendar_hash") and observation["calendar_hash"] != fingerprint:
                failures += 1
                continue
            now = clock()
            try:
                start = datetime.fromisoformat(observation["observed_at"])
                envelope = fetch_intraday(observation["symbol"], start - timedelta(minutes=5), now)
                if envelope.get("status") != "OK":
                    failures += 1
                    continue  # transient provider failure must not destroy a pending observation
                updated = advance_observation(
                    observation, envelope["bars"], observed_at=clock(), calendar=calendar
                )
                store.update_observation(updated)
                results.append(json_safe(updated))
            except (ValueError, TypeError, OSError, KeyError):
                failures += 1
        payload = {
            "updated": results,
            "failed": failures,
            "pending": len(store.pending()),
            "mode": "hypothetical_reference_only",
        }
        write_artifact(args.output, payload)
        print(
            json.dumps(
                {
                    "updated": len(results),
                    "failed": failures,
                    "pending": payload["pending"],
                    "output": args.output,
                }
            )
        )
        return 1 if failures else 0
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="IDX research-only strategy scanner; no orders or paid AI"
    )
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "settle", "evaluate"):
        p = subs.add_parser(name)
        p.add_argument("--db", required=True)
        p.add_argument("--output", required=True)
        if name != "evaluate":
            p.add_argument("--sessions", required=True)
        if name == "scan":
            p.add_argument("--strategy", choices=("day", "overnight", "both"), default="both")
            p.add_argument("--limit", type=int, default=25)
            for field in ("buy-fee", "sell-fee", "buy-slippage", "sell-slippage"):
                p.add_argument("--" + field)
    args = parser.parse_args(argv)
    if args.command == "scan" and not 1 <= args.limit <= 25:
        parser.error("--limit must be between 1 and 25")
    if args.command != "evaluate":
        from tradingagents.idx_strategies.sessions import load_sessions

        try:
            calendar = load_sessions(args.sessions)
            if args.command == "scan":
                calendar.get(datetime.now(JAKARTA).date())
                _costs(args)
        except (ValueError, OSError, InvalidOperation) as exc:
            parser.error(str(exc))
    try:
        if args.command == "scan":
            return scan(args, calendar)
        if args.command == "settle":
            return settle(args, calendar)
        from tradingagents.idx_strategies.evaluation import evaluate
        from tradingagents.idx_strategies.store import Store

        if not Path(args.db).exists():
            parser.error("database not found")
        store = Store(args.db)
        try:
            payload = evaluate(store.observations())
        finally:
            store.close()
        write_artifact(args.output, payload)
        print(json.dumps(json_safe(payload), ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"RESEARCH_UNAVAILABLE: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
