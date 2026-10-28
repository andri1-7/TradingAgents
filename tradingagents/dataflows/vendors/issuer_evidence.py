"""Curated official issuer disclosures, not reconstructed historical ratios.

Only the get_fundamentals company-overview route may use this evidence.
No statement APIs or network requests are provided here.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tradingagents.dataflows.errors import VendorUnavailableError

_ASSET = Path(__file__).resolve().parents[2] / "assets" / "issuer_evidence.json"


def get_issuer_fundamentals(ticker: str, as_of_date: str | None = None) -> str:
    """Return bounded primary-source excerpts and their availability convention."""
    if not isinstance(ticker, str) or ticker.upper() not in {"BBCA", "BBCA.JK"}:
        raise VendorUnavailableError("Issuer evidence has no coverage for this ticker; BBCA only.")
    try:
        if not isinstance(as_of_date, str):
            raise ValueError("missing date")
        cutoff = date.fromisoformat(as_of_date)
        if cutoff.isoformat() != as_of_date:
            raise ValueError("noncanonical date")
    except (TypeError, ValueError) as exc:
        raise VendorUnavailableError("Issuer evidence requires an explicit YYYY-MM-DD as_of_date.") from exc

    evidence = json.loads(_ASSET.read_text(encoding="utf-8"))["BBCA"]
    if cutoff < date.fromisoformat(evidence["available_after"]):
        raise VendorUnavailableError(
            "Issuer evidence withheld: no allowlisted disclosure available by this as_of_date."
        )
    quotes = "\n".join(f'> {quote}' for quote in evidence["excerpts"])
    return (
        f"Official issuer evidence: BBCA — {evidence['issuer']}\n"
        f"Source: {evidence['source_url']}\n"
        f"Source type: {evidence['source_type']}; not a financial statement.\n"
        f"available_after: {evidence['available_after']} ({evidence['timezone']}, inclusive)\n"
        f"availability_basis: {evidence['availability_basis']}\n"
        "Scope: company overview enrichment only; no annual/quarterly statement, "
        "historical valuation, PE, EPS, or Yahoo snapshot reconstructed.\n"
        f"Exact source excerpts (original units):\n{quotes}"
    )
