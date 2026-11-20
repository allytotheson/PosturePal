import sys
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .domain import Settings
from .firmware import Baseline, DeviceState, Readback
from .history import SessionDetails
from .qt_startup import create_application
from .spine import SpineWidget
from .storage import Storage
from .transport import BluetoothTransport, MockTransport

STYLE = """
QMainWindow,QWidget#root { background:#f2f2f2; color:#30343a; }
QWidget { font-family:Helvetica; font-size:13px; color:#30343a; }
QFrame#sidebar { background:#e9eaec; border:1px solid #d3d5d8; border-radius:4px; }
QFrame#card { background:white; border:1px solid #d3d5d8; border-radius:4px; }
QLabel#title { font-size:22px; font-weight:600; }
QLabel#brand { font-size:20px; font-weight:600; }
QLabel#eyebrow { color:#60656d; font-size:12px; }
QLabel#muted { color:#676c74; font-size:11px; }
QLabel#section { font-size:14px; font-weight:600; }
QLabel#metric { font-size:22px; font-weight:500; }
QLabel#banner { background:#edf1f5; border-radius:3px; padding:8px; color:#3d5367; }
QPushButton { min-height:16px; background:#4b6e91; color:white; padding:7px 11px; border:1px solid #3e607f; border-radius:4px; }
QPushButton:hover { background:#3e607f; }
QPushButton:disabled { background:#ececec; color:#95999f; border-color:#d8dadd; }
QPushButton#secondary { background:#f7f7f7; color:#30343a; border-color:#c7cbd0; }
QPushButton#secondary:hover { background:#e8ecf0; }
QPushButton#secondary:disabled { background:#ececec; color:#95999f; border-color:#d8dadd; }
QPushButton:checked { background:#dde6ef; color:#354f69; }
QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit { color:#20262e; background:white; border:1px solid #bfc5cb; border-radius:3px; padding:6px; min-height:20px; }
QPlainTextEdit { color:#20262e; background:#ffffff; border:1px solid #bfc5cb; border-radius:3px; padding:6px; font-family:Menlo; font-size:12px; selection-background-color:#315f86; selection-color:#ffffff; }
QLineEdit { selection-background-color:#315f86; selection-color:#ffffff; placeholder-text-color:#68717b; }
QLineEdit:disabled,QDoubleSpinBox:disabled { background:#f1f3f5; color:#676c74; }
QFrame#fault { background:#fff1ed; border:1px solid #d5a394; border-radius:4px; }
QFrame#fault QLabel { background:transparent; border:0; color:#783a2c; }
QSlider::groove:horizontal { background:#d6d9dd; height:5px; border-radius:2px; }
QSlider::handle:horizontal { background:#577b9b; width:14px; margin:-5px 0; border-radius:7px; }
QTableWidget { border:1px solid #d3d5d8; background:white; gridline-color:#e4e6e8; }
QHeaderView::section { background:#eceef0; padding:8px; border:0; }
"""


def label(text, kind=None):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    if kind:
        w.setObjectName(kind)
    w.setMinimumHeight(
        32 if kind in ("metric", "title", "brand") else 40 if kind == "banner" else 16
    )
    return w


def button(text, callback, secondary=False):
    w = QPushButton(text)
    w.clicked.connect(callback)
    if secondary:
        w.setObjectName("secondary")
    return w


