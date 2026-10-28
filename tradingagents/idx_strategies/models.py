"""Exact immutable shared research records and Decimal cost arithmetic."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SETUP = "SETUP"
    ENTERED = "ENTERED"
    ENTRY_REJECTED = "ENTRY_REJECTED"
    EXITED = "EXITED"
    AMBIGUOUS = "AMBIGUOUS"
    UNOBSERVABLE = "UNOBSERVABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True)
class Bar:
    symbol: str
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Costs:
    buy_fee: Decimal
    sell_fee: Decimal
    buy_slippage: Decimal
    sell_slippage: Decimal


def net_reference_return(entry: Decimal, exit: Decimal, costs: Costs) -> Decimal:
    values = (entry, exit, costs.buy_fee, costs.sell_fee, costs.buy_slippage, costs.sell_slippage)
    if not all(x.is_finite() for x in values):
        raise ValueError("non-finite price or cost")
    if entry <= 0 or exit <= 0:
        raise ValueError("prices must be positive")
    if not all(Decimal(0) <= x < Decimal(1) for x in values[2:]):
        raise ValueError("costs must be fractions in [0,1)")
    paid = entry * (1 + costs.buy_slippage) * (1 + costs.buy_fee)
    received = exit * (1 - costs.sell_slippage) * (1 - costs.sell_fee)
    return received / paid - 1
