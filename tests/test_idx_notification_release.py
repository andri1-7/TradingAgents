from tradingagents.idx_strategies.monitor import _normalize_analysis, _notification_text
from tradingagents.idx_strategies.telegram_delivery import format_support


def test_expired_card_never_heading_watch():
    text = format_support({"status": "EXPIRED"}, {})
    assert "[SAHAM IDX] EXPIRED" in text
    assert "[SAHAM IDX] WATCH" not in text


def test_normalize_real_jev_shape_and_error():
    result = _normalize_analysis(
        {
            "status": "partial",
            "rating": "Hold",
            "error_class": "analysis_timeout",
            "daily_as_of_session": "2026-10-27",
            "jev": {
                "status": "completed",
                "result": {
                    "decision": {"choice": "HOLD", "confidence": 0.8},
                    "resolved_model": "jev-1.14.0",
                },
            },
        }
    )
    assert result["jev"]["summary"] == "HOLD"
    assert result["sol"]["model"] == "cx/gpt-6.1-sol"
    assert result["sol"]["error"] == "analysis_timeout"


def test_maximum_close_summary_with_three_cards_fits_telegram():
    model = {
        "status": "x" * 40,
        "model": "m" * 80,
        "summary": "s" * 300,
        "error": "e" * 160,
        "provenance": "p" * 120,
    }
    card = dict.fromkeys(("symbol", "strategy", "reference_price", "stop", "target", "score", "provenance", "entry_deadline"), "v" * 200)
    card.update(status="EXPIRED", analysis={"sol": model, "jev": model})
    counts = dict.fromkeys(("scans", "requested", "valid", "provider_errors", "runtime_errors", "settlement_errors", "ai_reserved", "ai_failed", "settled"), 123)
    text = _notification_text(
        {"kind": "daily_close", "session_date": "2026-10-28", "counts": counts, "cards": [card] * 3}
    )
    assert len(text) <= 4096