def card():
    w = QFrame()
    w.setObjectName("card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(9)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    return w, layout


class Window(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.setWindowTitle("PosturePal · Python desktop")
        self.resize(1280, 940)
        self.setMinimumSize(1040, 860)
        self.mock = MockTransport(self)
        self.ble = BluetoothTransport(self)
        self.transport = self.mock
        self.mode = "Simulator"
        self.closing = False
        self.ble.devices_found.connect(self.on_devices)
        self.ble.connection.connect(self.on_ble_connection)
        self.ble.error.connect(self.on_ble_error)
        self.ble.event.connect(self.on_ble_event)
        self.ble.frame.connect(self.on_ble_frame)
        self.ble.acknowledged.connect(self.on_ack)
        self.ble.finished.connect(self.update_ble_controls)
        self.transport.frame.connect(self.on_frame)
        self.transport.acknowledged.connect(self.on_ack)
        self.settings = Settings()
        self.pending = None
        self.next_request = 0
        self.last = None
        self.connected = True
        self.paused = False
        self.samples = 0
        self.aligned = 0
        self.evaluated_samples = 0
        self.active_seconds = 0.0
        self.previous_time = None
        if db_path is None:
            directory = Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            directory.mkdir(parents=True, exist_ok=True)
            db_path = directory / "posturepal.sqlite3"
        self.storage = Storage(db_path)
        self.session = self.storage.start()
        self.ack_timer = QTimer(self)
        self.ack_timer.setSingleShot(True)
        self.ack_timer.timeout.connect(self.ack_timeout)
        self.checkpoint_timer = QTimer(self)
        self.checkpoint_timer.setInterval(5000)
        self.checkpoint_timer.timeout.connect(self.checkpoint)
        self.checkpoint_timer.start()
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(18, 18, 24, 18)
        outer.setSpacing(16)
        sidebar, side = card()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(170)
        side.addWidget(label("PosturePal", "brand"))
        side.addSpacing(18)
        side.addWidget(label("Navigation", "eyebrow"))
        side.addWidget(
            button("Live posture", lambda: self.pages.setCurrentIndex(0), True)
        )
        side.addWidget(button("Session history", self.show_history, True))
        side.addStretch()
        side.addWidget(label("18-500 · TEAM B5\nPython desktop · v0.2", "muted"))
        outer.addWidget(sidebar)
        body = QVBoxLayout()
        body.setSpacing(18)
        outer.addLayout(body, 1)
        top = QHBoxLayout()
        top.addWidget(label("Posture monitor", "eyebrow"))
        top.addStretch()
        self.mode_select = QComboBox()
        self.mode_select.addItems(["Simulator", "BLE vest"])
        self.mode_select.currentTextChanged.connect(self.switch_mode)
        top.addWidget(self.mode_select)
        body.addLayout(top)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        live = QWidget()
        live.setObjectName("root")
        layout = QVBoxLayout(live)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(17)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(live)
        self.pages.addWidget(scroll)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("Live posture", "title"))
        titles.addWidget(
            label("Upper and lower back angles relative to your baseline.", "muted")
        )
        heading.addLayout(titles, 1)
        self.connect_button = button(
            "Disconnect simulator", self.toggle_connection, True
        )
        heading.addWidget(self.connect_button)
        layout.addLayout(heading)
        self.ble_panel, bl = card()
        br = QHBoxLayout()
        self.scan_button = button("Scan for vests", self.scan_devices, True)
        br.addWidget(self.scan_button)
        self.device_select = QComboBox()
        self.device_select.setMinimumWidth(250)
        self.device_select.currentIndexChanged.connect(self.update_ble_controls)
        br.addWidget(self.device_select, 1)
        self.status_button = button(
            "Read device status", lambda: self.ble_command("status"), True
        )
        br.addWidget(self.status_button)
        self.ble_pause_button = button("Pause vest", self.toggle_ble_pause, True)
        br.addWidget(self.ble_pause_button)
        self.diagnostics_button = button("Diagnostics", self.toggle_diagnostics, True)
        br.addWidget(self.diagnostics_button)
        bl.addLayout(br)
        self.device_status = label("Scan, select a vest, then connect.", "muted")
        self.device_status.setWordWrap(True)
        bl.addWidget(self.device_status)
        self.fault_panel = QFrame()
        self.fault_panel.setObjectName("fault")
        fault_layout = QVBoxLayout(self.fault_panel)
        fault_layout.addWidget(label("Vest fault · sensor readings stopped", "section"))
        self.fault_reason_label = label("")
        self.fault_reason_label.setWordWrap(True)
        self.fault_reason_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        fault_layout.addWidget(self.fault_reason_label)
        self.fault_help = label("", "muted")
        self.fault_help.setWordWrap(True)
        fault_layout.addWidget(self.fault_help)
        self.retry_button = button(
            "Retry device after correcting cause",
            lambda: self.ble_command("retry"),
            True,
        )
        fault_layout.addWidget(self.retry_button)
        self.fault_panel.hide()
        bl.addWidget(self.fault_panel)
        self.diagnostics_panel = QWidget()
        diagnostics = QVBoxLayout(self.diagnostics_panel)
        diagnostics.setContentsMargins(0, 0, 0, 0)
        self.device_log = QPlainTextEdit()
        self.device_log.setReadOnly(True)
        self.device_log.setMaximumBlockCount(200)
        self.device_log.setMaximumHeight(110)
        self.device_log.setPlaceholderText("Firmware responses and diagnostics")
        diagnostics.addWidget(self.device_log)
        command_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setMaxLength(159)
        self.command_input.setPlaceholderText(
            "Device command, e.g. sense, axes +Y +Z, mount-ok, retry"
        )
        self.command_input.returnPressed.connect(self.send_device_command)
        command_row.addWidget(self.command_input, 1)
        self.command_button = button("Send command", self.send_device_command, True)
        command_row.addWidget(self.command_button)
        diagnostics.addLayout(command_row)
        self.diagnostics_panel.hide()
        bl.addWidget(self.diagnostics_panel)
        self.ble_panel.hide()
        layout.addWidget(self.ble_panel)
        metrics, ml = card()
        row = QHBoxLayout()
        self.time_label = label("00:00", "metric")
        self.percent_label = label("—", "metric")
        self.source_label = label("Mock vest", "metric")
        self.source_detail = label("20 Hz · simulated wearable", "muted")
        self.battery_label = label("86%", "metric")
        self.battery_detail = label("Simulated value", "muted")
        for name, value, detail in [
            ("Session time", self.time_label, "Active sample time"),
            (
                "Within thresholds",
                self.percent_label,
                "This session · sample percentage",
            ),
            ("Data source", self.source_label, self.source_detail),
            ("Vest battery", self.battery_label, self.battery_detail),
        ]:
            col = QVBoxLayout()
            col.addWidget(label(name, "eyebrow"))
            col.addWidget(value)
            col.addWidget(
                detail if isinstance(detail, QLabel) else label(detail, "muted")
            )
            row.addLayout(col, 1)
        ml.addLayout(row)
        layout.addWidget(metrics)
        dashboard = QHBoxLayout()
        dashboard.setSpacing(18)
        visual, vl = card()
        vl.addWidget(label("Posture model", "section"))
        vr = QHBoxLayout()
        vr.addWidget(label("Spinal column with skeletal context", "muted"))
        vr.addStretch()
        for name in ("3D view", "Side", "Back"):
            vr.addWidget(
                button(name, lambda checked=False, n=name: self.spine.set_view(n), True)
            )
        vl.addLayout(vr)
        self.spine = SpineWidget()
        vl.addWidget(self.spine, 1)
        vl.addWidget(
            label(
                "Ivory: spinal column · Amber: region above threshold",
                "muted",
            )
        )
        dashboard.addWidget(visual, 1)
        right = QVBoxLayout()
        right.setSpacing(15)
        posture, pl = card()
        posture.setFixedWidth(300)
        pl.setSpacing(6)
        pl.addWidget(label("Posture check", "section"))
        self.banner = label("Waiting for simulated readings", "banner")
        self.banner.setWordWrap(True)
        pl.addWidget(self.banner)
        self.angle_labels = []
        self.state_labels = []
        for name in ("Upper back", "Lower back"):
            r = QHBoxLayout()
            r.addWidget(label(name))
            angle = label("0.0°", "metric")
            r.addStretch()
            r.addWidget(angle)
            pl.addLayout(r)
            state = label("Waiting", "muted")
            pl.addWidget(state)
            self.angle_labels.append(angle)
            self.state_labels.append(state)
        self.calibrate_button = button(
            "Set current posture as baseline", self.calibrate
        )
        self.calibrate_button.setEnabled(False)
        pl.addWidget(self.calibrate_button)
        self.baseline_label = label("Mock baseline: 0.0° / 0.0°", "muted")
        pl.addWidget(self.baseline_label)
        self.reset_button = button("Reset baseline", lambda: self.calibrate(True), True)
        pl.addWidget(self.reset_button)
        right.addWidget(posture)
        settings, sl = card()
        sl.setSpacing(6)
        sl.addWidget(label("Feedback settings", "section"))
        self.settings_detail = label("Applied by the simulated MCU", "muted")
        sl.addWidget(self.settings_detail)
        grid = QGridLayout()
        self.upper_spin = QDoubleSpinBox()
        self.lower_spin = QDoubleSpinBox()
        for i, (name, spin, value) in enumerate(
            [
                ("Upper threshold", self.upper_spin, 15),
                ("Lower threshold", self.lower_spin, 12),
            ]
        ):
            spin.setRange(0.02, 90)
            spin.setDecimals(2)
            spin.setSuffix("°")
            spin.setValue(value)
            grid.addWidget(label(name, "muted"), 0, i)
            grid.addWidget(spin, 1, i)
        sl.addLayout(grid)
        self.upper_recovery = QDoubleSpinBox()
        self.lower_recovery = QDoubleSpinBox()
        for i, (name, spin) in enumerate(
            (
                ("Upper recovery", self.upper_recovery),
                ("Lower recovery", self.lower_recovery),
            )
        ):
            spin.setRange(0.01, 89.99)
            spin.setDecimals(2)
            spin.setSuffix("°")
            spin.setValue(4)
            grid.addWidget(label(name, "muted"), 2, i)
            grid.addWidget(spin, 3, i)
        self.dwell = QDoubleSpinBox()
        self.dwell.setDecimals(3)
        self.dwell.setRange(0.001, 3600)
        self.dwell.setSuffix(" seconds")
        self.dwell.setValue(3)
        sl.addWidget(label("Sustained deviation", "muted"))
        sl.addWidget(self.dwell)
        self.apply_button = button("Apply to simulator", self.apply_settings, True)
        sl.addWidget(self.apply_button)
        self.settings_status = label("No physical feedback is sent.", "muted")
        self.settings_status.setWordWrap(True)
        sl.addWidget(self.settings_status)
        right.addWidget(settings)
        right.addStretch()
        dashboard.addLayout(right)
        layout.addLayout(dashboard, 1)
        simulator, sim = card()
        self.simulator_panel = simulator
        sr = QHBoxLayout()
        intro = QVBoxLayout()
        intro.addWidget(label("Simulated readings", "eyebrow"))
        intro.addWidget(label("Posture scenario", "section"))
        sr.addLayout(intro)
        sr.addStretch()
        self.scenario = QComboBox()
        self.scenario.addItems(
            [
                "Aligned",
                "Upper rounding",
                "Lower rounding",
                "Combined rounding",
                "Custom angles",
            ]
        )
        self.scenario.currentTextChanged.connect(self.set_scenario)
        sr.addWidget(self.scenario)
        self.pause_button = button("Pause stream", self.toggle_pause, True)
        sr.addWidget(self.pause_button)
        sim.addLayout(sr)
        self.custom_panel = QWidget()
        cr = QHBoxLayout(self.custom_panel)
        cr.setContentsMargins(0, 0, 0, 0)
        self.custom_sliders = []
        for name in ["Upper", "Lower"]:
            cr.addWidget(label(name))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-30, 45)
            slider.setAccessibleName(name + " mock flexion")
            slider.valueChanged.connect(self.custom_changed)
            cr.addWidget(slider)
            self.custom_sliders.append(slider)
        self.custom_values = label("0° / 0°", "muted")
        cr.addWidget(self.custom_values)
        self.custom_panel.hide()
        sim.addWidget(self.custom_panel)
        layout.addWidget(simulator)
        self.footer = label(
            "Simulated back readings. Anatomy is illustrative, not a medical reconstruction.",
            "muted",
        )
        body.addWidget(self.footer)
        history = QWidget()
        hl = QVBoxLayout(history)
        hl.addWidget(label("Session history", "title"))
        hl.addWidget(
            label(
                "Select a session to view its recorded angles · most recent 100 sessions",
                "muted",
            )
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Started (local time)", "Status", "Samples", "Within thresholds", "Source"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_session())
        hl.addWidget(self.table)
        hl.addWidget(button("View selected session", self.open_session, True))
        hl.addWidget(button("Refresh", self.show_history, True))
        self.pages.addWidget(history)
        self.transport.connect_device()
        self.stale_timer = QTimer(self)
        self.stale_timer.setInterval(500)
        self.stale_timer.timeout.connect(self.check_stale)
        self.stale_timer.start()

    def on_frame(self, f):
        self.last = f
        try:
            self.storage.record_sample(
                self.session,
                f,
                self.ble.settings if self.mode == "BLE vest" else self.settings,
                self.transport.baseline,
            )
        except Exception as exc:
            self.footer.setText(f"Sample recording failed: {exc}")
        self.samples += 1
        effective = self.ble.settings if self.mode == "BLE vest" else self.settings
        if effective is not None:
            self.evaluated_samples += 1
        if (
            effective is not None
            and abs(f.upper_deg) <= effective.upper_threshold
            and abs(f.lower_deg) <= effective.lower_threshold
        ):
            self.aligned += 1
        if self.previous_time is not None:
            self.active_seconds += max(
                0,
                min(
                    f.received_at - self.previous_time,
                    1.5 if self.mode == "BLE vest" else 0.1,
                ),
            )
        self.previous_time = f.received_at
        seconds = int(self.active_seconds)
        self.time_label.setText(f"{seconds // 60:02}:{seconds % 60:02}")
        self.percent_label.setText(
            f"{self.aligned / self.evaluated_samples:.0%}"
            if self.evaluated_samples
            else "—"
        )
        for angle, display, state, sd in zip(
            (f.upper_deg, f.lower_deg),
            self.angle_labels,
            (f.upper_state, f.lower_state),
            self.state_labels,
        ):
            display.setText(f"{angle:.1f}°")
            sd.setText(
                {
                    "aligned": "Within threshold",
                    "pending": "Above threshold · waiting",
                    "cue": "Simulated MCU cue active",
                    "above": "Above firmware trigger",
                    "unknown": "Firmware settings unknown",
                }[state]
            )
        status = (
            "Time for a posture check"
            if "cue" in (f.upper_state, f.lower_state)
            else "Deviation detected · timing duration"
            if "pending" in (f.upper_state, f.lower_state)
            else "You're within your thresholds"
        )
        if self.mode == "BLE vest":
            status = f"{self.ble.state.title()} · Alert requested: {'yes' if f.buzz else 'no'}"
            self.battery_label.setText("—")
            self.source_label.setText("BLE vest")
            self.device_status.setText(
                f"State: {self.ble.state} · Receiving wearable readings"
            )
        self.banner.setText(status)
        self.banner.setStyleSheet(
            "background:#fff1d6;color:#805b22;padding:8px;border-radius:3px;"
            if f.upper_state != "aligned" or f.lower_state != "aligned"
            else ""
        )
        self.calibrate_button.setEnabled(
            self.mode == "Simulator" or (self.connected and not self.ble.busy)
        )
        self.spine.set_posture(f)

    def stream_state(self):
        running = self.connected and not self.paused
        self.previous_time = None
        if running:
            self.transport.connect_device()
        else:
            self.transport.disconnect_device()
            if self.pending is not None:
                self.ack_timeout(
                    "Canceled: stream disconnected or paused; settings not applied."
                )
            self.banner.setText(
                "Paused · last reading held"
                if self.paused
                else "Disconnected · last reading held"
            )
            self.banner.setStyleSheet("")
            for state in self.state_labels:
                state.setText("Feedback inactive · last reading")
        self.connect_button.setText(
            "Disconnect simulator" if self.connected else "Connect simulator"
        )
        self.pause_button.setText("Resume stream" if self.paused else "Pause stream")
        self.pause_button.setEnabled(self.connected)
        self.source_label.setText(
            "Mock vest" if running else "Paused" if self.paused else "Offline"
        )
        self.calibrate_button.setEnabled(running and self.last is not None)
        self.reset_button.setEnabled(running)
        self.apply_button.setEnabled(running and self.pending is None)
        self.checkpoint()

    def toggle_connection(self):
        if self.mode == "BLE vest":
            if self.connected:
                self.ble.disconnect_device()
            else:
                device = self.device_select.currentData()
                if device is None:
                    self.banner.setText("Scan and select a PosturePal vest first.")
                    return
                try:
                    self.ble.connect_device(device)
                    self.banner.setText("Connecting and reading firmware status…")
                except RuntimeError as exc:
                    self.on_ble_error(str(exc))
            self.update_ble_controls()
            return
        self.connected = not self.connected
        self.paused = False
        self.stream_state()

    def toggle_pause(self):
        self.paused = not self.paused
        self.stream_state()

    def set_scenario(self, value):
        from .domain import Dwell

        self.mock.scenario = value
        self.mock.trackers = [Dwell(), Dwell()]
        self.custom_panel.setVisible(value == "Custom angles")

    def custom_changed(self):
        values = tuple(s.value() for s in self.custom_sliders)
        self.mock.custom = values
        self.custom_values.setText(f"{values[0]}° / {values[1]}°")

    def calibrate(self, reset=False):
        if self.mode == "BLE vest":
            self.ble_command("calibrate")
            return
        try:
            self.transport.calibrate(reset)
        except RuntimeError as exc:
            self.banner.setText(str(exc))
            return
        upper, lower = self.transport.baseline
        self.baseline_label.setText(f"Mock baseline: {upper:.1f}° / {lower:.1f}°")

    def apply_settings(self):
        try:
            requested = Settings(
                self.upper_spin.value(),
                self.lower_spin.value(),
                round(self.dwell.value() * 1000),
                self.upper_recovery.value(),
                self.lower_recovery.value(),
            )
        except ValueError as exc:
            self.settings_status.setText(str(exc))
            return
        self.next_request += 1
        self.pending = (self.next_request, requested)
        self.apply_button.setEnabled(False)
        self.settings_status.setText(
            "Waiting for firmware ACK and settings readback…"
            if self.mode == "BLE vest"
            else "Waiting for simulated MCU acknowledgment…"
        )
        self.ack_timer.start(15000 if self.mode == "BLE vest" else 2000)
        try:
            self.transport.request_settings(self.next_request, requested)
            if self.mode == "BLE vest":
                self.update_ble_controls()
        except RuntimeError as exc:
            self.ack_timeout(str(exc))

    def on_ack(self, ack):
        if (
            self.pending is None
            or ack.request_id != self.pending[0]
            or ack.settings != self.pending[1]
            or ack.source != ("ble" if self.mode == "BLE vest" else "mock")
        ):
            return
        self.settings = ack.settings
        self.pending = None
        self.ack_timer.stop()
        self.apply_button.setEnabled(self.connected and not self.paused)
        self.settings_status.setText(
            "Firmware ACK and settings readback confirmed."
            if ack.source == "ble"
            else "Acknowledged by simulated MCU."
        )
        try:
            self.storage.record_ack(self.session, ack)
        except Exception as exc:
            self.footer.setText(f"Settings applied, but local recording failed: {exc}")

    def ack_timeout(self, message="No acknowledgment: settings not applied."):
        self.pending = None
        self.ack_timer.stop()
        self.settings_status.setText(message)
        self.apply_button.setEnabled(self.connected and not self.paused)
        if self.mode == "BLE vest":
            self.update_ble_controls()

    def switch_mode(self, mode):
        self.mock.disconnect_device()
        self.ble.disconnect_device()
        self.ack_timer.stop()
        self.pending = None
        self.storage.checkpoint(self.session, self.samples, self.aligned, True)
        self.mode = mode
        self.transport = self.ble if mode == "BLE vest" else self.mock
        self.session = self.storage.start("ble" if mode == "BLE vest" else "mock")
        self.samples = self.aligned = self.evaluated_samples = 0
        self.active_seconds = 0
        self.previous_time = self.last = None
        self.time_label.setText("00:00")
        self.percent_label.setText("—")
        self.paused = False
        self.connected = mode == "Simulator"
        self.ble_panel.setVisible(mode == "BLE vest")
        self.simulator_panel.setVisible(mode == "Simulator")
        self.reset_button.setVisible(mode == "Simulator")
        self.clear_live(
            "Scan and connect to a PosturePal vest."
            if mode == "BLE vest"
            else "Waiting for simulated readings"
        )
        self.settings_detail.setText(
            "Firmware controls feedback · values confirmed by status"
            if mode == "BLE vest"
            else "Applied by the simulated MCU"
        )
        self.apply_button.setText(
            "Apply to vest" if mode == "BLE vest" else "Apply to simulator"
        )
        self.baseline_label.setText(
            "Firmware baseline unknown" if mode == "BLE vest" else "Mock baseline"
        )
        self.settings_status.setText(
            "Connect to read effective firmware settings."
            if mode == "BLE vest"
            else "No physical feedback is sent."
        )
        self.source_detail.setText(
            "1 Hz · wearable notifications"
            if mode == "BLE vest"
            else "20 Hz · simulated wearable"
        )
        self.battery_label.setText("—" if mode == "BLE vest" else "86%")
        self.battery_detail.setText(
            "Not reported by firmware" if mode == "BLE vest" else "Simulated value"
        )
        self.footer.setText(
            "Wearable angles · Alert flag is a request, not measured vibration. Anatomy is illustrative."
            if mode == "BLE vest"
            else "Simulated back readings. Anatomy is illustrative, not a medical reconstruction."
        )
        if mode == "Simulator":
            self.settings = self.mock.settings
            self.show_settings(self.settings)
            self.connect_button.setEnabled(True)
            for spin in (
                self.upper_spin,
                self.lower_spin,
                self.upper_recovery,
                self.lower_recovery,
                self.dwell,
            ):
                spin.setEnabled(True)
            self.stream_state()
        else:
            self.update_ble_controls()

    def clear_live(self, message):
        self.previous_time = None
        self.banner.setText(message)
        self.banner.setStyleSheet("")
        for angle in self.angle_labels:
            angle.setText("—")
        for state in self.state_labels:
            state.setText("No current reading")
        self.spine.upper = self.spine.lower = 0
        self.spine.states = ("unknown", "unknown")
        self.spine.update()
        self.source_label.setText("BLE vest" if self.connected else "Offline")

    def update_ble_controls(self, *_):
        if self.mode != "BLE vest" or self.closing:
            return
        idle = not self.ble.busy
        ready = self.connected and idle
        faulted = self.ble.state == "FAULT"
        functional = ready and not faulted
        self.fault_panel.setVisible(faulted)
        self.retry_button.setEnabled(ready and self.pending is None)
        self.scan_button.setEnabled(not self.connected and idle)
        self.device_select.setEnabled(not self.connected and idle)
        self.connect_button.setText(
            "Disconnect vest" if self.connected else "Connect vest"
        )
        self.connect_button.setEnabled(
            self.connected or (idle and self.device_select.currentData() is not None)
        )
        self.status_button.setEnabled(ready)
        self.command_button.setEnabled(ready and self.pending is None)
        self.command_input.setEnabled(ready and self.pending is None)
        self.ble_pause_button.setEnabled(functional and self.pending is None)
        self.ble_pause_button.setText(
            "Resume vest" if self.ble.state == "PAUSED" else "Pause vest"
        )
        self.calibrate_button.setEnabled(functional and self.pending is None)
        self.apply_button.setEnabled(
            functional and self.pending is None and self.ble.settings is not None
        )
        for spin in (
            self.upper_spin,
            self.lower_spin,
            self.upper_recovery,
            self.lower_recovery,
            self.dwell,
        ):
            spin.setEnabled(
                functional and self.pending is None and self.ble.settings is not None
            )

    def scan_devices(self):
        try:
            self.ble.scan()
            self.device_status.setText("Scanning for PosturePal vests…")
        except RuntimeError as exc:
            self.on_ble_error(str(exc))
        self.update_ble_controls()

    def on_devices(self, devices):
        if self.mode != "BLE vest":
            return
        self.device_select.clear()
        for device in devices:
            self.device_select.addItem(
                f"{device.name or 'PosturePal'} · {device.address}", device
            )
        self.device_status.setText(
            f"Found {len(devices)} vest(s). Select one and connect."
            if devices
            else "No vests found. Check power, BLE firmware and Bluetooth permission, then scan again."
        )
        self.update_ble_controls()

    def on_ble_connection(self, connected):
        if self.mode != "BLE vest" or self.closing:
            return
        self.connected = connected
        self.previous_time = None
        if connected:
            if self.ble.state == "FAULT":
                self.show_ble_fault()
            else:
                self.clear_live("Connected · waiting for wearable readings")
        else:
            if self.pending:
                self.ack_timeout(
                    "Disconnected: effective settings unknown. Reconnect to read status."
                )
            self.last = None
            self.device_status.setText("Disconnected · reconnect to read device status")
            self.clear_live("Disconnected · reconnect to read device status")
            self.settings_status.setText(
                "Effective settings unknown until reconnect and status readback."
            )
            self.baseline_label.setText("Firmware baseline unknown")
            self.checkpoint()
        self.update_ble_controls()

    def on_ble_error(self, message):
        if self.mode != "BLE vest" or self.closing:
            return
        self.device_log.appendPlainText(f"APP: {message}")
        self.diagnostics_panel.show()
        if self.ble.state == "FAULT":
            self.show_ble_fault()
        else:
            self.device_status.setText(message)
            self.banner.setText(message)
        if self.pending:
            self.ack_timeout(
                "Command unconfirmed; read device status before applying again. "
                + message
            )
        self.update_ble_controls()

    def show_settings(self, settings):
        self.upper_spin.setValue(settings.upper_threshold)
        self.lower_spin.setValue(settings.lower_threshold)
        self.upper_recovery.setValue(settings.upper_recovery)
        self.lower_recovery.setValue(settings.lower_recovery)
        self.dwell.setValue(settings.dwell_ms / 1000)

    def on_ble_event(self, event):
        if self.mode != "BLE vest" or self.closing:
            return
        if isinstance(event, str):
            self.device_log.appendPlainText(event)
        elif isinstance(event, ValueError):
            self.device_log.appendPlainText(f"APP: {event}")
        elif isinstance(event, Readback):
            self.settings = event.settings
            if self.pending is None:
                self.show_settings(event.settings)
                self.settings_status.setText("Effective settings read from firmware.")
        elif isinstance(event, Baseline):
            self.baseline_label.setText(
                "Baseline invalidated by firmware fault"
                if self.ble.state == "FAULT"
                else f"Firmware baseline: {event.angles[0]:.3f}° / {event.angles[1]:.3f}°"
                if event.angles
                else "Firmware baseline invalid · complete mounting and calibration"
            )
        elif isinstance(event, DeviceState):
            self.device_status.setText(f"State: {event.state} · {event.detail}")
            if event.state == "FAULT":
                self.show_ble_fault()
            elif event.state not in ("MONITORING", "ALERT"):
                self.last = None
                self.clear_live(f"{event.state.title()} · {event.detail}")
                self.baseline_label.setText(
                    "Firmware owns calibration · read status for baseline"
                )
        self.update_ble_controls()

    def show_ble_fault(self):
        cause = (
            self.ble.fault_reason or "Read device status for the firmware fault reason."
        )
        self.last = None
        self.clear_live("Vest fault · sensor readings stopped")
        self.banner.setStyleSheet(
            "background:#fff1ed;color:#783a2c;padding:8px;border-radius:3px;"
        )
        self.device_status.setText(
            "BLE connected · firmware FAULT"
            if self.connected
            else "Firmware FAULT reported"
        )
        self.fault_reason_label.setText(cause)
        self.fault_help.setText(
            "The sensor value reached the firmware's range limit. Keep the sensors still and check sensor wiring and power. "
            "After correcting the cause, retry the device. If the fault repeats at rest, investigate the reported sensor and I²C connection."
            if "IMU near full-scale" in cause
            else "The vest has stopped monitoring. Correct the reported cause, then retry the device."
        )
        self.baseline_label.setText("Baseline invalidated by firmware fault")
        self.fault_panel.show()
        self.diagnostics_panel.show()

    def on_ble_frame(self, frame):
        if self.mode == "BLE vest" and self.connected and not self.closing:
            self.on_frame(frame)

    def ble_command(self, command):
        try:
            self.ble.command(command)
            self.device_status.setText(f"Waiting for firmware: {command}")
        except (RuntimeError, ValueError) as exc:
            self.on_ble_error(str(exc))
        self.update_ble_controls()

    def toggle_diagnostics(self):
        self.diagnostics_panel.setVisible(self.diagnostics_panel.isHidden())

    def send_device_command(self):
        command = self.command_input.text().strip()
        if command:
            self.ble_command(command)

    def toggle_ble_pause(self):
        self.ble_command("resume" if self.ble.state == "PAUSED" else "pause")

    def check_stale(self):
        if (
            self.mode == "BLE vest"
            and self.connected
            and self.ble.state in ("MONITORING", "ALERT")
        ):
            if self.last is None or time.monotonic() - self.last.received_at > 3.5:
                self.clear_live(
                    "Waiting for fresh readings · no wearable sample in the last 3.5 seconds"
                )

    def checkpoint(self):
        try:
            self.storage.checkpoint(self.session, self.samples, self.aligned)
        except Exception as exc:
            self.footer.setText(f"Local history could not be saved: {exc}")

    def show_history(self):
        from datetime import datetime

        self.checkpoint()
        rows = self.storage.history()
        self.table.setRowCount(len(rows))
        for i, (started, ended, samples, aligned, source, session_id) in enumerate(
            rows
        ):
            values = [
                datetime.fromisoformat(started)
                .astimezone()
                .strftime("%b %d, %H:%M:%S"),
                "Ended" if ended else "Open / interrupted",
                str(samples),
                f"{aligned / samples:.0%}" if samples else "—",
                source,
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, session_id)
                self.table.setItem(i, j, item)
        if rows:
            self.table.selectRow(0)
        self.pages.setCurrentIndex(1)

    def open_session(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Session history", "Select a session first.")
            return
        self.checkpoint()
        session_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dialog = SessionDetails(self.storage, session_id, self)
        dialog.exec()

    def closeEvent(self, event):
        self.closing = True
        self.mock.disconnect_device()
        self.ble.shutdown()
        self.stale_timer.stop()
        self.ack_timer.stop()
        self.checkpoint_timer.stop()
        try:
            self.storage.checkpoint(self.session, self.samples, self.aligned, True)
        finally:
            self.storage.close()
        event.accept()


def main():
    try:
        app = create_application()
    except RuntimeError as exc:
        print(f"PosturePal startup failed: {exc}", file=sys.stderr)
        return 1
    app.setApplicationName("PosturePal")
    app.setOrganizationName("TeamB5")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    try:
        window = Window()
    except Exception as exc:
        QMessageBox.critical(None, "PosturePal startup failed", str(exc))
        return 1
    window.show()
    return app.exec()
