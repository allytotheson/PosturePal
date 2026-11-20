"""Local SQLite session summaries and acknowledged configuration events."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone


class Storage:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.pending_samples = []
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY, started TEXT NOT NULL, ended TEXT,
          samples INTEGER NOT NULL DEFAULT 0, aligned INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings_events (
          id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
          applied_at TEXT NOT NULL, source TEXT NOT NULL, request_id INTEGER NOT NULL, settings TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posture_samples (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
          recorded_at TEXT NOT NULL, sequence INTEGER NOT NULL,
          device_time_ms REAL, received_at REAL NOT NULL,
          upper_deg REAL NOT NULL, lower_deg REAL NOT NULL,
          upper_state TEXT NOT NULL, lower_state TEXT NOT NULL,
          battery_pct REAL, device_status TEXT NOT NULL,
          upper_threshold REAL, lower_threshold REAL,
          dwell_ms INTEGER, baseline_upper REAL, baseline_lower REAL);
        CREATE INDEX IF NOT EXISTS samples_by_session ON posture_samples(session_id, id);
        """)
        # Rebuild old sample tables to represent fields absent from BLE as NULL.
        columns = self.connection.execute(
            "PRAGMA table_info(posture_samples)"
        ).fetchall()
        if any(c[1] == "device_time_ms" and c[3] for c in columns):
            schema = self.connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='posture_samples'"
            ).fetchone()[0]
            for name, kind in (
                ("device_time_ms", "REAL"),
                ("battery_pct", "REAL"),
                ("upper_threshold", "REAL"),
                ("lower_threshold", "REAL"),
                ("dwell_ms", "INTEGER"),
                ("baseline_upper", "REAL"),
                ("baseline_lower", "REAL"),
            ):
                schema = schema.replace(f"{name} {kind} NOT NULL", f"{name} {kind}")
            with self.connection:
                self.connection.execute("BEGIN")
                self.connection.execute(
                    "ALTER TABLE posture_samples RENAME TO samples_legacy"
                )
                self.connection.execute(schema)
                names = ",".join(c[1] for c in columns)
                self.connection.execute(
                    f"INSERT INTO posture_samples ({names}) SELECT {names} FROM samples_legacy"
                )
                self.connection.execute("DROP TABLE samples_legacy")
                self.connection.execute(
                    "CREATE INDEX samples_by_session ON posture_samples(session_id, id)"
                )
        names = {
            c[1] for c in self.connection.execute("PRAGMA table_info(posture_samples)")
        }
        for name, kind in (
            ("buzz", "INTEGER"),
            ("upper_recovery", "REAL"),
            ("lower_recovery", "REAL"),
        ):
            if name not in names:
                self.connection.execute(
                    f"ALTER TABLE posture_samples ADD COLUMN {name} {kind}"
                )
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.commit()

    def start(self, source="mock"):
        with self.connection:
            return self.connection.execute(
                "INSERT INTO sessions(started, source) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), source),
            ).lastrowid

    def checkpoint(self, session_id, samples, aligned, end=False):
        with self.connection:
            self._insert_pending()
            self.connection.execute(
                "UPDATE sessions SET samples=?, aligned=?, ended=? WHERE id=?",
                (
                    samples,
                    aligned,
                    datetime.now(timezone.utc).isoformat() if end else None,
                    session_id,
                ),
            )

        self.pending_samples.clear()

    SAMPLE_FIELDS = (
        "recorded_at",
        "sequence",
        "device_time_ms",
        "received_at",
        "upper_deg",
        "lower_deg",
        "upper_state",
        "lower_state",
        "battery_pct",
        "device_status",
        "upper_threshold",
        "lower_threshold",
        "dwell_ms",
        "baseline_upper",
        "baseline_lower",
        "buzz",
        "upper_recovery",
        "lower_recovery",
    )

    def record_sample(self, session_id, frame, settings, baseline):
        # Keep bounded memory if disk writes fail. The UI reports recording errors.
        if len(self.pending_samples) >= 2000:
            raise RuntimeError(
                "Sample buffer full. New readings are not being recorded."
            )
        self.pending_samples.append(
            (
                session_id,
                datetime.now(timezone.utc).isoformat(),
                frame.sequence,
                frame.device_time_ms,
                frame.received_at,
                frame.upper_deg,
                frame.lower_deg,
                frame.upper_state,
                frame.lower_state,
                frame.battery_pct,
                frame.device_status,
                settings.upper_threshold if settings else None,
                settings.lower_threshold if settings else None,
                settings.dwell_ms if settings else None,
                baseline[0],
                baseline[1],
                frame.buzz,
                settings.upper_recovery if settings else None,
                settings.lower_recovery if settings else None,
            )
        )

    def _insert_pending(self):
        fields = ",".join(("session_id", *self.SAMPLE_FIELDS))
        self.connection.executemany(
            f"INSERT INTO posture_samples ({fields}) VALUES ({','.join('?' for _ in range(1 + len(self.SAMPLE_FIELDS)))})",
            self.pending_samples,
        )

    def flush(self):
        with self.connection:
            self._insert_pending()
        self.pending_samples.clear()

    def sample_count(self, session_id):
        return self.connection.execute(
            "SELECT COUNT(*) FROM posture_samples WHERE session_id=?", (session_id,)
        ).fetchone()[0]

    def sample_page(self, session_id, offset=0, limit=200):
        fields = ",".join(self.SAMPLE_FIELDS)
        return self.connection.execute(
            f"SELECT {fields} FROM posture_samples WHERE session_id=? ORDER BY id LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()

    def record_ack(self, session_id, ack):
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings_events(session_id,applied_at,source,request_id,settings) VALUES (?,?,?,?,?)",
                (
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                    ack.source,
                    ack.request_id,
                    json.dumps(asdict(ack.settings)),
                ),
            )

    def history(self):
        return self.connection.execute(
            "SELECT started, ended, samples, aligned, source, id FROM sessions ORDER BY id DESC LIMIT 100"
        ).fetchall()

    def close(self):
        self.flush()
        self.connection.close()
