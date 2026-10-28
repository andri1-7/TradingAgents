"""IDX equity/index quotes must be positive, not placeholder zero prices."""
import pandas as pd
import pytest

from tradingagents.indonesia import main


@pytest.mark.parametrize("close", [0.0, -1.0])
def test_reject_nonpositive_idx_close(monkeypatch, capsys, close):
    frame = pd.DataFrame({"Date": pd.to_datetime(["2026-01-15"]), "Close": [close]})
    monkeypatch.setattr(
        "tradingagents.dataflows.vendors.yahoo.ohlcv.load_ohlcv",
        lambda *a, **kw: frame,
    )
    assert main(["--ticker", "BBCA", "--date", "2026-01-15", "--check-data"]) == 1
    result = capsys.readouterr()
    assert not result.out
    assert "DATA_UNAVAILABLE" in result.err
