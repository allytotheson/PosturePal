"""Firmware fixtures, mocked GATT failures, and the real Qt/thread/UI boundary."""

import asyncio
import os
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from bleak.backends.device import BLEDevice
from PySide6.QtWidgets import QApplication

from posturepal.app import Window
from posturepal.domain import Frame, Settings
from posturepal.firmware import (
    RX_UUID,
    SERVICE_UUID,
    TX_UUID,
    Baseline,
    DeviceState,
    FirmwareCodec,
    ProtocolVersion,
    Readback,
    Reading,
)
from posturepal.qt_startup import create_application
from posturepal.storage import Storage
from posturepal.transport import Ack, BleakTransport

APP = QApplication.instance() or create_application([])
DEFAULTS = Settings(7.5, 7.5, 2000, 4, 4)
SENSOR_FAULT = (
    "IMU near full-scale imu=0 channel=0 source=gyro axis=Y raw=32761 limit=32000"
)


def status_text(settings=DEFAULTS, state="MONITORING", baseline=True, fault="none"):
    # Literal formats from firmware/PosturePal/PosturePal.ino at 6fbfdc0.
    return (
        "POSTUREPAL firmware=feather-v3 calibration=3s-settle+2s-still vqf_bits=64\n"
        "PROTOCOL version=1 transport=newline-ascii\n"
        f"STATUS state={state} mount_configured=1 mount_ok=1 baseline_valid={int(baseline)} geometry_valid=1 fault={fault}\n"
        "MOTOR buzz=0 motor=OFF_REG enabled=1\n"
        f"SETTINGS trigger={settings.upper_threshold:.2f},{settings.lower_threshold:.2f} "
        f"recovery={settings.upper_recovery:.2f},{settings.lower_recovery:.2f} duration_ms={settings.dwell_ms} motor_rtp=80 (TUNING VALUES)\n"
        f"BASELINE valid={int(baseline)} sag=1.250,-2.500\n"
    )


class FakeClient:
    instances = []

    def __init__(self, device, disconnected_callback):
        self.device = device
        self.callback = disconnected_callback
        self.is_connected = False
        self.notify = None
        self.buffer = b""
        self.writes = []
        self.commands = []
        self.write_times = []
        self.settings = DEFAULTS
        self.state = "MONITORING"
        self.fault_reason = "none"
        self.retry_fails = False
        self.no_ack = False
        self.reject = False
        self.mismatch = False
        self.fail_write = False
        self.fail_notify = False
        self.silent_status = False
        FakeClient.instances.append(self)

    async def connect(self):
        self.is_connected = True

    async def start_notify(self, uuid, callback):
        assert uuid == TX_UUID
        if self.fail_notify:
            raise RuntimeError("notifications unavailable")
        self.notify = callback

    def emit(self, text):
        data = text.encode("ascii")
        for start in range(0, len(data), 20):
            self.notify(None, data[start : start + 20])

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == RX_UUID and response and len(data) <= 20
        self.writes.append(bytes(data))
        if self.fail_write:
            raise OSError("radio write failed")
        self.buffer += bytes(data)
        if b"\n" not in self.buffer:
            return
        command = self.buffer.decode().strip()
        self.buffer = b""
        self.commands.append(command)
        self.write_times.append(time.monotonic())
        if command == "status":
            if not self.silent_status:
                self.emit(
                    status_text(
                        self.settings,
                        self.state,
                        self.state not in ("FAULT", "SETTLING"),
                        self.fault_reason,
                    )
                )
        elif command == "retry":
            if self.retry_fails:
                self.state = "FAULT"
                self.emit(
                    f"EVENT state=FAULT reason={self.fault_reason}\nERROR stop=registers-confirmed; retry required\n"
                )
            else:
                self.state = "SETTLING"
                self.fault_reason = "none"
                self.emit(
                    "EVENT state=SETTLING reason=hold neutral; 3 s settle, then 2 s continuously still\n"
                )
        elif self.state == "FAULT" and command not in ("sense", "help"):
            self.emit("ERR FAULT latched; use retry after correcting cause\n")
        elif command.startswith("set "):
            if self.reject:
                self.emit("ERR FAULT latched; use retry after correcting cause\n")
                return
            _, upper, ur, lower, lr, ms = command.split()
            if not self.mismatch:
                self.settings = Settings(
                    float(upper), float(lower), int(ms), float(ur), float(lr)
                )
            if not self.no_ack:
                self.emit("ACK settings applied; regional timers reset\n")
        elif command == "pause":
            self.state = "PAUSED"
            self.emit("EVENT state=PAUSED reason=user pause; filters continue\n")
        elif command == "resume":
            self.state = "MONITORING"
            self.emit("EVENT state=MONITORING reason=user resume\n")
        elif command == "calibrate":
            self.state = "SETTLING"
            self.emit(
                "EVENT state=SETTLING reason=hold neutral; 3 s settle, then 2 s continuously still\n"
            )
        elif command not in ("sense", "help"):
            self.emit("ERR unknown command or argument count; use help\n")

    async def disconnect(self):
        self.is_connected = False
        self.buffer = b""
        self.callback(self)


