import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication

from posturepal.app import Window
from posturepal.domain import Frame, Settings
from posturepal.history import SessionDetails
from posturepal.qt_startup import create_application
from posturepal.storage import Storage

APP = QApplication.instance() or create_application([])
FRAME = Frame(7, 100.0, 20.0, 24.0, -3.0, "cue", "aligned", 86.0, "ready")


class SampleTests(unittest.TestCase):
    def test_reopen_and_immutable_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.db"
            db = Storage(path)
            sid = db.start()
            baseline = [1.0, 2.0]
            db.record_sample(sid, FRAME, Settings(), baseline)
            baseline[0] = 99
            db.checkpoint(sid, 1, 0, True)
            db.close()
            db = Storage(path)
            row = db.sample_page(sid)[0]
            self.assertEqual(
                row[1:10], (7, 100.0, 20.0, 24.0, -3.0, "cue", "aligned", 86.0, "ready")
            )
            self.assertEqual(row[10:], (15.0, 12.0, 3000, 1.0, 2.0, None, 4.0, 4.0))
            self.assertTrue(row[0].endswith("+00:00"))
            db.close()

    def test_additive_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            c = sqlite3.connect(path)
            c.execute(
                "CREATE TABLE sessions (id INTEGER PRIMARY KEY, started TEXT NOT NULL, ended TEXT, samples INTEGER NOT NULL DEFAULT 0, aligned INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL)"
            )
            c.execute(
                "INSERT INTO sessions VALUES(1,'2026-10-01T00:00:00+00:00',NULL,150,100,'mock')"
            )
            c.commit()
            c.close()
            db = Storage(path)
            self.assertEqual(db.history()[0][2], 150)
            self.assertEqual(db.sample_count(1), 0)
            db.close()

    def test_atomic_retry_no_duplicates_and_session_isolation(self):
        db = Storage(":memory:")
        sid = db.start()
        second = db.start()
        db.record_sample(sid, FRAME, Settings(), (0, 0))
        db.connection.execute(
            "CREATE TRIGGER reject_sample BEFORE INSERT ON posture_samples BEGIN SELECT RAISE(ABORT,'disk failure'); END"
        )
        with self.assertRaises(sqlite3.DatabaseError):
            db.checkpoint(sid, 1, 0)
        self.assertEqual(len(db.pending_samples), 1)
        self.assertEqual(db.sample_count(sid), 0)
        self.assertEqual(db.history()[-1][2], 0)
        db.connection.execute("DROP TRIGGER reject_sample")
        db.checkpoint(sid, 1, 0)
        db.flush()
        self.assertEqual(db.sample_count(sid), 1)
        self.assertEqual(db.sample_count(second), 0)
        db.close()

    def test_pagination_and_empty_state(self):
        db = Storage(":memory:")
        sid = db.start()
        old = db.start()
        for i in range(405):
            db.record_sample(
                sid,
                replace(FRAME, sequence=i, received_at=20 + i * 0.05),
                Settings(),
                (0, 0),
            )
        dialog = SessionDetails(db, sid)
        self.assertEqual(dialog.table.rowCount(), 200)
        dialog.move(200)
        self.assertEqual(dialog.table.item(0, 1).text(), "200")
        dialog.move(200)
        self.assertEqual(dialog.table.rowCount(), 5)
        self.assertFalse(dialog.next.isEnabled())
        dialog.close()
        empty = SessionDetails(db, old)
        self.assertIn("summaries only", empty.summary.text())
        empty.close()
        db.close()

    def test_window_records_and_saves_on_disconnect(self):
        w = Window(":memory:")
        w.transport.disconnect_device()
        w.on_frame(FRAME)
        w.toggle_connection()
        self.assertEqual(w.storage.sample_count(w.session), 1)
        w.show_history()
        self.assertEqual(w.table.item(0, 0).data(256), w.session)
        w.close()
