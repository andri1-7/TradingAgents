"""Yahoo transport is replaced with synthetic frames; no unit-test HTTP."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from tradingagents.idx_strategies import provider


def test_probe_writes_actual_adapter_envelopes(tmp_path, monkeypatch):
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('idx_probe', Path(__file__).parents[1] / 'scripts/probe_idx_intraday.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake(monkeypatch, frame())
    output = tmp_path / 'probe.json'
    assert module.main(['--ticker', 'BBCA.JK', '--start', START.isoformat(),
                        '--end', END.isoformat(), '--output', str(output)]) == 0
    result = json.loads(output.read_text())
    assert len(result) == 1
    assert result[0]['bars'][0]['open'] == '100'
    assert result[0]['bars'][0]['start'] == START.isoformat()


def frame():
    return pd.DataFrame({'Open': [100, 105], 'High': [110, 115], 'Low': [90, 95],
                         'Close': [105, 110], 'Volume': [100, 200],
                         'Dividends': [0, 1], 'Stock Splits': [0, 0]},
                        index=pd.date_range('2026-10-26 09:00', periods=2, freq='5min', tz='Asia/Jakarta'))


def fake(monkeypatch, response):
    calls = []
    def history(**kwargs):
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(provider, 'yf', SimpleNamespace(Ticker=lambda s: SimpleNamespace(history=history)))
    return calls


def test_normalized_raw_interval_start_envelope(monkeypatch):
    calls = fake(monkeypatch, frame())
    result = provider.fetch_intraday('BBCA.JK', START, END)
    assert result['status'] == 'OK'
    assert result['source'] == 'yahoo'
    assert result['price_basis'] == 'raw'
    assert result['interval'] == '5m'
    assert result['retrieved_at'].tzinfo is not None
    assert result['bars'][0].start == START
    assert (result['bars'][0].end - START).total_seconds() == 300
    assert result['bars'][0].open == Decimal(100)
    assert result['corporate_actions'][0]['kind'] == 'dividend'
    assert calls == [{'start': START, 'end': END, 'interval': '5m', 'auto_adjust': False, 'actions': True, 'raise_errors': True}]


@pytest.mark.parametrize('response,status', [(pd.DataFrame(), 'EMPTY_HISTORY'),
    (RuntimeError('secret=do-not-copy https://user:password@host'), 'PROVIDER_ERROR')])
def test_empty_and_sanitized_exceptions(monkeypatch, response, status):
    calls = fake(monkeypatch, response)
    result = provider.fetch_intraday('BBCA.JK', START, END)
    assert result['status'] == status
    assert result['bars'] == []
    assert 'do-not-copy' not in str(result)
    assert 'password' not in str(result)
    assert len(calls) == 1


def test_daily_previous_sessions_only_raw_action_flags(monkeypatch):
    rows = frame()
    rows.index = pd.date_range('2026-10-25', periods=2, freq='1D', tz='Asia/Jakarta')
    calls = fake(monkeypatch, rows)
    result = provider.fetch_daily('BBCA.JK', END)
    assert result['status'] == 'OK'
    assert result['interval'] == '1d'
    assert result['price_basis'] == 'raw'
    assert len(result['bars']) == 1
    assert result['bars'][0]['date'].isoformat() == '2026-10-25'
    assert result['bars'][0]['close'] == Decimal(105)
    assert calls[0]['auto_adjust'] is False
    assert calls[0]['actions'] is True
    assert calls[0]['interval'] == '1d'
    # Corporate actions on current daily bar are NOT future-safe previous context.
    assert result['corporate_actions'] == []


def test_daily_failures_sanitized_and_naive_rejected(monkeypatch):
    fake(monkeypatch, RuntimeError('password=secret'))
    assert provider.fetch_daily('BBCA.JK', END)['status'] == 'PROVIDER_ERROR'
    with pytest.raises(ValueError):
        provider.fetch_daily('BBCA.JK', END.replace(tzinfo=None))


def test_invalid_vendor_rows_fail_closed(monkeypatch):
    rows = frame()
    rows.iloc[0, 0] = float('nan')
    fake(monkeypatch, rows)
    assert provider.fetch_intraday('BBCA.JK', START, END)['status'] == 'INVALID_DATA'


START = datetime.fromisoformat('2026-10-26T09:00:00+07:00')
END = datetime.fromisoformat('2026-10-26T10:00:00+07:00')


@pytest.mark.parametrize('symbol', ['', 'bbca.JK', 'BBCA', ' BBCA.JK', '../BBCA.JK', 'ABCDX.JK', None])
def test_canonical_ticker_before_http(monkeypatch, symbol):
    def forbidden(*a, **k):
        pytest.fail('invalid input reached HTTP')
    monkeypatch.setattr(provider, 'yf', SimpleNamespace(Ticker=forbidden))
    with pytest.raises(ValueError):
        provider.fetch_intraday(symbol, START, END)


@pytest.mark.parametrize('start,end,interval', [(START.replace(tzinfo=None), END, '5m'),
    (END, START, '5m'), (START, END, '1d')])
def test_explicit_aware_supported_range(monkeypatch, start, end, interval):
    monkeypatch.setattr(provider, 'yf', SimpleNamespace(Ticker=lambda *a: pytest.fail('HTTP')))
    with pytest.raises(ValueError):
        provider.fetch_intraday('BBCA.JK', start, end, interval)
