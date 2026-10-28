"""Deterministic research policies. SETUP is never an executable-entry claim.

Cost-adjusted target solves reward/net stop loss = 1.5 at the provisional
reference close. Future observed entry must be re-gated by the outcome engine.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from .bars import validate_bars
from .features import relative_volume, vwap

D = Decimal
STEP = timedelta(minutes=5)
RUBRIC_VERSION = "idx-rules-v1"


def rank_candidates(assessments, limit=3):
    """Select watch cards only; preserve input assessments for full persistence.

    Scores are strategy-specific evidence rubrics, not calibrated probabilities.
    The combined presentation order follows the explicit v1 policy.
    """
    maximum = max(0, min(3, limit))
    ranked = sorted(
        (r for r in assessments if r["status"] == "SETUP"),
        key=lambda r: (-D(str(r["score"])), r["symbol"], r["strategy"]),
    )
    seen, selected = set(), []
    for row in ranked:
        if row["symbol"] not in seen:
            selected.append(row)
            seen.add(row["symbol"])
    return selected[:maximum]


def _record(symbol, strategy):
    return {
        "symbol": symbol,
        "strategy": strategy,
        "status": "NO_SETUP",
        "reasons": [],
        "evidence": {"rubric_version": RUBRIC_VERSION},
        "score": 0,
        "signal_time": None,
        "reference_price": None,
        "stop": None,
        "target": None,
        "entry_deadline": None,
        "planned_exit": None,
    }


def _reject(result, reason, insufficient=False):
    result.update(status="INSUFFICIENT_DATA" if insufficient else "NO_SETUP", reasons=[reason])
    return result


def _in_session(moment, session):
    return any(start <= moment < end for start, end in session.intervals)


def _required(session, cutoff):
    windows = []
    for start, end in session.intervals:
        if start >= cutoff:
            break
        stop = min(end, cutoff)
        # Only complete grid bars are required; never bridge a lunch break.
        stop = start + STEP * ((stop - start) // STEP)
        if stop > start:
            windows.append((start, stop))
    return windows


def _prepare(result, symbol, bars, session, observed_at, daily_context, cutoff):
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return None, _reject(result, "aware_observation_required", True)
    if not daily_context or "eligible" not in daily_context:
        return None, _reject(result, "daily_context_required", True)
    if daily_context.get("eligible") is not True:
        return None, _reject(result, "daily_ineligible")
    if daily_context.get("corporate_action_ambiguity"):
        return None, _reject(result, "corporate_action_ambiguity")
    try:
        selected = [
            b
            for b in bars
            if b.symbol == symbol
            and b.end <= cutoff
            and any(start <= b.start and b.end <= end for start, end in session.intervals)
        ]
        known = validate_bars(selected, observed_at=cutoff)
    except (ValueError, TypeError, AttributeError):
        return None, _reject(result, "invalid_required_bars", True)
    if len(known) < 21:
        return None, _reject(result, "preceding_20_bars_required", True)
    if cutoff - known[-1].end > STEP:
        return None, _reject(result, "stale_signal", True)
    expected = []
    for start, end in _required(session, cutoff):
        cursor = start
        while cursor < end:
            expected.append(cursor)
            cursor += STEP
    if [b.start for b in known] != expected:
        return None, _reject(result, "missing_required_bars", True)
    if cutoff - known[-1].end > STEP:
        return None, _reject(result, "stale_signal", True)
    return known, None


def _features(known):
    try:
        return vwap(known), relative_volume(known)
    except ValueError:
        return None, None


def _finish(result, known, stop, costs, deadline, planned_exit):
    last = known[-1]
    risk = last.close - stop
    result.update(
        signal_time=last.end.isoformat(),
        reference_price=str(last.close),
        stop=str(stop),
        entry_deadline=deadline.isoformat(),
        planned_exit=planned_exit.isoformat(),
    )
    if risk <= 0 or risk / last.close > D(".02"):
        return _reject(result, "invalid_risk_distance")
    result["evidence"].update(
        risk_fraction=str(risk / last.close),
        gross_1_5r_target=str(last.close + D("1.5") * risk),
        provisional_reference=True,
        entry_risk_recheck_required=True,
    )
    if costs is None:
        result["evidence"]["net_eligibility"] = "unknown"
        return _reject(result, "costs_required", True)
    try:
        buy_fee, sell_fee, buy_slip, sell_slip = (
            D(str(getattr(costs, key)))
            for key in ("buy_fee", "sell_fee", "buy_slippage", "sell_slippage")
        )
        if not all(x.is_finite() and 0 <= x < 1 for x in (buy_fee, sell_fee, buy_slip, sell_slip)):
            raise ValueError("invalid costs")
        paid = last.close * (1 + buy_slip) * (1 + buy_fee)
        sell_factor = (1 - sell_slip) * (1 - sell_fee)
        net_stop_loss = paid - stop * sell_factor
        target = (paid + D("1.5") * net_stop_loss) / sell_factor
    except (ValueError, InvalidOperation, AttributeError):
        return _reject(result, "invalid_costs", True)
    result.update(status="SETUP", target=str(target))
    result["evidence"].update(
        net_eligibility="verified_provisional_reference",
        net_stop_loss=str(net_stop_loss),
        net_reward_risk="1.5",
        target_formula="(paid + 1.5 * (paid - stop * sell_factor)) / sell_factor",
    )
    return result


def assess_day(
    *,
    symbol,
    bars,
    session,
    observed_at,
    daily_context,
    next_session=None,
    event_coverage="unknown",
    adverse_event=False,
    costs=None,
):
    """Opening-range breakout followed by the latest closed-bar retest.

    Freshness permits at most five minutes; a historical retest is not replayed.
    Decision windows exclude lunch, using exact supplied continuous intervals.
    """
    result = _record(symbol, "day")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return _reject(result, "aware_observation_required", True)
    if not (
        session.open + timedelta(minutes=30) <= observed_at <= session.close - timedelta(minutes=30)
    ) or not _in_session(observed_at, session):
        return _reject(result, "outside_decision_window")
    cutoff = min(observed_at, session.close)
    known, failure = _prepare(result, symbol, bars, session, observed_at, daily_context, cutoff)
    if failure:
        return failure
    # Freshness is measured from the observed clock, not the historical signal.
    if observed_at - known[-1].end > STEP:
        return _reject(result, "stale_signal", True)
    last = known[-1]
    high = max(b.high for b in known[:6])
    result["evidence"]["opening_range_high"] = str(high)
    if not any(b.close > high for b in known[6:-1]):
        return _reject(result, "prior_breakout_required")
    if not (
        abs(last.low - high) <= high * D(".002") and last.close > high and last.close > last.open
    ):
        return _reject(result, "valid_later_retest_required")
    value, relative = _features(known)
    result["evidence"].update(vwap=str(value), relative_volume=str(relative))
    if value is None or relative is None:
        return _reject(result, "undefined_volume_features", True)
    if last.close <= value:
        return _reject(result, "close_not_above_vwap")
    if relative < D("1.5"):
        return _reject(result, "relative_volume_below_1_5")
    components = {
        "pattern": 3,
        "trend": 2,
        "participation": 2 if relative < 2 else 3,
        "risk": 1 if (last.close - last.low) / last.close > D(".01") else 2,
    }
    result["evidence"]["score_components"] = components
    result["score"] = sum(components.values())
    return _finish(
        result,
        known,
        last.low,
        costs,
        min(last.end + STEP * 2, session.close - timedelta(minutes=30)),
        session.close - timedelta(minutes=15),
    )


def assess_overnight(
    *,
    symbol,
    bars,
    session,
    observed_at,
    daily_context,
    next_session=None,
    event_coverage="unknown",
    adverse_event=False,
    costs=None,
):
    """Assess the fixed close-minus-30-minute instant in a five-minute window."""
    result = _record(symbol, "overnight")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return _reject(result, "aware_observation_required", True)
    decision = session.close - timedelta(minutes=30)
    if not decision <= observed_at < decision + STEP or not _in_session(decision, session):
        return _reject(result, "outside_decision_window")
    if next_session is None or next_session.open <= session.close:
        return _reject(result, "next_session_required", True)
    if adverse_event:
        return _reject(result, "known_adverse_event")
    known, failure = _prepare(result, symbol, bars, session, observed_at, daily_context, decision)
    if failure:
        return failure
    last = known[-1]
    try:
        daily_ema = D(str(daily_context["ema20"]))
        if not daily_ema.is_finite() or daily_ema <= 0:
            raise ValueError("invalid EMA")
    except (KeyError, ValueError, InvalidOperation):
        return _reject(result, "daily_ema20_required", True)
    if last.close <= daily_ema:
        return _reject(result, "close_not_above_ema20")
    if last.close / daily_ema - 1 > D(".02"):
        return _reject(result, "ema_overextension")
    value, relative = _features(known)
    if value is None or relative is None:
        return _reject(result, "undefined_volume_features", True)
    high, low = max(b.high for b in known), min(b.low for b in known)
    location = (last.close - low) / (high - low) if high > low else D(0)
    result["evidence"].update(
        ema20=str(daily_ema),
        vwap=str(value),
        relative_volume=str(relative),
        close_location=str(location),
        event_coverage=event_coverage,
        holding_calendar_days=(next_session.date - session.date).days,
    )
    if last.close <= value:
        return _reject(result, "close_not_above_vwap")
    if location < D(".75"):
        return _reject(result, "weak_close_location")
    if relative < D("1.5"):
        return _reject(result, "relative_volume_below_1_5")
    components = {
        "trend": 3,
        "close_location": 2 if location < D(".9") else 3,
        "participation": 2 if relative < 2 else 3,
        "risk": 1,
    }
    result["evidence"]["score_components"] = components
    result["score"] = sum(components.values())
    result = _finish(
        result,
        known,
        min(b.low for b in known[-6:]),
        costs,
        decision + STEP,
        next_session.open + timedelta(minutes=30),
    )
    if result["status"] == "SETUP":
        result["reasons"].append("sector_exposure_unassessed")
        if event_coverage != "known":
            result["reasons"].append("event_coverage_unknown")
        if (next_session.date - session.date).days > 1:
            result["reasons"].append("weekend_or_holiday_holding_span")
    return result