def qt_until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Qt condition did not complete")


class CodecTests(unittest.TestCase):
    def test_all_fragment_boundaries_and_coalesced_lines(self):
        wire = b"upper_deg=-179.20 lower_deg=12.50 buzz=1\r\nunknown diagnostic\nupper_deg=0.00 lower_deg=-1.25 buzz=0\n"
        for split in range(len(wire) + 1):
            codec = FirmwareCodec()
            events = codec.feed(wire[:split], 1) + codec.feed(wire[split:], 2)
            readings = [e for e in events if isinstance(e, Reading)]
            self.assertEqual(
                [(e.upper, e.lower, e.buzz) for e in readings],
                [(-179.2, 12.5, True), (0, -1.25, False)],
            )
            self.assertIn("unknown diagnostic", events)

    def test_overflow_and_bad_ascii_discard_through_newline(self):
        codec = FirmwareCodec()
        events = codec.feed(b"x" * 4096 + b"upper_deg=1 lower_deg=2 buzz=0\n", 1)
        self.assertEqual(sum(isinstance(e, ValueError) for e in events), 1)
        self.assertFalse(any(isinstance(e, Reading) for e in events))
        events = codec.feed(
            b"bad\xffupper_deg=1 lower_deg=2 buzz=0\nupper_deg=2 lower_deg=3 buzz=0\n",
            2,
        )
        self.assertEqual(sum(isinstance(e, Reading) for e in events), 1)
        self.assertEqual(len(codec.buffer), 0)

    def test_status_and_invalid_values(self):
        events = FirmwareCodec().feed(status_text().encode(), 10)
        self.assertIn(Readback(DEFAULTS), events)
        self.assertIn(Baseline((1.25, -2.5)), events)
        self.assertIn(ProtocolVersion(1), events)
        for line in (
            "upper_deg=nan lower_deg=0 buzz=0",
            "upper_deg=181 lower_deg=0 buzz=0",
            "PROTOCOL version=2 transport=newline-ascii",
            "STATUS state=UNKNOWN fault=none",
            "SETTINGS trigger=7.50,7.50 recovery=8.00,4.00 duration_ms=2000 motor_rtp=80 (TUNING VALUES)",
        ):
            with self.subTest(line=line):
                self.assertTrue(
                    any(
                        isinstance(e, ValueError)
                        for e in FirmwareCodec().feed((line + "\n").encode(), 1)
                    )
                )

    def test_fault_reason_from_event_and_status(self):
        text = f"EVENT state=FAULT reason={SENSOR_FAULT}\n" + status_text(
            state="FAULT", fault=SENSOR_FAULT, baseline=False
        )
        states = [
            event
            for event in FirmwareCodec().feed(text.encode(), 1)
            if isinstance(event, DeviceState)
        ]
        self.assertEqual(
            [state.fault_reason for state in states], [SENSOR_FAULT, SENSOR_FAULT]
        )
        self.assertIsNone(DeviceState("PAUSED", "reason=user pause").fault_reason)
        self.assertIsNone(DeviceState("FAULT", "fault=none").fault_reason)

    def test_command_validation(self):
        for command in ("", "a\nb", "x" * 160, "café", "status\r", "\t"):
            with self.assertRaises(ValueError):
                FirmwareCodec.encode_command(command)
        self.assertEqual(len(FirmwareCodec.encode_command("x" * 159)), 160)


class AsyncBleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.errors = []
        self.adapter = BleakTransport(
            "fixture",
            on_event=self.events.append,
            on_error=self.errors.append,
            client_factory=FakeClient,
        )
        await self.adapter.connect()
        self.client = self.adapter.client
        self.adapter.timeout = 0.03

    async def asyncTearDown(self):
        await self.adapter.disconnect()

    async def test_subscribe_before_status_and_roundtrip_settings(self):
        self.assertEqual(self.client.commands, ["status"])
        requested = Settings(15.25, 12.75, 3456, 5.5, 6.25)
        ack = await self.adapter.request_settings(7, requested)
        self.assertEqual(ack, Ack(7, "ble", requested))
        self.assertEqual(
            self.client.commands[1:], ["set 15.25 5.50 12.75 6.25 3456", "status"]
        )
        self.assertTrue(all(len(data) <= 20 for data in self.client.writes))
        self.assertGreaterEqual(
            self.client.write_times[2] - self.client.write_times[1], 0.09
        )

    async def test_gatt_write_without_ack_times_out_and_disconnects(self):
        self.client.no_ack = True
        with self.assertRaises(TimeoutError):
            await self.adapter.request_settings(1, Settings())
        self.assertIsNone(self.adapter.client)
        self.assertNotIn("status", self.client.commands[1:])

    async def test_rejection_and_mismatched_readback_never_ack(self):
        self.client.reject = True
        with self.assertRaisesRegex(RuntimeError, "FAULT latched"):
            await self.adapter.request_settings(1, Settings())
        self.assertTrue(self.client.is_connected)
        self.client.reject = False
        self.client.mismatch = True
        with self.assertRaisesRegex(RuntimeError, "readback differs"):
            await self.adapter.request_settings(2, Settings())

    async def test_failed_chunk_disconnects_and_clears_partial_command(self):
        self.client.fail_write = True
        with self.assertRaises(OSError):
            await self.adapter.send("sense")
        self.assertFalse(self.client.is_connected)
        self.assertIsNone(self.adapter.client)
        self.assertEqual(self.client.buffer, b"")

    async def test_concurrent_commands_rejected(self):
        command = asyncio.create_task(self.adapter.send("sense"))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError, "current command"):
            await self.adapter.send("pause")
        await command
        self.assertNotIn("pause", self.client.commands)

    async def test_remote_disconnect_unblocks_pending_and_reconnect_resets_parser(self):
        self.client.no_ack = True
        request = asyncio.create_task(self.adapter.request_settings(1, Settings()))
        await asyncio.sleep(0.01)
        await self.client.disconnect()
        with self.assertRaises(ConnectionError):
            await request
        self.assertTrue(self.errors)
        await self.adapter.connect()
        self.assertTrue(self.adapter.client.is_connected)
        self.assertEqual(self.adapter.codec.buffer, b"")

    async def test_invalid_command_does_not_write(self):
        before = list(self.client.writes)
        for command in ("set 1 2 3 4 5", "status\n", "x" * 160):
            with self.assertRaises(ValueError):
                await self.adapter.send(command)
        self.assertEqual(self.client.writes, before)

    async def test_notifications_failure_cleans_connection(self):
        await self.adapter.disconnect()

        def factory(*args, **kwargs):
            client = FakeClient(*args, **kwargs)
            client.fail_notify = True
            return client

        self.adapter.client_factory = factory
        with self.assertRaisesRegex(RuntimeError, "notifications unavailable"):
            await self.adapter.connect()
        self.assertIsNone(self.adapter.client)
        self.assertFalse(FakeClient.instances[-1].is_connected)


class BleWindowTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("bleak.BleakClient", FakeClient)
        self.patcher.start()
        self.window = Window(":memory:")
        self.window.show()
        self.window.mode_select.setCurrentText("BLE vest")
        self.device = BLEDevice("test-device", "PosturePal", None)
        self.window.on_devices([self.device])

    def tearDown(self):
        self.window.close()
        APP.processEvents()
        self.patcher.stop()

    def connect(self):
        self.window.toggle_connection()
        qt_until(lambda: self.window.connected)
        return self.window.ble.adapter.client

    def notify(self, text):
        adapter = self.window.ble.adapter
        future = asyncio.run_coroutine_threadsafe(
            self._notify(adapter, text), self.window.ble.worker.loop
        )
        future.result(1)
        APP.processEvents()

    async def _notify(self, adapter, text):
        adapter.client.emit(text)

    def test_scan_filter_and_device_selection(self):
        from types import SimpleNamespace

        async def discover(**kwargs):
            self.assertEqual(kwargs["service_uuids"], [SERVICE_UUID])
            return {
                "fixture": (self.device, SimpleNamespace(service_uuids=[SERVICE_UUID]))
            }

        with patch("bleak.BleakScanner.discover", discover):
            self.window.scan_devices()
            qt_until(lambda: not self.window.ble.busy)
        self.assertEqual(self.window.device_select.currentData().address, "test-device")

    def test_live_readings_settings_history_and_stale(self):
        w = self.window
        client = self.connect()
        self.assertIs(client.device, self.device)
        self.assertEqual(w.settings, DEFAULTS)
        self.assertEqual(w.upper_spin.value(), 7.5)
        self.assertEqual(w.battery_label.text(), "—")
        self.notify("upper_deg=18.25 lower_deg=-2.50 buzz=1\n")
        self.assertEqual(w.samples, 1)
        self.assertIn("yes", w.banner.text())
        self.assertEqual(w.last.upper_state, "above")
        self.assertIsNone(w.last.device_time_ms)
        w.checkpoint()
        row = w.storage.sample_page(w.session)[0]
        self.assertIsNone(row[2])
        self.assertIsNone(row[8])
        self.assertEqual(row[15:], (1, 4, 4))
        self.assertEqual(w.storage.history()[0][4], "ble")
        w.last = replace(w.last, received_at=time.monotonic() - 4)
        w.check_stale()
        self.assertEqual(w.angle_labels[0].text(), "—")
        w.upper_spin.setValue(20)
        w.apply_settings()
        self.assertIsNotNone(w.pending)
        qt_until(lambda: w.pending is None)
        self.assertEqual(w.settings.upper_threshold, 20)
        self.assertIn("readback confirmed", w.settings_status.text())
        self.assertEqual(
            w.storage.connection.execute(
                "SELECT source FROM settings_events"
            ).fetchone(),
            ("ble",),
        )

    def test_pause_resume_calibration_and_disconnect(self):
        w = self.window
        client = self.connect()
        self.notify("upper_deg=1 lower_deg=2 buzz=0\n")
        w.toggle_ble_pause()
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(w.ble.state, "PAUSED")
        self.assertEqual(w.angle_labels[0].text(), "—")
        self.notify("upper_deg=99 lower_deg=99 buzz=1\n")
        self.assertEqual(w.samples, 1)
        w.toggle_ble_pause()
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(w.ble.state, "MONITORING")
        w.calibrate()
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(w.ble.state, "SETTLING")
        self.assertIn("calibrate", client.commands)
        w.toggle_connection()
        qt_until(lambda: not w.ble.busy)
        self.assertFalse(w.connected)
        self.assertNotEqual(client.commands[-1], "pause")
        self.assertEqual(w.angle_labels[0].text(), "—")

    def test_unexpected_disconnect_and_reconnect(self):
        w = self.window
        client = self.connect()
        self.notify("upper_deg=1 lower_deg=2 buzz=0\n")
        future = asyncio.run_coroutine_threadsafe(
            client.disconnect(), w.ble.worker.loop
        )
        future.result(1)
        qt_until(lambda: not w.connected)
        self.assertFalse(w.apply_button.isEnabled())
        self.assertIsNone(w.ble.settings)
        self.assertEqual(w.angle_labels[0].text(), "—")
        self.connect()
        self.assertTrue(w.apply_button.isEnabled())

    def test_switch_to_simulator_isolates_sessions_and_old_events(self):
        w = self.window
        self.connect()
        self.notify("upper_deg=12 lower_deg=2 buzz=0\n")
        old_session = w.session
        generation = w.ble.generation
        w.mode_select.setCurrentText("Simulator")
        w.ble._on_event((generation, Reading(99, 99, True, time.monotonic())))
        self.assertEqual(w.samples, 0)
        self.assertNotEqual(w.session, old_session)
        self.assertTrue(w.mock.timer.isActive())
        self.assertEqual(w.storage.sample_count(old_session), 1)
        self.assertTrue(w.connect_button.isEnabled())

    def test_completed_calibration_reads_baseline_and_persists_raw_angles(self):
        w = self.window
        client = self.connect()
        self.notify(
            "EVENT state=SETTLING reason=hold neutral\nEVENT state=CALIBRATING reason=2 s neutral averaging\n"
        )
        self.assertEqual(w.ble.baseline, (None, None))
        self.notify("EVENT state=MONITORING reason=neutral saved in RAM\n")
        qt_until(lambda: w.ble.baseline == (1.25, -2.5) and not w.ble.busy)
        self.assertEqual(client.commands.count("status"), 2)
        self.assertIn("Firmware baseline: 1.250° / -2.500°", w.baseline_label.text())
        self.notify(
            "EVENT state=MONITORING reason=already monitoring\nupper_deg=-12 lower_deg=-4 buzz=0\n"
        )
        w.checkpoint()
        row = w.storage.sample_page(w.session)[0]
        self.assertEqual(row[4:6], (-12, -4))
        self.assertEqual(row[13:15], (1.25, -2.5))
        self.assertEqual(client.commands.count("status"), 2)

    def test_disconnect_cancels_queued_calibration_readback(self):
        w = self.window
        client = self.connect()
        generation = w.ble.generation
        w.ble._on_event((generation, DeviceState("CALIBRATING", "reason=hold neutral")))
        w.ble._on_event(
            (generation, DeviceState("MONITORING", "reason=neutral saved in RAM"))
        )
        w.ble.disconnect_device()
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(client.commands, ["status"])
        self.assertEqual(w.ble.baseline, (None, None))

    def test_connect_to_faulted_vest_preserves_cause_and_blocks_inapplicable_controls(
        self,
    ):
        def faulted_client(*args, **kwargs):
            client = FakeClient(*args, **kwargs)
            client.state = "FAULT"
            client.fault_reason = SENSOR_FAULT
            return client

        with patch("bleak.BleakClient", faulted_client):
            client = self.connect()
        w = self.window
        self.assertTrue(w.connected)
        self.assertIn("firmware FAULT", w.device_status.text())
        self.assertIn("sensor readings stopped", w.banner.text())
        self.assertEqual(w.fault_reason_label.text(), SENSOR_FAULT)
        self.assertTrue(w.fault_panel.isVisible())
        self.assertFalse(w.calibrate_button.isEnabled())
        self.assertFalse(w.ble_pause_button.isEnabled())
        self.assertFalse(w.apply_button.isEnabled())
        self.assertTrue(w.status_button.isEnabled())
        self.assertTrue(w.retry_button.isEnabled())
        self.assertEqual(w.ble.baseline, (None, None))
        self.assertEqual(client.commands, ["status"])  # No automatic recovery.
        w.check_stale()
        self.assertIn("sensor readings stopped", w.banner.text())

    def test_fault_stops_samples_and_recovery_follows_reported_state(self):
        w = self.window
        client = self.connect()
        self.notify("upper_deg=12 lower_deg=2 buzz=0\n")
        self.assertEqual(w.samples, 1)
        client.state = "FAULT"
        client.fault_reason = SENSOR_FAULT
        self.notify(
            f"EVENT state=FAULT reason={SENSOR_FAULT}\nERROR stop=registers-confirmed; retry required\n"
        )
        self.notify("upper_deg=99 lower_deg=99 buzz=1\n")
        self.assertEqual(w.samples, 1)
        self.assertEqual(w.angle_labels[0].text(), "—")
        w.ble_command("calibrate")  # A manual rejected command must retain the cause.
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(w.fault_reason_label.text(), SENSOR_FAULT)
        self.assertIn("sensor readings stopped", w.banner.text())
        w.retry_button.click()
        qt_until(lambda: not w.ble.busy)
        self.assertEqual(client.commands.count("retry"), 1)
        self.assertEqual(w.ble.state, "SETTLING")
        self.assertFalse(w.fault_panel.isVisible())
        self.assertEqual(w.angle_labels[0].text(), "—")
        client.state = "MONITORING"
        self.notify(
            "EVENT state=MONITORING reason=neutral saved in RAM\nupper_deg=1 lower_deg=2 buzz=0\n"
        )
        self.assertEqual(w.samples, 2)
        self.assertEqual(w.angle_labels[0].text(), "1.0°")
        self.assertIsNone(w.ble.fault_reason)

    def test_failed_retry_preserves_fault_without_automatic_retry(self):
        w = self.window
        client = self.connect()
        client.state = "FAULT"
        client.fault_reason = SENSOR_FAULT
        client.retry_fails = True
        self.notify(f"EVENT state=FAULT reason={SENSOR_FAULT}\n")
        w.retry_button.click()
        qt_until(lambda: not w.ble.busy)
        self.assertTrue(w.connected)
        self.assertEqual(w.ble.state, "FAULT")
        self.assertEqual(w.fault_reason_label.text(), SENSOR_FAULT)
        self.assertEqual(client.commands.count("retry"), 1)
        self.assertTrue(w.retry_button.isEnabled())
        self.assertFalse(w.calibrate_button.isEnabled())

    def test_rejection_requires_status_before_another_settings_attempt(self):
        w = self.window
        client = self.connect()
        client.reject = True
        w.upper_spin.setValue(20)
        w.apply_settings()
        qt_until(lambda: not w.ble.busy)
        self.assertIsNone(w.pending)
        self.assertFalse(w.apply_button.isEnabled())
        self.assertIn("FAULT latched", w.device_log.toPlainText())
        self.assertEqual(
            w.storage.connection.execute(
                "SELECT COUNT(*) FROM settings_events"
            ).fetchone()[0],
            0,
        )
        client.reject = False
        w.ble_command("status")
        qt_until(lambda: not w.ble.busy)
        self.assertTrue(w.apply_button.isEnabled())
        self.assertEqual(w.settings, DEFAULTS)

    def test_disconnect_while_settings_pending_cancels_ack(self):
        w = self.window
        client = self.connect()
        client.no_ack = True
        w.upper_spin.setValue(20)
        w.apply_settings()
        qt_until(lambda: any(command.startswith("set ") for command in client.commands))
        self.assertTrue(w.connect_button.isEnabled())
        w.toggle_connection()
        qt_until(lambda: not w.ble.busy)
        self.assertFalse(w.connected)
        self.assertIsNone(w.pending)
        self.assertIsNone(w.ble.settings)
        self.assertEqual(
            w.storage.connection.execute(
                "SELECT COUNT(*) FROM settings_events"
            ).fetchone()[0],
            0,
        )

    def test_close_during_scan_stops_thread(self):
        w = self.window

        async def discover(**kwargs):
            await asyncio.sleep(10)
            return {}

        with patch("bleak.BleakScanner.discover", discover):
            w.scan_devices()
            worker = w.ble.worker
            w.close()
            self.assertFalse(worker.isRunning())
        # Avoid closing the SQLite connection twice in tearDown.
        self.window = Window(":memory:")

    def test_close_during_pending_command_stops_thread(self):
        w = self.window
        self.connect()
        w.ble_command("sense")
        worker = w.ble.worker
        w.close()
        self.assertFalse(worker.isRunning())
        self.window = Window(":memory:")


