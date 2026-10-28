"""Registry contracts; small import fixtures are synthetic, bundled data is sourced."""
import json

import pytest


def test_bundled_count_and_identity():
    from tradingagents.idx_registry import load_registry
    data = load_registry()
    assert len(data['issuers']) == data['declared_count']
    assert len({r['symbol'] for r in data['issuers']}) == data['declared_count']
    assert any(r['yahoo_symbol'] == 'BBCA.JK' for r in data['issuers'])
    assert 'unverified' in data['coverage_status']


def test_cli_exports_every_row(capsys):
    from tradingagents.idx_registry import load_registry, main
    assert main(['list', '--format', 'json']) == 0
    exported = json.loads(capsys.readouterr().out)
    assert len(exported['issuers']) == load_registry()['declared_count']


@pytest.mark.parametrize('fields', [('Code', 'Name'), ('KodeEmiten', 'NamaEmiten')])
def test_import_reconciles_both_official_shapes(tmp_path, fields):
    from tradingagents.idx_registry import import_registry, load_registry
    source = tmp_path / 'source.json'
    out = tmp_path / 'registry.json'
    source.write_text(json.dumps({'recordsTotal': 1, 'recordsFiltered': 1, 'data': [{fields[0]: 'BBCA', fields[1]: 'Bank Central Asia'}]}))
    import_registry(source, out, 'https://www.idx.co.id/example', None)
    assert load_registry(out)['issuers'][0]['symbol'] == 'BBCA'
    assert 'unverified' in load_registry(out)['coverage_status']


@pytest.mark.parametrize('rows,total', [([], 1), ([{'Code': 'BBCA', 'Name': 'Bank'}], 2), ([{'Code': '../X', 'Name': 'Bank'}], 1), ([{'Code': 'BBCA', 'Name': 'Bank'}]*2, 2)])
def test_bad_import_preserves_existing(tmp_path, rows, total):
    from tradingagents.idx_registry import import_registry
    source = tmp_path / 'source.json'
    out = tmp_path / 'registry.json'
    out.write_text('old')
    source.write_text(json.dumps({'recordsTotal': total, 'data': rows}))
    with pytest.raises(ValueError):
        import_registry(source, out, 'https://www.idx.co.id/example', None)
    assert out.read_text() == 'old'
