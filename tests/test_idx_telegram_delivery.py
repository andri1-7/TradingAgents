"""Safe send-only Telegram delivery; all credentials and network calls are fake."""

from unittest.mock import Mock

import pytest


def test_config_uses_only_dotenv_authorized_chat_ids(monkeypatch):
    from tradingagents.idx_strategies import telegram_delivery as delivery

    read = Mock(
        return_value={
            "TELEGRAM_BOT_TOKEN": "123:fake-token",
            "TELEGRAM_ALLOWED_CHAT_IDS": "-100123,456,-100123",
            "TELEGRAM_ADMIN_IDS": "999",
        }
    )
    monkeypatch.setattr(delivery, "dotenv_values", read)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "999")
    assert delivery.telegram_config() == ("123:fake-token", [-100123, 456])
    read.assert_called_once_with("/srv/alt-whale-tracker/.env", interpolate=False)


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"TELEGRAM_ALLOWED_CHAT_IDS": "123"},
        {"TELEGRAM_BOT_TOKEN": "fake"},
        {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_ALLOWED_CHAT_IDS": "123,private-secret"},
        {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_ALLOWED_CHAT_IDS": "0"},
    ],
)
def test_config_refuses_missing_or_invalid_without_secret_errors(monkeypatch, values):
    from tradingagents.idx_strategies import telegram_delivery as delivery

    monkeypatch.setattr(delivery, "dotenv_values", Mock(return_value=values))
    with pytest.raises(ValueError, match="Telegram configuration unavailable") as caught:
        delivery.telegram_config("/fake.env")
    assert "private-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_config_sanitizes_read_failure(monkeypatch):
    from tradingagents.idx_strategies import telegram_delivery as delivery

    monkeypatch.setattr(delivery, "dotenv_values", Mock(side_effect=OSError("private-secret")))
    with pytest.raises(ValueError, match="Telegram configuration unavailable"):
        delivery.telegram_config()


def test_send_plaintext_with_explicit_safety_and_receipt(monkeypatch):
    from tradingagents.idx_strategies import telegram_delivery as delivery

    response = Mock(status_code=200)
    response.json.return_value = {"ok": True, "result": {"chat": {"id": -100123}, "message_id": 42}}
    post = Mock(return_value=response)
    monkeypatch.setattr(delivery.requests, "post", post)
    assert delivery.send_text("[SAHAM IDX] <WATCH>", "123:fake", -100123) == {
        "ok": True,
        "chat_id": -100123,
        "message_id": 42,
    }
    post.assert_called_once_with(
        "https://api.telegram.org/bot123:fake/sendMessage",
        json={"chat_id": -100123, "text": "[SAHAM IDX] <WATCH>", "disable_web_page_preview": True},
        timeout=15,
        allow_redirects=False,
    )


@pytest.mark.parametrize("kind", ["network", "json", "api", "http", "receipt", "redirect"])
def test_send_failures_never_expose_token_or_api_description(monkeypatch, kind):
    import requests

    from tradingagents.idx_strategies import telegram_delivery as delivery

    response = Mock(status_code=200)
    response.json.return_value = {
        "ok": False,
        "description": "secret-token in URL",
        "error_code": 403,
    }
    if kind == "http":
        response.status_code = 503
    if kind == "redirect":
        response.status_code = 302
    if kind == "receipt":
        response.json.return_value = {"ok": True, "result": {"chat": {"id": 999}, "message_id": 42}}
    if kind == "json":
        response.json.side_effect = ValueError("secret-token")
    post = Mock(return_value=response)
    if kind == "network":
        post.side_effect = requests.RequestException(
            "https://api.telegram.org/botsecret-token/sendMessage"
        )
    monkeypatch.setattr(delivery.requests, "post", post)
    result = delivery.send_text("watch", "secret-token", -100123)
    assert result["ok"] is False
    assert result["error"]
    assert "secret-token" not in str(result)
    assert "message_id" not in result
    assert post.call_count == 1


@pytest.mark.parametrize(
    "text,token,chat",
    [("", "token", 1), ("a" * 4097, "token", 1), ("hi", "", 1), ("hi", "token", 0)],
)
def test_send_invalid_input_does_not_call_network(monkeypatch, text, token, chat):
    from tradingagents.idx_strategies import telegram_delivery as delivery

    post = Mock()
    monkeypatch.setattr(delivery.requests, "post", post)
    assert delivery.send_text(text, token, chat)["ok"] is False
    post.assert_not_called()


def test_format_watch_separates_models_provenance_and_expiry():
    from tradingagents.idx_strategies.telegram_delivery import format_support

    candidate = {
        "symbol": "BBCA.JK",
        "strategy": "pullback",
        "score": 70,
        "reference_price": 9000,
        "stop": 8800,
        "target": 9400,
        "entry_deadline": "2026-10-28T10:00:00+07:00",
        "provider": "yahoo",
    }
    analysis = {
        "sol": {"status": "ok", "summary": "wait for confirmation", "model": "sol-model"},
        "jev": {"status": "error", "error": "provider timeout", "model": "jev-model"},
    }
    text = format_support(candidate, analysis)
    assert text.startswith("[SAHAM IDX] WATCH")
    for value in [
        "BBCA.JK",
        "pullback",
        "9000",
        "8800",
        "9400",
        "Sol:",
        "Jev:",
        "wait for confirmation",
        "error",
        "provider timeout",
        "sol-model",
        "jev-model",
        "yahoo",
        "2026-10-28T10:00:00+07:00",
        "NOT an actual BUY",
    ]:
        assert value in text
    assert len(text) <= 3500


def test_format_accepts_analyzer_rating_and_separate_jev_result():
    from tradingagents.idx_strategies.telegram_delivery import format_support

    text = format_support(
        {"symbol": "BBCA.JK"},
        {
            "status": "completed",
            "rating": "Hold",
            "model": "cx/gpt-6.1-sol",
            "jev": {
                "status": "completed",
                "result": {"decision": {"choice": "WAIT", "confidence": 0.8}},
            },
            "errors": ["news unavailable"],
        },
    )
    assert "Hold" in text and "WAIT" in text
    assert "news unavailable" in text
    assert "cx/gpt-6.1-sol" in text


def test_format_stays_compact_without_losing_safety_or_expiry():
    from tradingagents.idx_strategies.telegram_delivery import format_support

    text = format_support(
        {"symbol": "X" * 5000, "strategy": "Y" * 5000, "entry_deadline": "EXPIRES-HERE"},
        {"sol": {"summary": "😀" * 10000}, "jev": {"error": "E" * 10000}},
    )
    assert len(text.encode("utf-16-le")) // 2 <= 3500
    assert "EXPIRES-HERE" in text
    assert "Sol:" in text and "Jev:" in text
    assert "NOT an actual BUY" in text
    missing = format_support({}, {})
    assert "unavailable" in missing and "Expiry: unknown" in missing
