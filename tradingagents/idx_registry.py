"""Offline IDX identity registry; registration is not monitoring or coverage proof."""
import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

BUNDLED = Path(__file__).parent / 'assets' / 'idx_issuers.json'


def validate(data):
    """Reject incomplete or ambiguous identity snapshots without repairing tokens."""
    if not isinstance(data, dict):
        raise ValueError('registry must be an object')
    for key in ('source_url', 'retrieved_at', 'coverage_status'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'missing {key}')
    if 'unverified' not in data['coverage_status']:
        raise ValueError('current completeness must remain explicitly unverified')
    rows = data.get('issuers')
    if not isinstance(rows, list) or not rows:
        raise ValueError('empty or invalid issuers')
    if type(data.get('declared_count')) is not int or data['declared_count'] != len(rows):
        raise ValueError('declared_count does not match rows')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid issuer')
        symbol = row.get('symbol')
        if not isinstance(symbol, str) or not re.fullmatch('[A-Z]{4}', symbol) or symbol in seen:
            raise ValueError('invalid or duplicate symbol')
        if not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError('empty issuer name')
        if row.get('yahoo_symbol') != symbol + '.JK':
            raise ValueError('invalid Yahoo mapping')
        seen.add(symbol)
    return data


def load_registry(path=None):
    return validate(json.loads(Path(path or BUNDLED).read_text(encoding='utf-8')))


def import_registry(source, output, source_url, source_as_of=None):
    """Import a complete response snapshot, never certify its current freshness."""
    raw = json.loads(Path(source).read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or not isinstance(raw.get('data'), list):
        raise ValueError('expected IDX data array')
    rows = raw['data']
    for key in ('recordsTotal', 'recordsFiltered'):
        if key in raw and (type(raw[key]) is not int or raw[key] != len(rows)):
            raise ValueError(f'{key} does not match rows; partial import refused')
    issuers = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid source issuer')
        symbol = row.get('Code', row.get('KodeEmiten'))
        issuers.append({'symbol': symbol, 'name': row.get('Name', row.get('NamaEmiten')),
                        'yahoo_symbol': symbol + '.JK' if isinstance(symbol, str) else None})
    data = validate({'source_url': source_url, 'source_as_of': source_as_of,
                     'retrieved_at': datetime.now(UTC).isoformat(),
                     'coverage_status': 'imported_snapshot_current_completeness_unverified',
                     'declared_count': len(issuers), 'issuers': issuers})
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description='Registry emiten IDX; no network or paid analyses')
    parser.add_argument('--registry', help='Custom validated registry snapshot')
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--format', choices=('json', 'csv', 'tickers'), default='csv')
    listing.add_argument('--search', default='')
    commands.add_parser('info')
    importing = commands.add_parser('import')
    importing.add_argument('--input', required=True)
    importing.add_argument('--output', required=True)
    importing.add_argument('--source-url', required=True)
    importing.add_argument('--source-as-of')
    args = parser.parse_args(argv)
    try:
        if args.command == 'import':
            data = import_registry(args.input, args.output, args.source_url, args.source_as_of)
            print(json.dumps({k: v for k, v in data.items() if k != 'issuers'}, ensure_ascii=False))
            return 0
        data = load_registry(args.registry)
        if args.command == 'info':
            print(json.dumps({k: v for k, v in data.items() if k != 'issuers'}, ensure_ascii=False, indent=2))
            return 0
        rows = [r for r in data['issuers'] if args.search.casefold() in (r['symbol'] + ' ' + r['name']).casefold()]
        if args.format == 'json':
            print(json.dumps({**data, 'issuers': rows, 'matched_count': len(rows)}, ensure_ascii=False, indent=2))
        elif args.format == 'tickers':
            print('\n'.join(r['yahoo_symbol'] for r in rows))
        else:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=('symbol', 'name', 'yahoo_symbol'))
            writer.writeheader()
            writer.writerows(rows)
            print(buffer.getvalue(), end='')
        print(f"Registry: {len(rows)}/{data['declared_count']}; {data['coverage_status']}", file=sys.stderr)
        return 0
    except (ValueError, OSError, TypeError) as exc:
        print(f'REGISTRY_UNAVAILABLE: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
