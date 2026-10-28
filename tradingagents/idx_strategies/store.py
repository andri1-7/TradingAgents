"""Transactional local research store. All monetary payloads are JSON strings."""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .reporting import json_safe


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assessments(scan_id TEXT,symbol TEXT,strategy TEXT,payload_json TEXT,UNIQUE(scan_id,symbol,strategy));
        CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,symbol TEXT,strategy TEXT,session_date TEXT,rubric_version TEXT,status TEXT,payload_json TEXT,UNIQUE(symbol,strategy,session_date,rubric_version));
        CREATE TABLE IF NOT EXISTS rotation(name TEXT PRIMARY KEY,next_offset INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_snapshots(id TEXT PRIMARY KEY,scan_id TEXT,symbol TEXT,retrieved_at TEXT,payload_json TEXT,sha256 TEXT);
        """)

    def rotation(self, name="registry"):
        row = self.connection.execute(
            "SELECT next_offset FROM rotation WHERE name=?", (name,)
        ).fetchone()
        return row[0] if row else 0

    def save_scan(self, scan, assessments, snapshots, next_offset=None):
        ident = uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO scans VALUES (?,?)",
                (ident, json.dumps(json_safe(scan), allow_nan=False)),
            )
            for row in assessments:
                payload = json.dumps(json_safe(row), allow_nan=False)
                self.connection.execute(
                    "INSERT INTO assessments VALUES (?,?,?,?)",
                    (ident, row["symbol"], row["strategy"], payload),
                )
                if row["status"] == "SETUP":
                    obs_id = uuid4().hex
                    record = {**row, "id": obs_id}
                    self.connection.execute(
                        "INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                        (
                            obs_id,
                            row["symbol"],
                            row["strategy"],
                            row["session_date"],
                            row["rubric_version"],
                            row["status"],
                            json.dumps(json_safe(record), allow_nan=False),
                        ),
                    )
            for snapshot in snapshots:
                raw = json.dumps(
                    json_safe(snapshot.get("payload", snapshot)), sort_keys=True, allow_nan=False
                )
                self.connection.execute(
                    "INSERT INTO provider_snapshots VALUES (?,?,?,?,?,?)",
                    (
                        uuid4().hex,
                        ident,
                        snapshot["symbol"],
                        snapshot["retrieved_at"],
                        raw,
                        hashlib.sha256(raw.encode()).hexdigest(),
                    ),
                )
            if next_offset is not None:
                self.connection.execute(
                    "INSERT INTO rotation VALUES (?,?) ON CONFLICT(name) DO UPDATE SET next_offset=excluded.next_offset",
                    ("registry", next_offset),
                )
        return ident

    def admit_observation(self, row, clock):
        """Two-phase admission: no retrospective entry after a slow commit.

        ADMITTING rows are never pending/tradeable. If final persistence crosses
        a 5-minute boundary, reject rather than authorize an already-open bar.
        """
        from datetime import datetime

        record = {**row, "id": uuid4().hex, "status": "ADMITTING"}
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                (
                    record["id"],
                    row["symbol"],
                    row["strategy"],
                    row["session_date"],
                    row["rubric_version"],
                    "ADMITTING",
                    json.dumps(json_safe(record), allow_nan=False),
                ),
            )
        existing = self.connection.execute(
            "SELECT id FROM observations WHERE symbol=? AND strategy=? AND session_date=? AND rubric_version=?",
            (row["symbol"], row["strategy"], row["session_date"], row["rubric_version"]),
        ).fetchone()
        if existing[0] != record["id"]:
            return
        admitted = clock()
        row["observed_at"] = admitted.isoformat()
        row["status"] = (
            "SETUP" if admitted < datetime.fromisoformat(row["entry_deadline"]) else "UNOBSERVABLE"
        )
        record.update(row)
        self.update_observation(record)
        durable = clock()

        def slot(t):
            return t.replace(second=0, microsecond=0, minute=(t.minute // 5) * 5)

        if slot(durable) != slot(admitted) or durable >= datetime.fromisoformat(
            row["entry_deadline"]
        ):
            row["status"] = "UNOBSERVABLE"
            row["reasons"] = [*row.get("reasons", []), "persistence_crossed_entry_boundary"]
            record.update(row)
            self.update_observation(record)
        else:
            # Evidence and SETUP are already durable before this timestamp.
            # A crash before this certificate leaves an inadmissible row.
            record["observed_at"] = durable.isoformat()
            row["observed_at"] = durable.isoformat()
            record["admission_verified"] = True
            self.update_observation(record)

    def pending(self):
        rows = [
            json.loads(r[0])
            for r in self.connection.execute(
                "SELECT payload_json FROM observations WHERE status IN ('SETUP','ENTERED') ORDER BY id"
            )
        ]
        return [
            r for r in rows if not r.get("calendar_hash") or r.get("admission_verified") is True
        ]

    def observations(self):
        return [
            json.loads(r[0])
            for r in self.connection.execute("SELECT payload_json FROM observations ORDER BY id")
        ]

    def scans(self):
        return [
            dict(json.loads(r["payload_json"]), id=r["id"])
            for r in self.connection.execute("SELECT * FROM scans ORDER BY rowid")
        ]

    def update_observation(self, record):
        with self.connection:
            changed = self.connection.execute(
                "UPDATE observations SET status=?,payload_json=? WHERE id=?",
                (record["status"], json.dumps(json_safe(record), allow_nan=False), record["id"]),
            )
            if changed.rowcount != 1:
                raise ValueError("unknown observation")

    def close(self):
        self.connection.close()
