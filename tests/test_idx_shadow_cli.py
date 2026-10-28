"""Synthetic CLI boundaries, no provider/LLM calls."""

import json


def test_missing_calendar_blocks_before_database(tmp_path):
    import pytest

    from tradingagents.idx_strategies.cli import main

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "scan",
                "--sessions",
                str(tmp_path / "missing.json"),
                "--db",
                str(tmp_path / "x.db"),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
    assert exc.value.code == 2
    assert not (tmp_path / "x.db").exists()


def test_reporting_deduplicates_and_limits_cards():
    from tradingagents.idx_strategies.reporting import report

    rows = [
        {"symbol": f"AAA{i}.JK", "strategy": "day", "status": "SETUP", "score": 9, "reasons": []}
        for i in range(5)
    ]
    out = report({"assessments": rows})
    assert len(out["shortlist"]) == 3
    assert all(x["label"] == "WATCH" for x in out["shortlist"])
    assert "BUY" not in json.dumps(out)
