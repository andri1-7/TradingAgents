"""Separate hypothetical outcome cohorts; never actual portfolio PnL."""

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def _timestamp(value):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return stamp if stamp.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _session_date(row):
    try:
        value = row.get("session_date")
        if isinstance(value, str):
            return date.fromisoformat(value)
        if type(value) is date:
            return value
    except (TypeError, ValueError):
        pass
    stamp = _timestamp(row.get("observed_at"))
    return stamp.astimezone(ZoneInfo("Asia/Jakarta")).date() if stamp else None


def _summarize(observations):
    output = {"mode": "hypothetical_reference_only", "strategies": {}}
    for strategy in ("day", "overnight"):
        rows = [r for r in observations if r["strategy"] == strategy]
        closed = [r for r in rows if r["status"] == "EXITED"]
        net = [Decimal(r["net_return"]) for r in closed if r.get("net_return") is not None]
        gross = [Decimal(r["gross_return"]) for r in closed if r.get("gross_return") is not None]
        output["strategies"][strategy] = {
            "observations": len(rows),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "observable_closed": len(closed),
            "net_observable": len(net),
            "net_unknown": len(closed) - len(net),
            "gross_mean": str(sum(gross) / len(gross)) if gross else None,
            "net_mean": str(sum(net) / len(net)) if net else None,
            "net_positive_fraction": str(Decimal(sum(x > 0 for x in net)) / len(net))
            if net
            else None,
            "ambiguous_bounds": [r.get("gross_bounds") for r in rows if r["status"] == "AMBIGUOUS"],
            "warning": "Correlated reference outcomes; not executable fills, calibrated profit odds, or strategy proof.",
        }
    return output


def evaluate(observations):
    """Keep pooled compatibility summaries and fixed chronological research cohorts."""
    rows = list(observations)
    dated = [(_session_date(row), row) for row in rows]
    dates = sorted({day for day, _ in dated if day is not None})
    unclassified = [row for day, row in dated if day is None]
    boundary = len(dates) * 4 // 5 if len(dates) > 1 else len(dates)
    discovery_dates, holdout_dates = dates[:boundary], dates[boundary:]
    discovery = [row for day, row in dated if day in discovery_dates]
    holdout = [row for day, row in dated if day in holdout_dates]
    stamps = [_timestamp(row.get("observed_at")) for row in holdout]
    known_stamps = [stamp for stamp in stamps if stamp is not None]
    first_holdout = (
        min(known_stamps).astimezone(ZoneInfo("Asia/Jakarta"))
        if (stamps and len(known_stamps) == len(stamps))
        else None
    )
    cutoff = first_holdout
    if cutoff is None and holdout_dates:
        cutoff = datetime.combine(
            holdout_dates[0], datetime.min.time(), tzinfo=ZoneInfo("Asia/Jakarta")
        )
    purged = []
    if cutoff:
        safe = []
        for row in discovery:
            exit_time = _timestamp(row.get("planned_exit"))
            if exit_time is None:
                unclassified.append(row)
            elif exit_time >= cutoff:
                purged.append(row)
            else:
                safe.append(row)
        discovery = safe
    output = _summarize(rows)
    output["split"] = {
        "status": "available" if holdout_dates else "insufficient_data",
        "discovery_dates": [day.isoformat() for day in discovery_dates],
        "holdout_dates": [day.isoformat() for day in holdout_dates],
        "holdout_first_observation": first_holdout.isoformat() if first_holdout else None,
        "boundary_basis": "observed_at"
        if first_holdout
        else ("conservative_session_start" if cutoff else None),
        "purge_cutoff": cutoff.isoformat() if cutoff else None,
    }
    output["cohorts"] = {
        "discovery": _summarize(discovery),
        "holdout": _summarize(holdout),
        "purged": _summarize(purged),
        "unclassified": _summarize(unclassified),
    }
    return output
