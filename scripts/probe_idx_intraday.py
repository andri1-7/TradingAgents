"""Bounded authentic Yahoo probe, not a scanner or evidence of profitability."""
import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# Permit direct execution from an uninstalled checkout.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.idx_strategies.provider import fetch_intraday


def _json(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError('unsupported probe value')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', action='append', help='Exact XXXX.JK (max 3)')
    parser.add_argument('--start', required=True, type=datetime.fromisoformat)
    parser.add_argument('--end', required=True, type=datetime.fromisoformat)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    tickers = args.ticker or ['BBCA.JK', 'AADI.JK', 'UNTR.JK']
    if len(tickers) > 3:
        parser.error('probe is bounded to 3 ticker history requests')
    try:
        results = [fetch_intraday(symbol, args.start, args.end) for symbol in tickers]
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, default=_json, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return 0 if any(r['status'] == 'OK' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
