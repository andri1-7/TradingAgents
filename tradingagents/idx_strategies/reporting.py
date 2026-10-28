"""Research artifacts, never executable recommendations."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def report(payload):
    result = json_safe(payload)
    seen = set()
    cards = []
    for row in sorted(
        result.get("assessments", []),
        key=lambda x: (-x.get("score", 0), x["symbol"], x["strategy"]),
    ):
        if row.get("status") not in ("SETUP", "ENTERED") or row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        cards.append({**row, "label": "WATCH" if row["status"] == "SETUP" else "SHADOW_ENTERED"})
        if len(cards) == 3:
            break
    return {
        **result,
        "shortlist": cards,
        "disclaimer": "Observational research only. Reference prices are not executable fills; no orders or profit claims.",
    }


def write_artifact(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
