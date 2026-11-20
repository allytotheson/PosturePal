import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from posturepal.app import STYLE, Window
from posturepal.domain import Dwell, Frame, Settings, spine_points
from posturepal.qt_startup import create_application
from posturepal.storage import Storage
from posturepal.transport import Ack, BleakTransport, BleProfile

APP = QApplication.instance() or create_application([])
APP.setStyle("Fusion")
APP.setStyleSheet(STYLE)


def events(seconds=0.25):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        APP.processEvents()
        time.sleep(0.005)


class DomainTests(unittest.TestCase):
    def test_frame_validation(self):
        payload = dict(
            version=1,
            sequence=1,
            device_time_ms=1,
            upper_deg=2,
            lower_deg=3,
            upper_state="aligned",
            lower_state="pending",
            battery_pct=86,
            device_status="ready",
        )
        self.assertEqual(Frame.decode(payload, 20).received_at, 20)
        for key, value in [
            ("upper_deg", float("nan")),
            ("lower_deg", 91),
            ("battery_pct", 101),
            ("sequence", True),
            ("upper_state", "unknown"),
            ("device_status", "garbage"),
            ("version", 2),
        ]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    Frame.decode({**payload, key: value}, 20)

    def test_continuous_dwell(self):
        d = Dwell()
        self.assertEqual(d.update(20, 15, 0, 3000), "pending")
        self.assertEqual(d.update(20, 15, 2.99, 3000), "pending")
        self.assertEqual(d.update(20, 15, 3, 3000), "cue")
        self.assertEqual(d.update(15, 15, 4, 3000), "aligned")
        self.assertEqual(d.update(-20, 15, 5, 3000), "pending")

    def test_geometry(self):
        n = spine_points(0, 0)
        u = spine_points(25, 0)
        lower = spine_points(0, 20)
        self.assertEqual(len(n), 24)
        self.assertEqual(n[:11], u[:11])
        self.assertGreater(u[-1][2], n[-1][2])
        self.assertGreater(lower[10][2], n[10][2])

    def test_settings(self):
        for kwargs in [
            dict(upper_threshold=0),
            dict(lower_threshold=float("inf")),
            dict(dwell_ms=0),
        ]:
            with self.assertRaises(ValueError):
                Settings(**kwargs)

    def test_sqlite_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            db = Storage(path)
            sid = db.start()
            db.checkpoint(sid, 12, 9, True)
            db.record_ack(sid, Ack(1, "mock", Settings()))
            db.close()
            db = Storage(path)
            self.assertEqual(db.history()[0][2:4], (12, 9))
            self.assertIsNotNone(db.history()[0][1])
            self.assertEqual(
                db.connection.execute(
                    "SELECT COUNT(*) FROM settings_events"
                ).fetchone()[0],
                1,
            )
            db.close()


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.window = Window(Path(self.tmp.name) / "test.db")
        self.window.show()
        events(0.08)

    def tearDown(self):
        self.window.close()
        events(0.01)
        self.tmp.cleanup()

    def test_scenarios_calibration_and_pause(self):
        w = self.window
        w.set_scenario("Custom angles")
        w.transport.custom = (25, 2)
        w.transport._tick()
        self.assertEqual(w.last.upper_deg, 25)
        w.calibrate()
        w.transport._tick()
        self.assertEqual(w.last.upper_deg, 0)
        w.calibrate(True)
        w.transport._tick()
        self.assertEqual(w.last.upper_deg, 25)
        w.toggle_pause()
        count = w.samples
        events(0.12)
        self.assertEqual(w.samples, count)
        self.assertFalse(w.calibrate_button.isEnabled())
        self.assertIn("Paused", w.banner.text())
        w.toggle_pause()
        events(0.08)
        self.assertGreater(w.samples, count)

    def test_settings_only_apply_after_matching_ack(self):
        w = self.window
        w.upper_spin.setValue(25)
        w.apply_settings()
        self.assertEqual(w.settings.upper_threshold, 15)
        w.on_ack(Ack(999, "mock", Settings(25, 12, 3000)))
        self.assertEqual(w.settings.upper_threshold, 15)
        events(0.25)
        self.assertEqual(w.settings.upper_threshold, 25)
        self.assertEqual(
            w.storage.connection.execute(
                "SELECT COUNT(*) FROM settings_events"
            ).fetchone()[0],
            1,
        )

    def test_disconnect_cancels_pending_settings(self):
        w = self.window
        w.upper_spin.setValue(30)
        w.apply_settings()
        w.toggle_connection()
        events(0.25)
        self.assertEqual(w.settings.upper_threshold, 15)
        self.assertEqual(w.transport.settings.upper_threshold, 15)
        self.assertIsNone(w.pending)
        self.assertFalse(w.apply_button.isEnabled())

    def test_timeout_does_not_apply(self):
        w = self.window
        w.transport.request_settings = lambda *_: None
        w.upper_spin.setValue(22)
        w.apply_settings()
        w.ack_timeout()
        self.assertEqual(w.settings.upper_threshold, 15)
        self.assertIn("not applied", w.settings_status.text())

    def test_history_and_native_render(self):
        w = self.window
        w.show_history()
        self.assertEqual(w.table.rowCount(), 1)
        self.assertEqual(w.table.item(0, 4).text(), "mock")
        w.pages.setCurrentIndex(0)
        w.spine.set_view("Side")
        events(0.05)
        self.assertFalse(w.grab().isNull())


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_write_without_connection(self):
        adapter = BleakTransport(
            "unset", BleProfile("unset", "unset"), None, lambda _: None, lambda _: None
        )
        with self.assertRaises(RuntimeError):
            await adapter.request_settings(1, Settings())
        await adapter.disconnect()


if __name__ == "__main__":
    unittest.main()
