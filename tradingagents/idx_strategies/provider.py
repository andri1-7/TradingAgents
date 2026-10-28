"""Compatibility boundary: vendor implementation lives in the data layer."""

import sys

from tradingagents.dataflows.vendors import idx_intraday

sys.modules[__name__] = idx_intraday
