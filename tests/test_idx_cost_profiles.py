"""Stockbit stock research costs: exact fractions, not execution estimates."""

import json
from dataclasses import fields
from decimal import Decimal
from importlib import import_module

import pytest

from tradingagents.idx_strategies.models import Costs


@pytest.mark.parametrize("name", ["", "Stockbit", " stockbit", "stockbit ", "unknown", None, 1, True, [], {}])
def test_invalid_profile_names_are_rejected(name):
    module = import_module("tradingagents.idx_strategies.cost_profiles")
    with pytest.raises(ValueError, match="cost profile"):
        module.load_cost_profile(name)


def test_metadata_separates_verified_fees_from_assumptions_and_exclusions():
    module = import_module("tradingagents.idx_strategies.cost_profiles")
    metadata = module.load_cost_profile_metadata("stockbit")
    assert metadata["fees_url"] == (
        "https://help.stockbit.com/id/article/"
        "transaksi-saham-berapa-biaya-trading-di-stockbit-sekuritas-1lbkyq9"
    )
    assert metadata["fee_provenance"] == "Stockbit official help: stock buy 0.15%, sell 0.25%."
    assert metadata["assumptions"] == {
        "slippage_bps_per_side": "10",
        "slippage_basis": "Unmeasured research assumption; not a Stockbit fact or execution estimate.",
    }
    assert metadata["exclusions"] == {
        "stamp_duty": "IDR 10000 per daily trade confirmation when aggregate buy/sell notional exceeds IDR 10000000; not modeled without daily notional.",
        "datafeed": "Conditional monthly live datafeed charge; not modeled without monthly transaction notional and account billing context.",
    }
    assert json.loads(json.dumps(metadata)) == metadata


@pytest.mark.parametrize("name", ["", "Stockbit", None, [], {}])
def test_metadata_rejects_invalid_profile_names(name):
    module = import_module("tradingagents.idx_strategies.cost_profiles")
    with pytest.raises(ValueError, match="cost profile"):
        module.load_cost_profile_metadata(name)


def test_profile_results_do_not_leak_mutations():
    module = import_module("tradingagents.idx_strategies.cost_profiles")
    costs = module.load_cost_profile("stockbit")
    costs["buy_fee"] = "1"
    assert module.load_cost_profile("stockbit")["buy_fee"] == "0.0015"
    metadata = module.load_cost_profile_metadata("stockbit")
    metadata["assumptions"]["slippage_bps_per_side"] = "999"
    assert module.load_cost_profile_metadata("stockbit")["assumptions"]["slippage_bps_per_side"] == "10"


def test_stockbit_costs_are_exact_json_safe_cost_fields():
    module = import_module("tradingagents.idx_strategies.cost_profiles")
    profile = module.load_cost_profile("stockbit")
    assert profile == {
        "buy_fee": "0.0015",
        "sell_fee": "0.0025",
        "buy_slippage": "0.001",
        "sell_slippage": "0.001",
    }
    assert set(profile) == {field.name for field in fields(Costs)}
    assert json.loads(json.dumps(profile)) == profile
    costs = Costs(**{key: Decimal(value) for key, value in profile.items()})
    assert costs.buy_fee == Decimal("0.0015")
    assert costs.sell_fee == Decimal("0.0025")
