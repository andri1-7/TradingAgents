"""Explicit IDX provider chains preserve user selection and history guards."""

def test_profile_uses_idx_enrichment_only_for_applicable_tools():
    from tradingagents.indonesia import build_indonesia_config
    c = build_indonesia_config()
    assert c['tool_vendors']['get_news'] == 'idx_news,yfinance'
    assert c['tool_vendors']['get_fundamentals'] == 'issuer_evidence,yfinance'
    assert c['data_vendors']['fundamental_data'] == 'yfinance'


def test_idx_vendors_registered():
    from tradingagents.dataflows.router import VENDOR_METHODS
    assert 'idx_news' in VENDOR_METHODS['get_news']
    assert 'issuer_evidence' in VENDOR_METHODS['get_fundamentals']
