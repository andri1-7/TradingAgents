"""Synthetic durable shadow contracts."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal


def test_store_rotation_transaction_and_no_duplicate_observation(tmp_path):
    from tradingagents.idx_strategies.store import Store

    store = Store(tmp_path / "shadow.db")
    row = {
        "symbol": "BBCA.JK",
        "strategy": "day",
        "session_date": "2026-10-28",
        "observed_at": "2026-10-28T10:00:01+07:00",
        "status": "SETUP",
        "rubric_version": "v1",
        "entry_deadline": "2026-10-28T10:10:00+07:00",
        "planned_exit": "2026-10-28T15:00:00+07:00",
        "reference_price": "100",
        "stop": "99",
        "target": "102",
    }
    for _ in range(2):
        store.save_scan(
            {"started_at": row["observed_at"], "completed_at": row["observed_at"]},
            [row],
            [],
            next_offset=25,
        )
    assert len(store.observations()) == 1
    assert store.rotation() == 25
    store.close()


def test_outcome_enters_strictly_future_and_marks_collision():
    from tradingagents.idx_strategies.models import Bar
    from tradingagents.idx_strategies.outcomes import advance_observation

    t = datetime(2026, 10, 28, 10, 0, tzinfo=timezone(timedelta(hours=7)))
    row = {
        "symbol": "BBCA.JK",
        "strategy": "day",
        "status": "SETUP",
        "observed_at": (t + timedelta(seconds=1)).isoformat(),
        "entry_deadline": (t + timedelta(minutes=10)).isoformat(),
        "planned_exit": (t + timedelta(hours=1)).isoformat(),
        "reference_price": "100",
        "stop": "99",
        "target": "102",
    }
    b = Bar(
        "BBCA.JK",
        t + timedelta(minutes=5),
        t + timedelta(minutes=10),
        Decimal(100),
        Decimal(103),
        Decimal(98),
        Decimal(101),
        Decimal(1000),
    )
    out = advance_observation(row, [b], t + timedelta(minutes=10))
    assert out["status"] == "AMBIGUOUS"
    assert out["entry"]["time"] == b.start.isoformat()


def test_rotation_visits_tail_without_duplicating():
    from tradingagents.idx_strategies.universe import select_symbols

    items = list(range(70))
    offset = 0
    all_rows = []
    for _ in range(3):
        rows, offset = select_symbols(items, offset, 25)
        all_rows += rows
    assert all_rows == items
    assert offset == 0
