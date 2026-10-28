"""Synthetic combined watch-card ranking; no probability interpretation."""

from copy import deepcopy

from tradingagents.idx_strategies import rules


def test_top_three_unique_symbols_stable_score_symbol_strategy_and_no_mutation():
    rows = [
        {"symbol": symbol, "strategy": strategy, "score": score, "status": status}
        for symbol, strategy, score, status in [
            ("BBBB.JK", "overnight", 8, "SETUP"),
            ("AAAA.JK", "overnight", 9, "SETUP"),
            ("AAAA.JK", "day", 9, "SETUP"),
            ("CCCC.JK", "day", 8, "SETUP"),
            ("DDDD.JK", "day", 7, "SETUP"),
            ("EEEE.JK", "day", 10, "NO_SETUP"),
        ]
    ]
    before = deepcopy(rows)
    result = rules.rank_candidates(rows)
    assert [(r["symbol"], r["strategy"]) for r in result] == [
        ("AAAA.JK", "day"),
        ("BBBB.JK", "overnight"),
        ("CCCC.JK", "day"),
    ]
    assert rules.rank_candidates(list(reversed(rows))) == result
    assert rows == before
    assert len(rules.rank_candidates(rows, limit=100)) == 3
    assert rules.rank_candidates(rows, limit=1) == result[:1]
    assert rules.rank_candidates(rows, limit=0) == []
