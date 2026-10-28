import json
import sqlite3
from datetime import datetime

from tests.test_idx_monitor import candidate, setup


def test_unavailable_ai_is_failed_not_revalidated(tmp_path):
    monitor, args, calendar = setup(tmp_path)
    row = candidate()
    monitor.run_cycle(
        args,
        calendar,
        scanner=lambda *a, **k: {"assessments": [row]},
        settler=lambda *a, **k: {},
        analyzer=lambda r: {"status": "unavailable", "error_class": "analysis_timeout"},
        revalidator=lambda *a, **k: {"valid": True, "assessment": row},
        clock=lambda: datetime.fromisoformat("2026-10-28T10:00:00+07:00"),
    )
    with sqlite3.connect(args.state_db) as db:
        status, error, result = db.execute("select status,error,result from jobs").fetchone()
    assert status == "FAILED"
    assert error == "analysis_timeout"
    assert json.loads(result)["analysis"]["status"] == "unavailable"
