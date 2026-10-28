"""Fresh, exact-symbol deterministic research checks. Never submits orders."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import provider, rules
from .cli import _daily_context
from .models import Costs

JAKARTA = ZoneInfo("Asia/Jakarta")


def revalidate_candidate(candidate, calendar, *, clock=None, fetch_intraday=None, fetch_daily=None):
    """Reassess only the original ticker/strategy, without extending its deadline."""
    clock = clock or (lambda: datetime.now(UTC))
    fetch_intraday = fetch_intraday or provider.fetch_intraday
    fetch_daily = fetch_daily or provider.fetch_daily
    started = clock()

    def reject(reason, assessment=None):
        return {
            "valid": False,
            "reason": reason,
            "assessment": assessment,
            "checked_at": received.isoformat(),
        }

    received = started
    try:
        if started.utcoffset() is None:
            return reject("aware_clock_required")
        symbol, strategy = candidate["symbol"], candidate["strategy"]
        if candidate["status"] != "SETUP" or strategy not in ("day", "overnight") or not symbol:
            return reject("invalid_candidate")
        deadline = datetime.fromisoformat(candidate["entry_deadline"])
        signal = datetime.fromisoformat(candidate["signal_time"])
        if deadline.utcoffset() is None or signal.utcoffset() is None:
            return reject("aware_candidate_times_required")
        if started >= deadline:
            return reject("entry_deadline_passed")
        session = calendar.get(started.astimezone(JAKARTA).date())
        if session.date != started.astimezone(JAKARTA).date() or not rules._in_session(
            started, session
        ):
            return reject("outside_market_interval")
        if signal > started or signal.astimezone(JAKARTA).date() != session.date:
            return reject("invalid_original_signal")
        costs = Costs(
            *(
                Decimal(str(candidate["costs"][key]))
                for key in ("buy_fee", "sell_fee", "buy_slippage", "sell_slippage")
            )
        )
        from .models import net_reference_return

        net_reference_return(Decimal(100), Decimal(100), costs)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        return reject("invalid_candidate_or_costs")
    cutoff = started.replace(second=0, microsecond=0, minute=started.minute // 5 * 5)
    try:
        try:
            intraday = fetch_intraday(symbol, session.open, cutoff)
            daily = fetch_daily(symbol, started)
        finally:
            # Receipt time is sampled even when a provider raises.
            received = clock()
        if received.utcoffset() is None or received < started:
            return reject("invalid_receipt_clock")
        if received >= deadline:
            return reject("entry_deadline_passed")
        if received.astimezone(JAKARTA).date() != session.date or not rules._in_session(
            received, session
        ):
            return reject("outside_market_interval")
        if intraday.get("status") != "OK" or daily.get("status") != "OK":
            return reject("provider_error")
        bars = intraday["bars"]
        if any(bar.symbol != symbol or bar.end > received for bar in bars):
            return reject("invalid_provider_evidence")
        following = calendar.next_session(session.date) if strategy == "overnight" else None
        fn = rules.assess_day if strategy == "day" else rules.assess_overnight
        assessment = fn(
            symbol=symbol,
            bars=bars,
            session=session,
            observed_at=received,
            daily_context=_daily_context(daily, received, calendar),
            costs=costs,
            next_session=following,
        )
        if assessment.get("symbol") != symbol or assessment.get("strategy") != strategy:
            return reject("assessment_identity_mismatch", assessment)
        if assessment.get("status") != "SETUP":
            return reject("rules_no_setup", assessment)
        new_signal = datetime.fromisoformat(assessment["signal_time"])
        new_deadline = datetime.fromisoformat(assessment["entry_deadline"])
        if new_signal < signal or new_signal > received or received - new_signal > rules.STEP:
            return reject("stale_or_future_signal", assessment)
        effective_deadline = min(deadline, new_deadline)
        assessment["entry_deadline"] = effective_deadline.isoformat()
        if received >= effective_deadline:
            return reject("entry_deadline_passed", assessment)
        reference = Decimal(assessment["reference_price"])
        original_stop = Decimal(str(candidate["stop"]))
        if not original_stop.is_finite() or original_stop <= 0 or reference <= original_stop:
            return reject("original_stop_invalidated", assessment)
        if (reference - original_stop) / reference > Decimal(".02"):
            return reject("original_stop_risk_exceeded", assessment)
        return {
            "valid": True,
            "reason": "fresh_setup",
            "assessment": assessment,
            "checked_at": received.isoformat(),
        }
    except Exception:
        # Provider/runtime/schema failures must never admit an actionable card.
        return reject("provider_or_assessment_error")
