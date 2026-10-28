from argparse import Namespace
from decimal import Decimal

import pytest

from tradingagents.idx_strategies.cli import _costs


def args(**kwargs):
    return Namespace(
        buy_fee=None,
        sell_fee=None,
        buy_slippage=None,
        sell_slippage=None,
        cost_profile="stockbit",
        **kwargs,
    )


def test_stockbit_profile_populates_four_cost_fractions():
    costs = _costs(args())
    assert costs.buy_fee == Decimal("0.0015")
    assert costs.sell_fee == Decimal("0.0025")
    assert costs.buy_slippage == costs.sell_slippage == Decimal("0.001")


def test_profile_rejects_ambiguous_manual_overrides():
    values = args()
    values.buy_fee = "0.002"
    with pytest.raises(ValueError, match="profile"):
        _costs(values)
