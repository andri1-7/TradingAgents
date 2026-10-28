import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from tradingagents.idx_strategies import monitor


def test_old_scan_artifact_cannot_be_reused(tmp_path):
    path = tmp_path / "scan.json"
    path.write_text(json.dumps({"assessments": [{"status": "SETUP"}]}))
    with pytest.raises(FileNotFoundError):
        monitor._invoke(lambda *a, **k: 1, SimpleNamespace(output=str(path)), None, None)


def test_outbox_expired_watch_is_downgraded_before_send(tmp_path):
    db = monitor._connect(tmp_path / "state.db")
    monitor._enqueue(
        db,
        "test",
        [1],
        {
            "kind": "analysis",
            "candidate": {
                "status": "WATCH_REVALIDATED",
                "entry_deadline": "2026-10-28T10:05:00+07:00",
            },
            "analysis": {},
        },
    )
    sent = []
    monitor._deliver(
        db,
        lambda chat, payload: sent.append(payload),
        lambda: datetime.fromisoformat("2026-10-28T10:06:00+07:00"),
    )
    assert sent[0]["candidate"]["status"] == "EXPIRED"
    assert sent[0]["candidate"]["actionable"] is False
    db.close()
