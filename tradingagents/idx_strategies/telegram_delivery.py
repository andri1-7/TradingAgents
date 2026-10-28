"""Send-only Telegram support notifications; no polling or bot configuration.

Credentials come exclusively from the existing tracker's dotenv file. Environment
variables and administrator IDs must never expand the authorized recipient list.
"""

from pathlib import Path

import requests
from dotenv import dotenv_values


def telegram_config(path: str | Path = "/srv/alt-whale-tracker/.env") -> tuple[str, list[int]]:
    """Read the existing bot and deduplicated authorized chats, failing closed."""
    try:
        values = dotenv_values(str(path), interpolate=False)
        token = (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chats = [
            int(item.strip()) for item in (values.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").split(",")
        ]
        if token and chats and all(chats):
            return token, list(dict.fromkeys(chats))
    except (OSError, ValueError, TypeError):
        pass
    raise ValueError("Telegram configuration unavailable") from None


def send_text(text: str, token: str, chat_id: int) -> dict:
    """Send once, as plain text; return a validated receipt or a fixed safe error.

    No automatic retries: a timeout can mean Telegram accepted the message. The
    caller's durable outbox owns delivery policy. Never return remote descriptions
    or exception strings because requests exceptions may contain the bot token.
    """
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 4096
        or not isinstance(token, str)
        or not token.strip()
        or type(chat_id) is not int
        or chat_id == 0
    ):
        return {"ok": False, "error": "invalid_input"}
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return {"ok": False, "error": "http_error"}
        payload = response.json()
        if payload.get("ok") is not True:
            return {"ok": False, "error": "telegram_rejected"}
        result = payload["result"]
        receipt_chat = result["chat"]["id"]
        message_id = result["message_id"]
        if (
            type(receipt_chat) is not int
            or receipt_chat != chat_id
            or type(message_id) is not int
            or message_id <= 0
        ):
            return {"ok": False, "error": "invalid_receipt"}
        return {"ok": True, "chat_id": receipt_chat, "message_id": message_id}
    except requests.RequestException:
        return {"ok": False, "error": "transport_error_delivery_unknown"}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"ok": False, "error": "invalid_response"}


def _compact(value, limit=120):
    """Bound each field separately, preserving the disclaimer and expiration."""
    text = " ".join(str(value if value is not None else "unknown").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _model_line(label, value):
    if not isinstance(value, dict):
        return f"{label}: unavailable"
    status = value.get("status", "error" if value.get("error") else "unavailable")
    model = _compact(value.get("model", "unknown"), 80)
    summary = _compact(
        value.get(
            "summary", value.get("text", value.get("rating", value.get("result", "unavailable")))
        ),
        300,
    )
    error = _compact(value.get("error", "none"), 160)
    provenance = _compact(value.get("provenance", "unknown"), 120)
    return f"{label}: {_compact(status, 40)} | {model} | {summary} | error: {error} | provenance: {provenance}"


def format_support(candidate: dict, analysis: dict) -> str:
    """Compact plain-text watch card; model views are separate, not trade orders.

    Candidate fields follow the strategy rule records. Analysis uses independent
    ``sol`` / ``jev`` dictionaries (status, model, summary, error, provenance).
    Missing provenance or expiration is explicit, never inferred.
    """
    sol = analysis.get("sol")
    if sol is None and ("rating" in analysis or "reports" in analysis):
        sol = {key: value for key, value in analysis.items() if key != "jev"}
    return "\n".join(
        [
            f"[SAHAM IDX] {_compact(candidate.get('status', 'WATCH'), 40)} | {_compact(candidate.get('symbol'))} | {_compact(candidate.get('strategy'))}",
            "Research support only — NOT an actual BUY or execution instruction.",
            f"Reference: {_compact(candidate.get('reference_price'), 40)} | stop: {_compact(candidate.get('stop'), 40)} | target: {_compact(candidate.get('target'), 40)}",
            f"Score (not probability): {_compact(candidate.get('score'), 40)}",
            f"Provenance: {_compact(candidate.get('provenance', candidate.get('provider', 'unknown')), 160)}",
            f"Expiry: {_compact(candidate.get('expires_at', candidate.get('entry_deadline', 'unknown')), 100)}",
            _model_line("Sol", sol),
            _model_line("Jev", analysis.get("jev")),
            f"Analysis errors: {_compact(analysis.get('errors', 'none'), 160)}",
        ]
    )
