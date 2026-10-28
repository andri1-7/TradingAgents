"""JSON-safe stock research costs, separate from provenance and limitations.

Only stock transaction fees are broker facts. Slippage is an unmeasured
research assumption, not a Stockbit fact or promise of achievable execution.
The four-field Costs model has no notional/account context for fixed charges.
"""


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or name != "stockbit":
        raise ValueError("unknown cost profile; expected 'stockbit'")


def load_cost_profile(name: str) -> dict[str, str]:
    """Return exactly the four Costs fields as fresh, exact decimal strings.

    Only the case-sensitive name ``stockbit`` is supported. Invalid names
    (including non-strings) raise ValueError; no normalization is performed.
    Convert values with Decimal(value) when constructing models.Costs.
    See load_cost_profile_metadata for provenance, assumptions and exclusions.
    """
    _validate_name(name)
    return {
        "buy_fee": "0.0015",
        "sell_fee": "0.0025",
        "buy_slippage": "0.001",
        "sell_slippage": "0.001",
    }


def load_cost_profile_metadata(name: str) -> dict[str, str | dict[str, str]]:
    """Return fresh JSON-safe provenance; excludes notional-dependent charges."""
    _validate_name(name)
    return {
        "fees_url": (
            "https://help.stockbit.com/id/article/"
            "transaksi-saham-berapa-biaya-trading-di-stockbit-sekuritas-1lbkyq9"
        ),
        "fee_provenance": "Stockbit official help: stock buy 0.15%, sell 0.25%.",
        "assumptions": {
            "slippage_bps_per_side": "10",
            "slippage_basis": "Unmeasured research assumption; not a Stockbit fact or execution estimate.",
        },
        "exclusions": {
            "stamp_duty": (
                "IDR 10000 per daily trade confirmation when aggregate buy/sell "
                "notional exceeds IDR 10000000; not modeled without daily notional."
            ),
            "datafeed": (
                "Conditional monthly live datafeed charge; not modeled without "
                "monthly transaction notional and account billing context."
            ),
        },
    }
