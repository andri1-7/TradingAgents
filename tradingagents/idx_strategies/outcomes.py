"""Chronological hypothetical references, not order fills."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

from .models import Costs, net_reference_return

STEP = timedelta(minutes=5)
D = Decimal
TERMINAL = {"EXITED", "AMBIGUOUS", "UNOBSERVABLE", "ENTRY_REJECTED"}


def _stamp(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("aware timestamp required")
    return stamp


def _next_grid(stamp):
    return stamp.replace(second=0, microsecond=0, minute=(stamp.minute // 5) * 5) + STEP


def advance_observation(observation, bars, observed_at, costs=None, calendar=None):
    row = deepcopy(observation)
    if row["status"] in TERMINAL:
        return row
    now = _stamp(observed_at)
    signal = _stamp(row["observed_at"])
    deadline = _stamp(row["entry_deadline"])
    planned = _stamp(row["planned_exit"])
    known = sorted(
        (b for b in bars if b.symbol == row["symbol"] and b.end <= now), key=lambda b: b.start
    )
    from .bars import validate_bars

    try:
        # A pending entry may have no closed evidence yet; assess its close below.
        if known or row["status"] != "SETUP":
            known = validate_bars(known, now)
    except ValueError:
        return {**row, "status": "UNOBSERVABLE", "outcome_reason": "invalid_bars"}
    stop, target = D(row["stop"]), D(row["target"])
    if costs is None and row.get("costs"):
        costs = Costs(**{k: D(v) for k, v in row["costs"].items()})
    if row["status"] == "SETUP":
        expected = _next_grid(signal)
        if calendar is not None:
            session = calendar.get(
                signal.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Jakarta")).date()
            )
            slots = []
            for start, end in session.intervals:
                cursor = start
                while cursor + STEP <= end:
                    if cursor > signal:
                        slots.append(cursor)
                    cursor += STEP
            if not slots:
                return {**row, "status": "UNOBSERVABLE", "outcome_reason": "no_future_entry_slot"}
            expected = slots[0]
        entrybar = next((b for b in known if b.start == expected), None)
        # The deadline limits entry opens, not when their closed evidence arrives.
        if expected > deadline or (entrybar is None and now >= expected + STEP):
            return {**row, "status": "UNOBSERVABLE", "outcome_reason": "missing_first_entry_bar"}
        if entrybar is None:
            return row
        entry = entrybar.open
        risk = entry - stop
        if risk <= 0 or risk / entry > D(".02") or target <= entry:
            return {**row, "status": "ENTRY_REJECTED", "outcome_reason": "entry_gap_risk_gate"}
        if costs is not None:
            loss = -net_reference_return(entry, stop, costs)
            reward = net_reference_return(entry, target, costs)
            if loss <= 0 or reward / loss < D("1.5"):
                return {
                    **row,
                    "status": "ENTRY_REJECTED",
                    "outcome_reason": "entry_gap_net_reward_gate",
                }
        row.update(
            status="ENTERED",
            entry={
                "time": entrybar.start.isoformat(),
                "price": str(entry),
                "basis": "future_bar_open_reference_not_fill",
            },
        )
    entry_time = _stamp(row["entry"]["time"])
    entry = D(row["entry"]["price"])
    expected = entry_time
    for bar in known:
        if bar.start < entry_time:
            continue
        if calendar is not None and not any(
            start <= bar.start and bar.end <= end
            for session in calendar.sessions
            for start, end in session.intervals
        ):
            return {
                **row,
                "status": "UNOBSERVABLE",
                "outcome_reason": "bar_outside_continuous_session",
            }
        if bar.start != expected:
            # Session boundaries may skip lunch/overnight only when explicitly supplied.
            allowed = False
            if calendar:
                slots = []
                for sess in calendar.sessions:
                    for start, end in sess.intervals:
                        t = start
                        while t + STEP <= end:
                            if expected <= t <= bar.start:
                                slots.append(t)
                            t += STEP
                allowed = slots == [bar.start]
            if not allowed:
                return {**row, "status": "UNOBSERVABLE", "outcome_reason": "missing_post_entry_bar"}
        expected = bar.end
        if bar.start >= planned:
            if bar.start > planned + timedelta(minutes=10):
                return {**row, "status": "UNOBSERVABLE", "outcome_reason": "missed_time_exit"}
            return _exit(row, entry, bar.open, bar.start, "time_exit", costs)
        if bar.open <= stop:
            return _exit(row, entry, bar.open, bar.start, "gap_stop_reference", costs)
        if bar.open >= target:
            return _exit(row, entry, bar.open, bar.start, "gap_target_reference", costs)
        if bar.low <= stop and bar.high >= target:
            return {
                **row,
                "status": "AMBIGUOUS",
                "outcome_reason": "stop_and_target_same_bar",
                "gross_bounds": [str(stop / entry - 1), str(target / entry - 1)],
                "net_return": None,
            }
        if bar.low <= stop:
            return _exit(row, entry, stop, bar.end, "modeled_stop_touch_not_fill", costs)
        if bar.high >= target:
            return _exit(row, entry, target, bar.end, "modeled_target_touch_not_fill", costs)
    if now >= planned + timedelta(minutes=15):
        return {**row, "status": "UNOBSERVABLE", "outcome_reason": "missing_time_exit_bar"}
    return row


def _exit(row, entry, price, time, reason, costs):
    return {
        **row,
        "status": "EXITED",
        "exit": {"time": time.isoformat(), "price": str(price), "basis": reason},
        "gross_return": str(price / entry - 1),
        "net_return": str(net_reference_return(entry, price, costs)) if costs else None,
        "actual_holding_seconds": (time - _stamp(row["entry"]["time"])).total_seconds(),
        "planned_holding_seconds": (
            _stamp(row["planned_exit"]) - _stamp(row["entry"]["time"])
        ).total_seconds(),
        "hypothetical": True,
    }