class BleStorageTests(unittest.TestCase):
    def test_migrate_populated_original_sample_table_and_reopen_ble(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            # Reproduce the original schema, including NOT NULL constraints.
            db = Storage(path)
            sid = db.start()
            frame = Frame(1, 10, 20, 1, 2, "aligned", "aligned", 86, "ready")
            db.record_sample(sid, frame, Settings(), (0, 0))
            db.close()
            c = sqlite3.connect(path)
            schema = c.execute(
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
                schema = schema.replace(f"{name} {kind},", f"{name} {kind} NOT NULL,")
            c.execute("ALTER TABLE posture_samples RENAME TO original_samples")
            c.execute(schema)
            c.execute("INSERT INTO posture_samples SELECT * FROM original_samples")
            c.execute("DROP TABLE original_samples")
            c.commit()
            c.close()
            db = Storage(path)
            self.assertEqual(db.sample_page(sid)[0][2], 10)
            ble_sid = db.start("ble")
            db.record_sample(
                ble_sid,
                replace(frame, device_time_ms=None, battery_pct=None, buzz=True),
                None,
                (None, None),
            )
            db.checkpoint(ble_sid, 1, 0, True)
            db.close()
            db = Storage(path)
            row = db.sample_page(ble_sid)[0]
            self.assertIsNone(row[2])
            self.assertIsNone(row[8])
            self.assertEqual(row[10:15], (None,) * 5)
            self.assertEqual(row[15], 1)
            self.assertEqual(db.sample_count(sid), 1)
            self.assertEqual(db.history()[0][4], "ble")
            db.close()
